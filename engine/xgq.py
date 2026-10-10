"""Strict shot-level XGQ ingestion and pre-match inference (standard library only).

XGQ uses exactly the public source's shot-level xG values:
    XGQ = sum(xG_for_each_shot ** 2) / number_of_shots
Never substitute aggregate xG / shots as the underlying shot series.
"""
from __future__ import annotations
from datetime import date, timedelta
from collections import defaultdict
import math
import re
import unicodedata

LEAGUE_MAP = {
    "La Liga": "es.1", "Spanish Primera Division": "es.1",
    "Premier League": "en.1", "English Premier League": "en.1",
    "Bundesliga": "de.1", "Serie A": "it.1", "Ligue 1": "fr.1",
    "2. Bundesliga": "de.2", "EFL Championship": "en.2",
}


def normalized(name):
    value = unicodedata.normalize("NFKD", str(name or "").lower())
    value = "".join(c for c in value if not unicodedata.combining(c))
    value = value.replace("&", " and ")
    value = re.sub(r"[^a-z0-9]+", " ", value).strip()
    return re.sub(r"^(fc|afc)\s+|\s+(fc|afc)$", "", value).strip()


def shot_quality(shot_xgs):
    if not isinstance(shot_xgs, list) or not shot_xgs:
        raise ValueError("Complete shot-level xG array is required")
    if len(shot_xgs) > 150 or any(type(x) not in (int, float) or
                                   not math.isfinite(x) or x < 0 or x > 1
                                   for x in shot_xgs):
        raise ValueError("Invalid shot probabilities")
    return {
        "shots": len(shot_xgs),
        "xg": round(sum(shot_xgs), 6),
        "xgq": round(sum(x * x for x in shot_xgs) / len(shot_xgs), 8),
    }


def strict_row(row):
    """Validate an owner-supplied match with complete arrays, not aggregates."""
    if not isinstance(row, dict):
        raise ValueError("Not a match")
    dt = date.fromisoformat(row["date"])
    league = str(row["league"]).strip()
    home = str(row["home_team"]).strip()
    away = str(row["away_team"]).strip()
    hg, ag = row.get("home_goals"), row.get("away_goals")
    if not league or not normalized(home) or not normalized(away) or normalized(home) == normalized(away):
        raise ValueError("Invalid fixture identity")
    if any(type(g) is not int or not 0 <= g <= 30 for g in (hg, ag)):
        raise ValueError("Match must have a verified final result")
    h = shot_quality(row["home_shots_xg"])
    a = shot_quality(row["away_shots_xg"])
    return {"id": f"{league}|{dt.isoformat()}|{normalized(home)}|{normalized(away)}",
            "date": dt.isoformat(), "league": league, "home": home, "away": away,
            "h": normalized(home), "a": normalized(away), "hg": hg, "ag": ag,
            "home_xgq": h["xgq"], "away_xgq": a["xgq"],
            "home_xg": h["xg"], "away_xg": a["xg"],
            "home_shots": h["shots"], "away_shots": a["shots"],
            "source": str(row.get("source") or "verified_shot_feed")[:120],
            "source_match_id": str(row.get("source_match_id") or "")[:80]}


def statsbomb_to_row(match, events, league):
    """Read published StatsBomb open-data event/match JSON structures."""
    if not isinstance(events, list) or not isinstance(match, dict):
        raise ValueError("StatsBomb match and events must be structured")
    home = match["home_team"]["home_team_name"]
    away = match["away_team"]["away_team_name"]
    h_id = match["home_team"]["home_team_id"]
    a_id = match["away_team"]["away_team_id"]
    shots = {h_id: [], a_id: []}
    for event in events:
        if event.get("type", {}).get("name") != "Shot":
            continue
        tid = event.get("team", {}).get("id")
        if tid not in shots:
            raise ValueError("Unexpected shooting team")
        xg = event.get("shot", {}).get("statsbomb_xg")
        # Missing xG means the game cannot truthfully be labelled shot-based.
        if type(xg) not in (int, float):
            raise ValueError("Missing xG on shot")
        shots[tid].append(xg)
    data = {"league": league, "date": match["match_date"], "home_team": home,
            "away_team": away, "home_goals": match["home_score"], "away_goals": match["away_score"],
            "home_shots_xg": shots[h_id], "away_shots_xg": shots[a_id],
            "source": "StatsBomb Open Data", "source_match_id": str(match["match_id"])}
    return strict_row(data)


def weighted_form(rows, league, team, prediction_day, lookback=16, half_life=90):
    prior = sorted((r for r in rows if r["league"] == league and r["date"] < prediction_day and
                   (r["h"] == team or r["a"] == team)), key=lambda r: r["date"], reverse=True)[:lookback]
    if len(prior) < 5:
        return None
    asof = date.fromisoformat(prediction_day)
    weighted_for = weighted_against = weight_sum = 0
    for row in prior:
        age = (asof - date.fromisoformat(row["date"])).days
        weight = math.exp(-math.log(2) * age / half_life)
        is_home = row["h"] == team
        weighted_for += weight * (row["home_xgq"] if is_home else row["away_xgq"])
        weighted_against += weight * (row["away_xgq"] if is_home else row["home_xgq"])
        weight_sum += weight
    return {"n": len(prior), "xgq_for": weighted_for / weight_sum,
            "xgq_against": weighted_against / weight_sum,
            "last_seen": prior[0]["date"]}


def poisson_probabilities(home_lam, away_lam, max_goals=12):
    def probs(lam):
        out = [math.exp(-lam)]
        for k in range(1, max_goals + 1):
            out.append(out[-1] * lam / k)
        # Normalize the tiny truncated high-score tail.
        s = sum(out)
        return [x / s for x in out]
    hp, ap = probs(home_lam), probs(away_lam)
    p_home = sum(hp[i] * ap[j] for i in range(len(hp)) for j in range(len(ap)) if i > j)
    p_draw = sum(hp[i] * ap[i] for i in range(len(hp)))
    p_away = 1 - p_home - p_draw
    scores = sorted(({"score": f"{i}-{j}", "p": round(hp[i] * ap[j], 5)}
                     for i in range(6) for j in range(6)), key=lambda x: x["p"], reverse=True)
    return {"home": round(p_home, 5), "draw": round(p_draw, 5),
            "away": round(p_away, 5), "scorelines": scores[:5]}


def predict_xgq(fixture, history, today, max_stale_days=120, *,
                lookback=16, half_life=90, prior_strength=1.0):
    """Return a strictly pre-match, shot-verified forecast.

    Optional research parameters preserve the default production calculation.
    They are not automatically chosen from future matches or published.
    """
    if (type(lookback) is not int or lookback < 5 or lookback > 64 or
            type(half_life) not in (int, float) or not 15 <= half_life <= 730 or
            type(prior_strength) not in (int, float) or not .1 <= prior_strength <= 10):
        raise ValueError("Invalid research-model parameters")
    d = fixture["date"]
    if d < today:
        return None, "not_upcoming"
    league = fixture["league"]
    home = normalized(fixture["home_team"])
    away = normalized(fixture["away_team"])
    if home == away or not home or not away:
        return None, "invalid_teams"
    rows = [r for r in history if r["league"] == league and r["date"] < d and r["date"] < today]
    h = weighted_form(rows, league, home, d, lookback, half_life)
    a = weighted_form(rows, league, away, d, lookback, half_life)
    if h is None or a is None:
        return None, "insufficient_verified_shots"
    last = max(h["last_seen"], a["last_seen"])
    if (date.fromisoformat(today) - date.fromisoformat(h["last_seen"])).days > max_stale_days or \
       (date.fromisoformat(today) - date.fromisoformat(a["last_seen"])).days > max_stale_days:
        return None, "stale_xgq"
    base_rows = [r for r in rows if r["date"] >= (date.fromisoformat(d) - timedelta(days=900)).isoformat()]
    if len(base_rows) < 40:
        return None, "small_league_sample"
    avg_xgq = sum(r["home_xgq"] + r["away_xgq"] for r in base_rows) / (2 * len(base_rows))
    if avg_xgq < 1e-6:
        return None, "invalid_league_xgq"
    avg_goals_home = sum(r["hg"] for r in base_rows) / len(base_rows)
    avg_goals_away = sum(r["ag"] for r in base_rows) / len(base_rows)
    # Conservative shrinkage; both shot creation and shot prevention use real XGQ.
    def ratio(value):
        return max(.55, min(1.55, (value + prior_strength * avg_xgq) / ((1 + prior_strength) * avg_xgq)))
    lh = max(.2, min(3.7, avg_goals_home * ratio(h["xgq_for"]) * ratio(a["xgq_against"])))
    la = max(.2, min(3.7, avg_goals_away * ratio(a["xgq_for"]) * ratio(h["xgq_against"])))
    return {"league": league, "date": d, "home": fixture["home_team"],
            "away": fixture["away_team"], "id": f"{league}|{d}|{home}|{away}",
            "model": "verified-shot-xgq-poisson-v1", "source_basis": "verified_shot_level_xg",
            "home_xgq_for": round(h["xgq_for"], 6), "away_xgq_for": round(a["xgq_for"], 6),
            "home_xgq_against": round(h["xgq_against"], 6),
            "away_xgq_against": round(a["xgq_against"], 6),
            "history_home": h["n"], "history_away": a["n"],
            "last_home_xgq": h["last_seen"], "last_away_xgq": a["last_seen"],
            "expected_home_goals": round(lh, 3), "expected_away_goals": round(la, 3),
            "probabilities": poisson_probabilities(lh, la)}, None


def holdout_metrics(history, asof, max_test=180):
    """Chronological research diagnostic; never call it live prediction accuracy."""
    games = sorted((r for r in history if r["date"] < asof), key=lambda r: r["date"])
    if len(games) < 70:
        return {"status": "insufficient", "tested": 0}
    candidate_dates = sorted(set(r["date"] for r in games))
    cutoff = candidate_dates[max(1, int(len(candidate_dates) * .8))]
    evaluated = []
    for game in games:
        if game["date"] < cutoff:
            continue
        forecast, reason = predict_xgq({"date": game["date"], "league": game["league"],
                        "home_team": game["home"], "away_team": game["away"]},
                        games, game["date"], max_stale_days=9999)
        if not forecast:
            continue
        p = forecast["probabilities"]
        outcome = "home" if game["hg"] > game["ag"] else "away" if game["hg"] < game["ag"] else "draw"
        evaluated.append((p, outcome))
        if len(evaluated) >= max_test:
            break
    if len(evaluated) < 25:
        return {"status": "insufficient", "tested": len(evaluated)}
    loss = sum(-math.log(max(1e-9, p[outcome])) for p, outcome in evaluated) / len(evaluated)
    brier = sum(sum((p[k] - int(k == outcome))**2 for k in ("home", "draw", "away"))
                for p, outcome in evaluated) / len(evaluated)
    hit = sum(max(p, key=lambda k: p[k] if k in ("home", "draw", "away") else -1) == outcome
              for p, outcome in evaluated) / len(evaluated)
    return {"status": "retrospective", "tested": len(evaluated), "log_loss": round(loss, 4),
            "brier": round(brier, 4), "top_choice_accuracy": round(hit, 4),
            "note": "Chronological replay. Evaluation quality depends on event coverage and source history."}
