"""Paired complete-archive benchmark of all Penniless XGQ 1X2 model variants.

Input: every verified Understat fixture in the private D1 history table.
Forecasts: strictly using games dated BEFORE the evaluated game, recomputed
chronologically. Warm-up/ineligible fixtures excluded and enumerated.
One *identical eligible fixture set* for every compared model. Neither model
training nor hyperparameter choice is a prospective blind test here:
component and V2 calibration coefficients were selected in hindsight for
early historical dates, and 2025-26 data overlap historical validation.

This is research-only; never alter permanently frozen forward forecasts.
"""
from __future__ import annotations

from collections import Counter,defaultdict
from datetime import datetime,timezone
import json
import math

from .comprehensive import _dated_replay,ensemble,APPROVED_PARAMS
from .draw_lab import apply_draw_calibration,feature_vector,FROZEN_DRAW_WEIGHTS
from .understat_d1 import D1

OUTCOMES=("home","draw","away")
MODELS=("xgq","dc","elo","hybrid","stage1","stage3","comprehensive_v1","draw_v2")
REPORT_KEY="penniless_full_understat_archive_models_20261018"

def _evaluate(records,model):
    n=len(records)
    if not n:
        return {"n":0}
    outcomes=Counter()
    picks=Counter()
    accurate=Counter()
    loss=brier=draw_sum=0.
    for row in records:
        probs=row["models"][model]
        actual=row["actual"]
        pick=max(OUTCOMES,key=lambda k:probs[k])
        outcomes[actual]+=1
        picks[pick]+=1
        accurate[actual]+=int(pick==actual)
        loss-=math.log(max(probs[actual],1e-12))
        brier+=sum((probs[k]-int(k==actual))**2 for k in OUTCOMES)
        draw_sum+=probs["draw"]
    d=picks["draw"]
    dc=accurate["draw"]
    return {"n":n,"correct":sum(accurate.values()),
            "accuracy_pct":round(100*sum(accurate.values())/n,3),
            "log_loss":round(loss/n,6),"brier":round(brier/n,6),
            "draw_predictions":d,"correct_draw_predictions":dc,
            "incorrect_draw_predictions":d-dc,
            "draw_precision_pct":round(100*dc/d,3) if d else None,
            "actual_draws":outcomes["draw"],
            "draw_recall_pct":round(100*dc/outcomes["draw"],3) if outcomes["draw"] else None,
            "average_draw_probability_pct":round(100*draw_sum/n,3),
            "picks":{k:picks[k] for k in OUTCOMES},
            "correct_by_actual":{k:accurate[k] for k in OUTCOMES}}

def _season(day):
    year=int(day[:4])
    if int(day[5:7])<7:
        year-=1
    return f"{year}/{str(year+1)[-2:]}"

def benchmark(rows,*,through="2026-10-17"):
    if not rows:
        raise ValueError("Understat historical database empty")
    latest=[r for r in rows if r["date"]<=through]
    start=min(r["date"] for r in latest)
    all_draws=sum(r["hg"]==r["ag"] for r in latest)
    base,withheld,flow,n=_dated_replay(latest,through,eval_start=start)
    evaluated=[]
    for x in base:
        components=x["models"]
        comprehensive=ensemble(components,APPROVED_PARAMS)
        adjusted=apply_draw_calibration(
            comprehensive,feature_vector(x),FROZEN_DRAW_WEIGHTS)
        choices={m:components[m] for m in
                 ("xgq","dc","elo","hybrid","stage1","stage3")}
        choices["comprehensive_v1"]=comprehensive
        choices["draw_v2"]=adjusted
        for key,probs in choices.items():
            if set(probs)!=set(OUTCOMES) or any(not isinstance(v,(int,float)) or not math.isfinite(v) or v<0
                                for v in probs.values()):
                raise ValueError("Invalid 1X2 for "+key)
            total=sum(probs.values())
            # XGQ probabilities may be truncated in its legacy payload.
            # Accept only tiny numerical discrepancy and normalize fairly.
            if not (0.999 <= total <= 1.001):
                raise ValueError("Substantial probability sum error for "+key)
            choices[key]={k:float(probs[k])/total for k in OUTCOMES}
        evaluated.append({"date":x["date"],"league":x["league"],
                          "actual":x["actual"],"models":choices})
    if not evaluated:
        return {"status":"insufficient","history_n":n,"withheld":withheld}
    eligible_d=Counter(r["actual"] for r in evaluated)
    return {"status":"retrospective_paired_full_archive",
            "source":"private verified Understat summary archive",
            "all_archive_matches":n,
            "all_archive_draws":all_draws,
            "archive_start":start,
            "archive_end":through,
            "warmup_and_unavailable":n-len(evaluated),
            "withheld_by_reason":withheld,
            "eligible_matched_matches":len(evaluated),
            "eligible_actual_outcomes":{k:eligible_d[k] for k in OUTCOMES},
            "models":{m:_evaluate(evaluated,m) for m in MODELS},
            "per_league":{league:{"n":sum(r["league"]==league for r in evaluated),
                "models":{m:_evaluate([r for r in evaluated if r["league"]==league],m)
                          for m in MODELS}}
                for league in sorted({r["league"] for r in evaluated})},
            "per_season":{season:{"n":sum(_season(r["date"])==season for r in evaluated),
                "models":{m:_evaluate([r for r in evaluated if _season(r["date"])==season],m)
                          for m in MODELS}}
                for season in sorted({_season(r["date"]) for r in evaluated})},
            "evaluation_rules":{
                "paired_exactly_same_games":True,
                "uses_only_results_from_dates_prior_to_fixture":True,
                "draw_definition":"draw is selected only when P(draw) is the largest of home/draw/away",
                "historical_retrospective_not_live_predictions":True,
                "lookahead_parameter_selection_caveat":"Historical model parameters and V2 coefficients were developed in later date ranges and may have been selected using overlapping evaluation history.",
                "does_not_change_any_published_forecasts":True,
                "all_archive_counts_not_identical_to_evaluable_counts":True},
            "generated_at_utc":datetime.now(timezone.utc).isoformat()}

def main():
    db=D1()
    history=db.history()
    through=max(r["date"] for r in history)
    report=benchmark(history,through=through)
    db.query("INSERT OR REPLACE INTO metadata(k,v) VALUES(?,?)",
             (REPORT_KEY,json.dumps(report,ensure_ascii=False,separators=(",",":"))))
    print(json.dumps({k:report[k] for k in
           ("status","all_archive_matches","all_archive_draws",
            "archive_start","archive_end","eligible_matched_matches",
            "warmup_and_unavailable","withheld_by_reason","models")},sort_keys=True))
    return report

if __name__=="__main__":
    main()
