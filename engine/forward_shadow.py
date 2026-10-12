"""Prospective, never-retrofitted championship audit of FROZEN daily model picks.

The production model remains unchanged. We compare the pre-registered,
fixed-rho goal baseline with XGQ on EXACTLY the same verified future matches.
Research hybrid is descriptive only. No private provider rows are published.
Historical replay is deliberately EXCLUDED from this audit and promotion gate.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
import json
import math
from random import Random

from .understat_d1 import D1

PRIMARY = "xgq_production_formula"
CHALLENGER = "goal_fixed_rho"
EXPLORATORY = "hybrid_393_validation"
GATE_PAIRS = 350
MIN_LEAGUE = 25
OUTCOMES = ("home", "draw", "away")
REPORT_KEY = "understat_forward_shadow_championship"


def _moment(value):
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        raise ValueError("Forecast and grade clocks must have offsets")
    return dt


def _valid_score(x):
    return (isinstance(x, dict)
            and type(x.get("correct")) is bool
            and x.get("pick") in OUTCOMES
            and all(type(x.get(k)) in (int, float)
                    and math.isfinite(x[k]) and x[k] >= 0
                    for k in ("log_loss", "brier")))


def _summarize(records):
    n = len(records)
    if not n:
        return {"tested": 0, "correct": 0,
                "top_choice_accuracy": None, "log_loss": None, "brier": None}
    return {"tested": n,
            "correct": sum(x["correct"] for x in records),
            "top_choice_accuracy": round(sum(x["correct"] for x in records) / n, 6),
            "log_loss": round(sum(x["log_loss"] for x in records) / n, 6),
            "brier": round(sum(x["brier"] for x in records) / n, 6)}


def _paired_ci(pairs, draws=2000, seed=20261012):
    """Calendar-day / league clustered paired bootstrap. Higher gain is better."""
    blocks = defaultdict(list)
    for rec in pairs:
        blocks[(rec["league"], rec["date"])].append(
            rec["a"]["log_loss"] - rec["b"]["log_loss"])
    if len(blocks) < 20:
        return {"status": "insufficient_match_days", "paired_days": len(blocks)}
    groups = [blocks[key] for key in sorted(blocks)]
    rng = Random(seed)
    vals = []
    for _ in range(draws):
        selected = [groups[rng.randrange(len(groups))] for __ in groups]
        vals.append(sum(sum(group) for group in selected) /
                    sum(len(group) for group in selected))
    vals.sort()
    ci = [round(vals[int((draws - 1) * p)], 6) for p in (.025, .975)]
    return {"method": "paired_league_date_block_bootstrap", "paired_days": len(groups),
            "draws": draws, "log_loss_gain_ci95": ci,
            "reliably_better": ci[0] > 0}


def compare(frozen, grades, *, min_pairs=GATE_PAIRS):
    """All scores from the originally-frozen, immutable pre-kickoff fixture IDs."""
    if type(min_pairs) is not int or min_pairs < 1:
        raise ValueError("Invalid prospective audit threshold")
    if len({x["id"] for x in frozen}) != len(frozen):
        raise ValueError("Duplicate frozen fixture")
    if len({x["id"] for x in grades}) != len(grades):
        raise ValueError("Duplicate independently graded fixture")
    lookup = {row["id"]: row for row in frozen}
    paired = []
    counted = set()
    missing = 0
    for result in grades:
        f = lookup.get(result["id"])
        if f is None:
            raise ValueError("Graded match has no immutable frozen forecast")
        if f.get("status") != "frozen":
            continue
        try:
            kickoff = _moment(f["kickoff_utc"])
            stamp = _moment(f["frozen_at_utc"])
            grade_time = _moment(result["graded_at_utc"])
        except (ValueError, TypeError, KeyError) as exc:
            raise ValueError("Broken immutable clock") from exc
        if not stamp < kickoff or grade_time < kickoff + timedelta(minutes=115):
            raise ValueError("Invalid forward freeze / final-result timeline")
        if f.get("id") != result.get("id") or f.get("date") != result.get("date"):
            raise ValueError("Graded fixture identity mismatch")
        if f.get("source_match_id") != result.get("verified_understat_match_id"):
            raise ValueError("Graded source identity mismatch")
        a = result.get("models", {}).get(PRIMARY)
        b = result.get("models", {}).get(CHALLENGER)
        if not _valid_score(a) or not _valid_score(b):
            missing += 1
            continue
        if a["pick"] != f.get("picks", {}).get(PRIMARY) or b["pick"] != f.get("picks", {}).get(CHALLENGER):
            raise ValueError("Graded model pick does not match original forecast")
        optional = result["models"].get(EXPLORATORY)
        paired.append({"league": f["league"], "date": f["date"],
                       "a": a, "b": b,
                       "hybrid": optional if _valid_score(optional) else None})
        counted.add(f["id"])
    n = len(paired)
    pa = _summarize([x["a"] for x in paired])
    pb = _summarize([x["b"] for x in paired])
    league_counts = {code: sum(x["league"] == code for x in paired)
                     for code in ("en.1", "de.1", "es.1", "it.1", "fr.1")}
    ci = _paired_ci(paired) if n else {"status": "no_forward_pairs", "paired_days": 0}
    score_gain = round(pa["log_loss"] - pb["log_loss"], 6) if n else None
    brier_gain = round(pa["brier"] - pb["brier"], 6) if n else None
    acceptance = (
        n >= min_pairs
        and all(value >= MIN_LEAGUE for value in league_counts.values())
        and ci.get("reliably_better") is True
        and score_gain is not None and score_gain > 0
        and brier_gain is not None and brier_gain > 0
        and pb["top_choice_accuracy"] >= pa["top_choice_accuracy"]
    )
    return {
        "status": "eligible_for_manual_review" if acceptance
                  else "collecting_prospective_evidence" if n < min_pairs
                  else "not_proven_better",
        "decision": "KEEP_EXISTING_PRODUCTION_MODEL",
        "requires_manual_approval_to_switch": True,
        "models_pre_registered": [PRIMARY, CHALLENGER, EXPLORATORY],
        "primary": PRIMARY, "challenger": CHALLENGER,
        "candidate_is_fixed_rho_not_fitted_dc": True,
        "paired_verified_matches": n, "graded_without_paired_baseline": missing,
        "all_frozen": len(frozen), "all_graded": len(grades),
        "min_forward_pairs": min_pairs, "min_paired_per_league": MIN_LEAGUE,
        "by_league_paired_counts": league_counts,
        "xgq": pa, "goal_fixed_rho": pb,
        "hybrid_research_only": _summarize([x["hybrid"] for x in paired if x["hybrid"]]),
        "goal_over_xgq_log_loss_gain": score_gain,
        "goal_over_xgq_brier_gain": brier_gain,
        "paired_log_loss_ci95": ci,
        "gate_met": acceptance,
        "note": "Prospective frozen predictions only. Never compare with retrospective replays or rewrite past picks.",
    }


def _load_payloads(db, table):
    """D1 may cap result row counts; never silently audit a truncated ledger."""
    if table not in ("private_daily_forecasts", "private_daily_grades"):
        raise ValueError("Unexpected audit table")
    output, offset = [], 0
    while True:
        page = db.query(
            f"SELECT payload FROM {table} ORDER BY id LIMIT ? OFFSET ?",
            (250, offset))
        output.extend(json.loads(row["payload"]) for row in page)
        if len(output) > 20000:
            raise ValueError("Prospective audit ledger exceeds safety limit")
        if len(page) < 250:
            break
        offset += len(page)
    return output


def main():
    db = D1()
    frozen = _load_payloads(db, "private_daily_forecasts")
    grades = _load_payloads(db, "private_daily_grades")
    report = compare(frozen, grades)
    db.query("INSERT OR REPLACE INTO metadata(k,v) VALUES(?,?)",
             (REPORT_KEY, json.dumps(report, separators=(",", ":"))))
    # Only summary counts leave the private D1; no provider IDs/team names.
    print(json.dumps({"shadow_status": report["status"],
                      "paired": report["paired_verified_matches"],
                      "target": report["min_forward_pairs"],
                      "gate_met": report["gate_met"]}, sort_keys=True))
    return report


if __name__ == "__main__":
    main()
