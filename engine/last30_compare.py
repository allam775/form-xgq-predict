"""Paired retrospective Stage 1 vs Stage 3 on the last 30 COMPLETE UTC dates.

This is a chronological *replay*, not a previously frozen forward record.
Stage 1 parameters (.50,.25,.30) and Stage 3 parameters (.25,.15) were
selected using historical data that can overlap this window. No retuning.
Never print private fixture identities or provider-owned shot data to public CI.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from itertools import groupby
import hashlib
import json
import math

from .feature_ladder import stage1_probs
from .stage3_form import stage3_probs, STAGE1_SELECTED
from .understat_championship import _dc_baseline, _elo_probs, _update_elo_batch
from .understat_quality import actual_outcome
from .understat_private import verified_row
from .understat_d1 import D1

OUTCOMES = ("home", "draw", "away")
STAGE3_PARAMS = (.25, .15)
REPORT_KEY = "penniless_stage1_stage3_last30_completed"


def _metrics(records, model):
    if not records:
        return {"n": 0, "correct": 0, "accuracy": None, "log_loss": None,
                "brier": None, "draw_picks": 0}
    loss = brier = 0.0
    hits = Counter()
    pick_counts = Counter()
    draw_sum = 0.0
    for r in records:
        p = r[model]
        actual = r["actual"]
        pick = max(OUTCOMES, key=lambda k: p[k])
        hits[actual] += int(pick == actual)
        pick_counts[pick] += 1
        loss -= math.log(max(1e-12, p[actual]))
        brier += sum((p[k] - int(k == actual))**2 for k in OUTCOMES)
        draw_sum += p["draw"]
    n = len(records)
    return {"n": n, "correct": sum(hits.values()),
            "accuracy": round(sum(hits.values())/n, 6),
            "log_loss": round(loss/n, 6),
            "brier": round(brier/n, 6),
            "draw_picks": pick_counts["draw"],
            "home_picks": pick_counts["home"],
            "away_picks": pick_counts["away"],
            "mean_draw_probability": round(draw_sum/n, 6),
            "correct_by_actual": {k: hits[k] for k in OUTCOMES}}


def compare(rows, *, start, end, stage3_params=STAGE3_PARAMS):
    start_day, end_day = date.fromisoformat(start), date.fromisoformat(end)
    if not start_day <= end_day:
        raise ValueError("Invalid completed-date window")
    if not (isinstance(stage3_params, tuple) and stage3_params in
            ((0.,0.),(.15,0.),(.25,0.),(.15,.15),(.25,.15),(.35,.25))):
        raise ValueError("Stage 3 parameters must be from the preregistered grid")
    records = [verified_row(r) for r in rows if r["date"] <= end]
    if len(records) != len({r["id"] for r in records}):
        raise ValueError("Duplicate verified match identity")
    groups = defaultdict(list)
    for r in records:
        groups[r["league"]].append(r)
    expected = 0
    paired = []
    withheld = Counter()
    for league, games in sorted(groups.items()):
        games.sort(key=lambda r: (r["date"], r["id"]))
        prior = []
        ratings = {}
        for day, same_day in groupby(games, lambda r: r["date"]):
            batch = list(same_day)
            if start <= day <= end:
                expected += len(batch)
                recent = [r for r in prior if r["date"] >=
                          (date.fromisoformat(day)-timedelta(days=900)).isoformat()]
                if len(recent) < 40:
                    withheld["insufficient_prior_league_games"] += len(batch)
                else:
                    for match in batch:
                        game = {"league": league, "date": day,
                                "h": match["h"], "a": match["a"]}
                        dc = _dc_baseline(recent, game)
                        if dc is None:
                            withheld["missing_dc"] += 1
                            continue
                        s1 = stage1_probs(recent, game, dc, STAGE1_SELECTED)
                        s3 = stage3_probs(recent, game, dc, stage3_params)
                        if not s1 or not s3:
                            withheld["insufficient_prior_stage_features"] += 1
                            continue
                        elo = _elo_probs(recent, ratings, game)
                        models = {"stage1": s1, "stage3": s3, "dc": dc}
                        if elo:
                            models["elo"] = elo
                        for name, probs in models.items():
                            if set(probs) != set(OUTCOMES) or any(
                                not math.isfinite(probs[k]) or probs[k] < 0
                                for k in OUTCOMES
                            ) or abs(sum(probs.values()) - 1) > .00001:
                                raise ValueError("Invalid 1X2: " + name)
                        paired.append({"league": league, "date": day,
                                       "actual": actual_outcome(match), **models})
            # Match-day outcomes are deliberately applied AFTER every fixture that day.
            annotated = [{**m,
                          "prior_opponent_elo_home": ratings.get(m["a"], 1500),
                          "prior_opponent_elo_away": ratings.get(m["h"], 1500)}
                         for m in batch]
            _update_elo_batch(ratings, batch)
            prior.extend(annotated)
    models = ("stage1", "stage3", "dc", "elo")
    common = [r for r in paired if all(name in r for name in models)]
    result = {"status": "retrospective_paired" if common else "insufficient",
              "start": start, "end": end, "calendar_days": (end_day-start_day).days+1,
              "verified_history_as_of_end": len(records),
              "eligible_match_candidates": expected,
              "paired_games": len(common), "withheld": dict(withheld),
              "stage1_params": STAGE1_SELECTED,
              "stage3_params": stage3_params,
              "models": {m: _metrics(common, m) for m in models},
              "per_league": {l: {m: _metrics([r for r in common if r["league"]==l],m)
                                  for m in models}
                             for l in sorted({r["league"] for r in common})},
              "per_date": {d: {m: _metrics([r for r in common if r["date"]==d],m)
                                for m in ("stage1","stage3")}
                           for d in sorted({r["date"] for r in common})},
              "actual_results": dict(Counter(r["actual"] for r in common)),
              "generated_at_utc": datetime.now(timezone.utc).isoformat(),
              "warning": "Chronological fixture features, but parameters were chosen on historically overlapping data: NOT blind out-of-sample or original frozen forecasts.",
              "production_forecasts_unchanged": True}
    if common:
        a = lambda r,m: max(OUTCOMES, key=lambda k: r[m][k]) == r["actual"]
        result["head_to_head"] = {
            "both_correct": sum(a(r,"stage1") and a(r,"stage3") for r in common),
            "stage1_only_correct": sum(a(r,"stage1") and not a(r,"stage3") for r in common),
            "stage3_only_correct": sum(a(r,"stage3") and not a(r,"stage1") for r in common),
            "both_incorrect": sum(not a(r,"stage1") and not a(r,"stage3") for r in common),
            "different_picks": sum(max(OUTCOMES,key=lambda k:r["stage1"][k]) !=
                                   max(OUTCOMES,key=lambda k:r["stage3"][k]) for r in common)}
        report_ids = sorted((r["league"],r["date"],r["actual"]) for r in common)
        result["paired_record_fingerprint"] = hashlib.sha256(
            json.dumps(report_ids,separators=(",",":")).encode()).hexdigest()
    return result


def main():
    end_day = datetime.now(timezone.utc).date()-timedelta(days=1)
    start_day = end_day-timedelta(days=29)
    db = D1()
    report = compare(db.history(), start=start_day.isoformat(),end=end_day.isoformat())
    db.query("INSERT OR REPLACE INTO metadata(k,v) VALUES (?,?)",
             (REPORT_KEY,json.dumps(report,separators=(",",":"))))
    # Strictly aggregate output: no private fixture names or shot-level payloads.
    print(json.dumps({k: report[k] for k in (
          "status","start","end","eligible_match_candidates","paired_games",
          "withheld","stage1_params","stage3_params","models","head_to_head")},
          sort_keys=True))
    return report


if __name__=="__main__":
    main()
