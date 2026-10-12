"""Chronological phase-by-phase football feature research, private by design.

Phase 1: goal/shot volume/quality features available in compact Understat D1.
Candidates are tuned ONLY using earlier validation days, then evaluated on
later, disjoint test days shared with XGQ, Elo, fixed-rho and a frozen hybrid.
Never mutate production forecasts. Replays are retrospective, NOT blind tests.
"""
from __future__ import annotations
from collections import defaultdict
from datetime import date, timedelta, datetime, timezone
from itertools import groupby
import json
import math

from .understat_d1 import D1
from .understat_private import verified_row
from .understat_quality import score, actual_outcome, historical_league_baseline
from .understat_championship import (_dc_baseline, _elo_probs, _update_elo_batch,
                                     _poisson_rates, _paired_ci)
from .understat_hybrid import hybrid_probs, shot_rates
from .xgq import predict_xgq

OUTCOMES = ("home", "draw", "away")
# Predeclared, not adjusted after the test period is inspected.
STAGE1_CANDIDATES = (
    (0.35, 0.0, 0.0), (0.50, 0.0, 0.30),
    (0.35, 0.12, 0.0), (0.35, 0.12, 0.30),
    (0.50, 0.12, 0.30), (0.35, 0.25, 0.30),
    (0.50, 0.25, 0.30),
)
BASELINES = ("xgq", "elo", "dc_fixed_rho", "hybrid_fixed", "naive")
SHRINK = 6


def _clip(x, low, high):
    return max(low, min(high, x))


def _weighted_pair(prior, game, side, field, *, lookback=20, half_life=120):
    team=game["h"] if side=="home" else game["a"]
    matches=[r for r in prior if team in (r["h"],r["a"])]
    matches=sorted(matches,key=lambda x:(x["date"],x["id"]),reverse=True)[:lookback]
    if len(matches)<5:
        return None
    day=date.fromisoformat(game["date"])
    weighted=0.0
    weight=0.0
    for m in matches:
        if m["date"]>=game["date"]:
            raise ValueError("Same-day or future football feature leakage")
        w=2**(-(day-date.fromisoformat(m["date"])).days/half_life)
        k=("home_" if team==m["h"] else "away_")+field
        weighted+=w*m[k]
        weight+=w
    return weighted/weight, len(matches)


def _shot_volume(prior, game):
    avg=sum(r["home_shots"]+r["away_shots"] for r in prior)/(2*len(prior))
    if avg<=0:return None
    hm=_weighted_pair(prior,game,"home","shots")
    am=_weighted_pair(prior,game,"away","shots")
    # Shoot-against totals, not shot creation in reverse.
    def conceded(team):
        m=sorted((r for r in prior if team in (r["h"],r["a"])),
                 key=lambda r:(r["date"],r["id"]),reverse=True)[:20]
        if len(m)<5:return None
        day=date.fromisoformat(game["date"])
        weights=[2**(-(day-date.fromisoformat(r["date"])).days/120) for r in m]
        return (sum(w*(r["away_shots"] if r["h"]==team else r["home_shots"])
                    for w,r in zip(weights,m))/sum(weights),len(m))
    hd=conceded(game["h"])
    ad=conceded(game["a"])
    if None in (hm,am,hd,ad):return None
    def ratio(pair):
        average=(pair[0]*pair[1]+SHRINK*avg)/(pair[1]+SHRINK)
        return _clip(average/avg,.65,1.45)
    return ratio(hm)*ratio(ad),ratio(am)*ratio(hd)


def stage1_probs(prior, game, dc, params):
    """Fixed-rho 1X2 blend with independently measured shooting VOLUME.

    xG already includes quantity; volume coefficient is deliberately small
    and optimized on validation data only to guard double-counting.
    """
    blend,volume_power,xgq_power=params
    lambdas=shot_rates(prior,game,xgq_strength=xgq_power)
    if lambdas is None:return None
    vol=_shot_volume(prior,game)
    if vol is None:return None
    rates=tuple(_clip(lam*(max(.2,mult)**volume_power),.2,4)
                for lam,mult in zip(lambdas,vol))
    shot=_poisson_rates(*rates)
    result={k:(1-blend)*dc[k]+blend*shot[k] for k in OUTCOMES}
    s=sum(result.values())
    return {k:result[k]/s for k in OUTCOMES}


def _key(p):
    return "_".join(f"{v:.2f}" for v in p)


def _metrics(items, model):
    return score([(r[model],r["actual"]) for r in items])


def _split_by_league(rows):
    groups=defaultdict(list)
    for r in rows:groups[r["league"]].append(r)
    cohorts={}
    for league,history in sorted(groups.items()):
        history.sort(key=lambda r:(r["date"],r["id"]))
        days=sorted({r["date"] for r in history})
        if len(days)<30 or len(history)<90:continue
        cohorts[league]={"history":history,
            "validation_start":days[int(.40*len(days))],
            "test_start":days[int(.55*len(days))]}
    return cohorts


def run_stage1(rows, *, min_test=80):
    clean=[verified_row(x) for x in rows]
    if len({x["id"] for x in clean})!=len(clean):
        raise ValueError("Duplicate historical Understat match IDs")
    if any(x["date"]>date.today().isoformat() for x in clean):
        raise ValueError("Future results not usable")
    cohorts=_split_by_league(clean)
    cohorts_summary={}
    buckets={"validation":[],"test":[]}
    for league,cohort in cohorts.items():
        hist=cohort["history"]
        valday,testday=cohort["validation_start"],cohort["test_start"]
        cohorts_summary[league]={"historical_matches":len(hist),
            "validation_start":valday,"test_start":testday}
        prior=[]
        rating={}
        for day,byday in groupby(hist,key=lambda x:x["date"]):
            matches=list(byday)
            split="train" if day<valday else "validation" if day<testday else "test"
            if split!="train":
                cutoff=(date.fromisoformat(day)-timedelta(days=900)).isoformat()
                recent=[x for x in prior if x["date"]>=cutoff]
                if len(recent)>=40:
                    naive=historical_league_baseline(recent)
                    for match in matches:
                        fixture={"league":league,"date":day,
                                 "h":match["h"],"a":match["a"],
                                 "home":match["home"],"away":match["away"]}
                        xgq,_=predict_xgq({"league":league,"date":day,
                            "home_team":match["home"],"away_team":match["away"]},
                            prior,day)
                        if xgq is None:continue
                        dc=_dc_baseline(recent,fixture)
                        elo=_elo_probs(recent,rating,fixture)
                        hybrid=hybrid_probs(recent,fixture,dc,(.35,.30)) if dc else None
                        if not all((dc,elo,hybrid)):continue
                        candidates={}
                        for params in STAGE1_CANDIDATES:
                            candidates[_key(params)]=stage1_probs(recent,fixture,dc,params)
                        if not all(candidates.values()):continue
                        buckets[split].append({
                            "league":league,"date":day,"actual":actual_outcome(match),
                            "xgq":{k:xgq["probabilities"][k] for k in OUTCOMES},
                            "elo":elo,"dc_fixed_rho":dc,"naive":naive,
                            "hybrid_fixed":hybrid,"variants":candidates})
            _update_elo_batch(rating,matches)
            prior.extend(matches)
    validation,test=buckets["validation"],buckets["test"]
    report={"stage":"1: shots + xG/xGA + XGQ","status":"insufficient",
        "historical_matches":len(clean),
        "validation_matches":len(validation),"test_matches":len(test),
        "split":"chronological_40_15_45_by_league_day",
        "historical_overlap_warning":"This is retrospective research on a repeatedly studied snapshot, not pristine blind or live evidence.",
        "cohorts":cohorts_summary,"production_model_unchanged":True,
        "generated_at":datetime.now(timezone.utc).isoformat()}
    if not validation or len(test)<min_test:
        report["reason"]="insufficient_nonleaking_paired_coverage"
        return report
    val_scores={_key(p):_metrics([{"actual":r["actual"],
           "p":r["variants"][_key(p)]} for r in validation],"p")
           for p in STAGE1_CANDIDATES}
    chosen=min(STAGE1_CANDIDATES,
               key=lambda p:(val_scores[_key(p)]["log_loss"],p))
    selected=_key(chosen)
    val_chosen=val_scores[selected]
    for rec in test:
        rec["stage1"]=rec["variants"][selected]
    names=BASELINES+("stage1",)
    scores={name:_metrics(test,name) for name in names}
    gain=_paired_ci([{"league":r["league"],"date":r["date"],
            "outcome":r["actual"],"xgq":r["dc_fixed_rho"],"stage1":r["stage1"]}
            for r in test], "stage1",baseline="xgq")
    report.update(status="retrospective",selected={"params":chosen,
        "selected_by":"prior_validation_log_loss_only"},
        validation_selected=val_chosen,test_scores=scores,
        "stage1_vs_dc_logloss_ci95":gain,
        "test_by_league":{league:{name:_metrics([r for r in test if r["league"]==league],name)
                         for name in names}
                    for league in sorted({r["league"] for r in test})},
        "test_candidate_count":len(STAGE1_CANDIDATES),
        "private_match_level_records_written":0)
    return report


def main():
    report=run_stage1(D1().history())
    db=D1()
    db.query("INSERT OR REPLACE INTO metadata(k,v) VALUES(?,?)",
             ("understat_feature_stage1",json.dumps(report,separators=(",",":"))))
    print(json.dumps({"stage":1,"status":report["status"],
       "validation":report["validation_matches"],"test":report["test_matches"],
       "selected":report.get("selected"),"test_scores":report.get("test_scores"),
       "vs_dc":report.get("stage1_vs_dc_logloss_ci95")},sort_keys=True))
    return report


if __name__=="__main__":main()
