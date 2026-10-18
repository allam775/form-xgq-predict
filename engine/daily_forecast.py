"""Chronology-safe daily 1X2 forecasts for five major leagues (private D1).

Only owner-authorized Understat league indexes provide fixture identities.
Never publish provider-derived data, never create a forecast after kickoff,
never overwrite an earlier forecast, and never call retrospective work live skill.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
import json
import math
import re

from .provider_understat import SOURCE, LEAGUES, fetch as understat_fetch
from .understat_d1 import D1
from .understat_backfill import validate_config
from .xgq import normalized, predict_xgq
from .understat_championship import _dc_baseline, _elo_probs
from .understat_hybrid import hybrid_probs
from .feature_ladder import stage1_probs
from .stage3_form import stage3_probs
from .comprehensive import (annotated_opponent_ratings, ensemble,
                            APPROVED_PARAMS, STAGE3_PRESET)
from .draw_lab import (apply_draw_calibration, feature_vector,
                       draw_features_for_fixture, FROZEN_DRAW_WEIGHTS, DRAW_VERSION)
from .prematch_ledger import _ratings_by_league, normalize_probabilities

FORECASTS = "private_daily_forecasts"
GRADES = "private_daily_grades"
LEAD = timedelta(minutes=30)
HORIZON = timedelta(hours=72)
OUTCOMES = ("home", "draw", "away")
# Every new forecast must retain every independently computed registered model.
MODEL_SUITE = (
    "xgq_production_formula", "goal_fixed_rho", "elo",
    "hybrid_393_validation", "stage1_volume_xgq",
    "stage3_opponent_form", "penniless_comprehensive",
    "penniless_draw_calibrated",
)
MODEL_SUITE_VERSION = "penniless-eight-models-forward-v1-20261018"


def _utc(value):
    if value.tzinfo is None:
        raise ValueError("A timezone-aware clock is required")
    return value.astimezone(timezone.utc)


def _kickoff(raw):
    """Understat league-index datetime is UTC; refuse dates without clock time."""
    if not isinstance(raw, str) or not re.match(
        r"^\d{4}-\d\d-\d\d[ T]\d\d:\d\d", raw
    ):
        raise ValueError("No trustworthy kickoff time")
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("Invalid kickoff timestamp") from None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else _utc(dt)


def fixtures_from_index(payload, league, *, now):
    if league not in LEAGUES or not isinstance(payload, dict) or not isinstance(payload.get("dates"), list):
        raise ValueError("Invalid Understat fixture index")
    output = []
    for event in payload["dates"]:
        if not isinstance(event, dict) or event.get("isResult") is not False:
            continue
        mid = str(event.get("id", ""))
        h, a = event.get("h"), event.get("a")
        if not re.fullmatch(r"[1-9]\d{0,9}", mid) or not isinstance(h, dict) or not isinstance(a, dict):
            continue
        home, away = h.get("title"), a.get("title")
        if not isinstance(home, str) or not isinstance(away, str):
            continue
        home_id, away_id = normalized(home), normalized(away)
        if not home_id or not away_id or home_id == away_id:
            continue
        try:
            kickoff = _kickoff(event.get("datetime"))
        except ValueError:
            continue
        if not now + LEAD < kickoff <= now + HORIZON:
            continue
        if any(not re.fullmatch(r"[1-9]\d*", str(x.get("id", ""))) for x in (h, a)):
            continue
        output.append({
            "id": f"{league}|{mid}", "league": league, "source_match_id": mid,
            "date": kickoff.date().isoformat(), "kickoff_utc": kickoff.isoformat(),
            "home": home, "away": away, "h": home_id, "a": away_id,
        })
    return output


def fetch_upcoming(leagues, *, now, fetcher=understat_fetch):
    season = now.year if now.month >= 7 else now.year - 1
    found = {}
    for league in leagues:
        payload = fetcher("league", (league, season))
        for item in fixtures_from_index(payload, league, now=now):
            if item["id"] in found and found[item["id"]] != item:
                raise ValueError("Conflicting source fixture identity")
            found[item["id"]] = item
    return sorted(found.values(), key=lambda x: (x["kickoff_utc"], x["id"]))


def _forecast(fixture, league_rows, ratings, *, now):
    # Conservative no-leakage policy: only verified games on earlier UTC dates.
    prior = [r for r in league_rows if r["date"] < fixture["date"]
             and r["date"] < now.date().isoformat()]
    team_games = {
        "home": sum(fixture["h"] in (r["h"], r["a"]) for r in prior),
        "away": sum(fixture["a"] in (r["h"], r["a"]) for r in prior),
    }
    if len(prior) < 40 or min(team_games.values()) < 5:
        return None, "insufficient_verified_history"
    source_fixture = {
        "league": fixture["league"], "date": fixture["date"],
        "home_team": fixture["home"], "away_team": fixture["away"],
    }
    primary, reason = predict_xgq(source_fixture, prior, fixture["date"])
    if primary is None:
        return None, reason or "unavailable_verified_shot_form"
    models = {"xgq_production_formula": normalize_probabilities({k: primary["probabilities"][k] for k in OUTCOMES})}
    goal_baseline = _dc_baseline(prior, fixture)
    if not goal_baseline:
        return None, "missing_goal_baseline_for_approved_stage1"
    models["goal_fixed_rho"] = normalize_probabilities(goal_baseline)
    # Approved 2026-10-17: Stage 1 now drives NEW fixtures only. Its xG/xGA,
    # shot volume and XGQ terms are trained strictly on older verified games.
    # Already-frozen XGQ predictions are immutable and keep their original model.
    stage1 = stage1_probs(prior, fixture, goal_baseline, (.50, .25, .30))
    if stage1 is None:
        return None, "missing_verified_stage1_shot_evidence"
    models["stage1_volume_xgq"] = normalize_probabilities(stage1)
    hybrid = hybrid_probs(prior, fixture, goal_baseline, (.35, .30))
    if hybrid is None:
        return None, "missing_verified_hybrid"
    models["hybrid_393_validation"] = normalize_probabilities(hybrid)
    elo = _elo_probs(prior, ratings, fixture)
    if not elo:
        return None, "missing_elo_for_approved_comprehensive"
    models["elo"] = normalize_probabilities(elo)
    # Stage 3 requires opponents' Elo values *before* the old fixtures:
    # reconstruct them chronologically and update ratings after each match day.
    # Never silently substitute Stage 1 under a Stage 3 model name.
    decorated_prior = annotated_opponent_ratings(prior)
    stage3 = stage3_probs(decorated_prior, fixture, goal_baseline, STAGE3_PRESET)
    if stage3 is None:
        return None, "missing_genuine_stage3_opponent_form"
    models["stage3_opponent_form"] = normalize_probabilities(stage3)
    all_components = {
        "stage1": models["stage1_volume_xgq"],
        "stage3": models["stage3_opponent_form"],
        "elo": models["elo"],
        "dc": models["goal_fixed_rho"],
    }
    models["penniless_comprehensive"] = normalize_probabilities(
        ensemble(all_components, APPROVED_PARAMS))
    # Lagged draw-specific calibration, selected only from earlier seasons.
    # Crucially, this modifies honest probabilities, NOT forced 1X2 draw picks.
    lagged_draw = draw_features_for_fixture(prior, fixture)
    if lagged_draw is None:
        return None, "missing_verified_draw_form_for_v2"
    models["penniless_draw_calibrated"] = normalize_probabilities(
        apply_draw_calibration(
            models["penniless_comprehensive"],
            feature_vector({"models": all_components, "draw_features": lagged_draw}),
            FROZEN_DRAW_WEIGHTS))
    if set(models) != set(MODEL_SUITE):
        return None, "incomplete_eight_model_suite"
    return {
        "id": fixture["id"], "league": fixture["league"],
        "date": fixture["date"], "source_match_id": fixture["source_match_id"],
        "home": fixture["home"], "away": fixture["away"],
        "home_id": fixture["h"], "away_id": fixture["a"],
        "kickoff_utc": fixture["kickoff_utc"],
        "frozen_at_utc": now.isoformat(),
        "model": "penniless_draw_calibrated", "model_version": DRAW_VERSION,
        "model_suite_version": MODEL_SUITE_VERSION,
        "complete_model_suite": True,
        "registered_models": list(MODEL_SUITE),
        "status": "frozen",
        "models": models,
        "picks": {name: max(OUTCOMES, key=lambda v: probs[v]) for name, probs in models.items()},
        "prior_team_games": team_games,
        "prior_verified_matches": len(prior),
        "source": SOURCE,
        "source_evidence_end_lt": min(fixture["date"], now.date().isoformat()),
        "production_formula_unchanged": False,
        "original_xgq_preserved_as_comparator": True,
        "stage3_lagged_opponent_ratings": True,
        "stage3_missing_replaced_by_stage1": False,
        "comprehensive_frozen_params": list(APPROVED_PARAMS),
        "draw_calibration_coefficients": list(FROZEN_DRAW_WEIGHTS),
        "draw_only_probability_calibration": True,
        "no_forced_draw_pick": True,
        "creativity_metrics_not_yet_approved_for_production": True,
        "experimental_models_not_promoted": True,
    }, None


def ensure_tables(db):
    db.query(f"CREATE TABLE IF NOT EXISTS {FORECASTS} (id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
    db.query(f"CREATE TABLE IF NOT EXISTS {GRADES} (id TEXT PRIMARY KEY, payload TEXT NOT NULL)")


def freeze(db, *, now=None, fetcher=understat_fetch):
    now = _utc(now or datetime.now(timezone.utc))
    leagues, _, _ = validate_config(db.get_setting())
    # No provider fixture discovery if authorization is absent.
    ensure_tables(db)
    fixtures = fetch_upcoming(leagues, now=now, fetcher=fetcher)
    known = {r["id"] for r in db.query(f"SELECT id FROM {FORECASTS}")}
    history = db.history()
    pools = defaultdict(list)
    for r in history:
        if r["source"] == SOURCE and r["date"] < now.date().isoformat():
            pools[r["league"]].append(r)
    for league in pools:
        pools[league].sort(key=lambda r: (r["date"], r["id"]))
    ratings = _ratings_by_league([r for values in pools.values() for r in values])
    report = Counter()
    report["upcoming"] = len(fixtures)
    for fixture in fixtures:
        if fixture["id"] in known:
            report["already_frozen"] += 1
            continue
        row, why = _forecast(fixture, pools[fixture["league"]],
                             ratings.get(fixture["league"], {}), now=now)
        if row is None:
            report["withheld"] += 1
            report["reason_" + why] += 1
            continue
        db.query(f"INSERT OR IGNORE INTO {FORECASTS}(id,payload) VALUES (?,?)",
                 (row["id"], json.dumps(row, ensure_ascii=False, separators=(",", ":"))))
        report["newly_frozen"] += 1
    report["total_frozen"] = db.query(f"SELECT COUNT(*) AS n FROM {FORECASTS}")[0]["n"]
    # Aggregate counts only; no private fixture identities in public Actions logs.
    return dict(report)


def grade(db, *, now=None):
    now = _utc(now or datetime.now(timezone.utc))
    ensure_tables(db)
    saved = [json.loads(r["payload"]) for r in
             db.query(f"SELECT payload FROM {FORECASTS} ORDER BY id")]
    previous = {r["id"] for r in db.query(f"SELECT id FROM {GRADES}")}
    history = {(r["league"], r["source_match_id"]): r for r in db.history()}
    newly = 0
    for row in saved:
        if row["id"] in previous or row["status"] != "frozen":
            continue
        if now < datetime.fromisoformat(row["kickoff_utc"]) + timedelta(minutes=115):
            continue
        actual = history.get((row["league"], row["source_match_id"]))
        if not actual or (actual["date"] != row["date"] or
                          actual["h"] != row["home_id"] or actual["a"] != row["away_id"]):
            continue
        outcome = ("home" if actual["hg"] > actual["ag"] else
                   "draw" if actual["hg"] == actual["ag"] else "away")
        scores = {}
        for name, probs in row["models"].items():
            scores[name] = {
                "pick": row["picks"][name],
                "correct": row["picks"][name] == outcome,
                "log_loss": round(-math.log(max(probs[outcome], 1e-12)), 8),
                "brier": round(sum((probs[k] - (k == outcome)) ** 2 for k in OUTCOMES), 8),
            }
        result = {
            "id": row["id"], "date": row["date"], "outcome": outcome,
            "hg": actual["hg"], "ag": actual["ag"],
            "verified_understat_match_id": actual["source_match_id"],
            "graded_at_utc": now.isoformat(), "models": scores,
        }
        db.query(f"INSERT OR IGNORE INTO {GRADES}(id,payload) VALUES (?,?)",
                 (row["id"], json.dumps(result, ensure_ascii=False, separators=(",", ":"))))
        newly += 1
    total = db.query(f"SELECT COUNT(*) AS n FROM {GRADES}")[0]["n"]
    return {"newly_graded": newly, "total_graded": total,
            "total_frozen": len(saved), "pending": len(saved) - total}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=("freeze", "grade", "both"), nargs="?", default="both")
    args = ap.parse_args(argv)
    db = D1()
    output = {}
    if args.action in ("grade", "both"):
        output["grades"] = grade(db)
    if args.action in ("freeze", "both"):
        output["forecast"] = freeze(db)
    print(json.dumps(output, ensure_ascii=False, sort_keys=True))
    return output


if __name__ == "__main__":
    main()
