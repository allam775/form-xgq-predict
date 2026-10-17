"""Penniless Comprehensive: validation-selected Stage 1 / Stage 3 / Elo / DC ensemble.

Research evaluation uses actual authenticated previous-day evidence only.
Never tune on the held-out 2026/27 season, write match-level private shot
data to public CI, or rewrite a previously frozen forecast.
"""
from __future__ import annotations
from collections import Counter, defaultdict
from datetime import date, datetime, timezone, timedelta
from itertools import groupby
import json
import math
from .understat_d1 import D1
from .understat_private import verified_row
from .understat_quality import actual_outcome, score
from .understat_championship import _dc_baseline, _elo_probs, _update_elo_batch
from .feature_ladder import stage1_probs
from .stage3_form import stage3_probs, STAGE1_SELECTED
from .understat_hybrid import hybrid_probs
from .xgq import predict_xgq

OUTCOMES = ("home", "draw", "away")
STAGE3_PRESET = (.25, .15)  # historical validation-selected, frozen before this study
VAL_START, VAL_END = "2026-02-01", "2026-03-31"
HIST_START, HIST_END = "2026-04-01", "2026-05-31"
SEASON_START = "2026-08-01"
REPORT_KEY = "penniless_comprehensive_2026"
# A deliberately small grid; only February/March validation is used to select.
# Every rule retains the audited Stage 1 and Stage 3 signals, Elo, and
# the DC low-score correction. No retroactive fine-tuning on August results.
EL0_WEIGHTS = (.15, .30, .45, .60)
STAGE3_WEIGHTS = (.15, .30, .45)
DC_WEIGHTS = (.00, .10)
DRAW_FACTORS = (.90, 1.00, 1.10, 1.20, 1.35, 1.50)
PARAMETERS = tuple((e,s,d,b)
    for e in EL0_WEIGHTS for s in STAGE3_WEIGHTS for d in DC_WEIGHTS
    if 1-e-s-d >= .0999 for b in DRAW_FACTORS)


def ensemble(base, params):
    """Convex blend, followed by a bounded draw-calibration multiplier."""
    e, s, d, boost = params
    if not all(name in base for name in ("stage1", "stage3", "elo", "dc")):
        return None
    shot_weight = 1-e-s-d
    if shot_weight < .0999 or not .5 <= boost <= 2:
        raise ValueError("Invalid comprehensive model parameter set")
    raw = {k: (shot_weight * base["stage1"][k] +
               s * base["stage3"][k] +
               e * base["elo"][k] +
               d * base["dc"][k]) for k in OUTCOMES}
    # Only modify draw mass using independent, pre-match strength balance.
    # Similar-rated teams can have draw uplift; this coefficient is
    # selected on validation and never adjusted after observing the test.
    similarity = max(0., 1.-abs(base["elo"]["home"]-base["elo"]["away"]))
    raw["draw"] *= 1.+(boost-1.)*similarity
    denom = sum(raw.values())
    if denom <= 0 or any(not math.isfinite(v) or v < 0 for v in raw.values()):
        raise ValueError("Invalid comprehensive probabilities")
    return {k: raw[k]/denom for k in OUTCOMES}


def _scored(rows, name):
    return score([(row[name], row["actual"]) for row in rows])


def _short(records, name):
    metrics=_scored(records,name)
    metrics["correct"]=sum(max(OUTCOMES,key=lambda k:r[name][k])==r["actual"] for r in records)
    metrics["draw_picks"]=sum(max(OUTCOMES,key=lambda k:r[name][k])=="draw" for r in records)
    metrics["actual_draws"]=sum(r["actual"]=="draw" for r in records)
    metrics["draw_probability_mean"]=round(
        sum(r[name]["draw"] for r in records)/len(records),6) if records else None
    return metrics


def _dated_replay(rows, until):
    """One evaluation per fixture, only games strictly earlier than match day as inputs."""
    records=[verified_row(r) for r in rows if r["date"]<=until]
    if len({r["id"] for r in records})!=len(records):
        raise ValueError("Duplicate verified rows")
    leagues=defaultdict(list)
    for row in records:
        leagues[row["league"]].append(row)
    results=[]
    withheld=Counter()
    by_period=Counter()
    for league, history in sorted(leagues.items()):
        history.sort(key=lambda r:(r["date"],r["id"]))
        prior=[]
        ratings={}
        for day, items in groupby(history,lambda r:r["date"]):
            batch=list(items)
            eligible=day>=VAL_START
            if eligible:
                by_period["fixtures_from_validation_on"]+=len(batch)
                recent=[r for r in prior if r["date"] >=
                        (date.fromisoformat(day)-timedelta(days=900)).isoformat()]
                if len(recent)<40:
                    withheld["league_history_under_40"]+=len(batch)
                else:
                    for match in batch:
                        game={"league":league,"date":day,"h":match["h"],"a":match["a"]}
                        dc=_dc_baseline(recent,game)
                        elo=_elo_probs(recent,ratings,game)
                        if dc is None or elo is None:
                            withheld["goal_elo_unavailable"]+=1
                            continue
                        s1=stage1_probs(recent,game,dc,STAGE1_SELECTED)
                        s3=stage3_probs(recent,game,dc,STAGE3_PRESET)
                        hy=hybrid_probs(recent,game,dc,(.35,.30))
                        primary,_=predict_xgq({
                            "league":league,"date":day,
                            "home_team":match["home"],"away_team":match["away"]
                        },prior,day)
                        if not all((s1,s3,hy,primary)):
                            withheld["verified_pre_game_shot_form_missing"]+=1
                            continue
                        models={"stage1":s1,"stage3":s3,
                                "elo":elo,"dc":dc,"hybrid":hy,
                                "xgq":{k:primary["probabilities"][k] for k in OUTCOMES}}
                        if any(set(m)!=set(OUTCOMES) or
                                abs(sum(m.values())-1)>.0001
                               for m in models.values()):
                            raise ValueError("Incomplete 1X2")
                        results.append({"league":league,"date":day,"actual":actual_outcome(match),
                                        "models":models})
            # Only *after* all fixtures on that date have been forecast:
            batch_annotated=[{**r,
                "prior_opponent_elo_home":ratings.get(r["a"],1500),
                "prior_opponent_elo_away":ratings.get(r["h"],1500)}
                for r in batch]
            _update_elo_batch(ratings,batch)
            prior.extend(batch_annotated)
    return results,dict(withheld),dict(by_period),len(records)


def compare(history, *, as_of="2026-10-16", params=None):
    """Freeze candidate selection at 2026-03-31, report historic and season test."""
    records,withheld,flow,history_n=_dated_replay(history,as_of)
    val=[r for r in records if VAL_START<=r["date"]<=VAL_END]
    test=[r for r in records if HIST_START<=r["date"]<=HIST_END]
    season=[r for r in records if SEASON_START<=r["date"]<=as_of]
    if len(val)<50:
        return {"status":"insufficient_validation","validation_n":len(val),
                "historical_n":len(test),"season_n":len(season)}
    if params is None:
        # Selection only on dates before 2026-04-01 and 2026/27 commencement.
        best=None
        for trial in PARAMETERS:
            ll=-sum(math.log(max(1e-12,ensemble(r["models"],trial)[r["actual"]])) for r in val)/len(val)
            if best is None or (ll,trial)<(best[0],best[1]):
                best=(ll,trial)
        params=best[1]
    elif params not in PARAMETERS:
        raise ValueError("Unregistered candidate parameters")
    def prepare(bucket):
        out=[]
        for r in bucket:
            out.append({"league":r["league"],"date":r["date"],"actual":r["actual"],
                        **r["models"],"comprehensive":ensemble(r["models"],params)})
        return out
    def summarize(bucket):
        m=prepare(bucket)
        names=("xgq","stage1","stage3","elo","dc","hybrid","comprehensive")
        result={"games":len(m),"metrics":{name:_short(m,name) for name in names},
                "by_league":{league:{name:_short([x for x in m if x["league"]==league],name)
                                      for name in names}
                             for league in sorted(set(r["league"] for r in m))},
                "by_month":{month:{name:_short([x for x in m if x["date"][:7]==month],name)
                                     for name in names}
                            for month in sorted(set(r["date"][:7] for r in m))}}
        result["paired_comprehensive_vs_stage1"]={
            "comprehensive_only_correct":sum(
               max(OUTCOMES,key=lambda k:r["comprehensive"][k])==r["actual"] and
               max(OUTCOMES,key=lambda k:r["stage1"][k])!=r["actual"] for r in m),
            "stage1_only_correct":sum(
               max(OUTCOMES,key=lambda k:r["comprehensive"][k])!=r["actual"] and
               max(OUTCOMES,key=lambda k:r["stage1"][k])==r["actual"] for r in m)}
        return result
    return {"status":"retrospective_chronological",
            "history_records":history_n,
            "as_of":as_of,
            "validation_window":[VAL_START,VAL_END],
            "historical_holdout_window":[HIST_START,HIST_END],
            "season_window":[SEASON_START,as_of],
            "validation_games":len(val),
            "validation_selected_params":params,
            "candidate_count":len(PARAMETERS),
            "validation":summarize(val),
            "historical_holdout":summarize(test),
            "season_2026_27":summarize(season),
            "withheld":withheld,"eligible_flow":flow,
            "notes":[
                "All per-game features are drawn strictly from earlier match dates.",
                "Blend and draw-calibration parameters selected only on Feb-Mar 2026.",
                "Stage 1/3 component defaults were themselves selected in older overlapping research.",
                "Historical window was previously studied in this project: not pristine blind validation.",
                "2026/27 benchmark is a retrospective replay, not previously frozen predictions.",
                "The draw multiplier is selected on validation and may not create draw top choices.",
                "Missing non-penalty creativity/big-chance features are not invented or treated as available.",
                "Never overwrite already frozen predictions; production is unchanged."
            ],
            "created_at_utc":datetime.now(timezone.utc).isoformat()}


def main():
    # Date cutoff excludes today's partial results.
    cutoff=(datetime.now(timezone.utc).date()-timedelta(days=1)).isoformat()
    db=D1()
    report=compare(db.history(),as_of=cutoff)
    db.query("INSERT OR REPLACE INTO metadata(k,v) VALUES (?,?)",
             (REPORT_KEY,json.dumps(report,separators=(",",":"))))
    output={k:report[k] for k in ("status","as_of","validation_games",
            "validation_selected_params","candidate_count","withheld")}
    for name in ("historical_holdout","season_2026_27"):
        output[name]={"games":report[name]["games"],"metrics":report[name]["metrics"]}
    print(json.dumps(output,sort_keys=True))
    return report

if __name__=="__main__":
    main()
