"""Phase 2: real Understat match-level xA + key-pass creation benchmark.

NEVER use season-complete player stats to forecast earlier league matches.
Reads verified per-match creativity only; withholds instead of inventing values.
No Opta Big Chance counts are claimed: high-xG-shot threshold is a proxy.
"""
from __future__ import annotations
from collections import defaultdict
from datetime import date,datetime,timezone,timedelta
from itertools import groupby
import json
import math
from .feature_ladder import (_split_by_league,stage1_probs,OUTCOMES,_metrics)
from .understat_creativity import validate_creativity,TABLE
from .understat_championship import _dc_baseline,_elo_probs,_update_elo_batch,_poisson_rates
from .understat_hybrid import hybrid_probs
from .understat_quality import actual_outcome, historical_league_baseline
from .understat_d1 import D1
from .understat_private import verified_row
from .xgq import predict_xgq

STAGE1_FIXED=(.50,.25,.30)
CANDIDATES=((.10,.10,.05),(.20,.10,.10),(.25,.20,.10),(.35,.20,.15))
FIELDS=("xa","key_passes","high_xg_attempts")
OUTCOMES=("home","draw","away")


def _clip(x,a,b):return max(a,min(b,x))


def _profile(rows, team, day, field):
    games=sorted([r for r in rows if team in (r["h"],r["a"]) and
                  r["date"]<day and "creative" in r],
                 key=lambda r:(r["date"],r["id"]),reverse=True)[:20]
    if len(games)<5:return None
    def pick(r,side):
        home=r["h"]==team
        own=("home_" if home else "away_")+field
        conceded=("away_" if home else "home_")+field
        return r["creative"][own if side=="for" else conceded]
    return {side:sum(pick(r,side) for r in games)/len(games) for side in ("for","against")}


def creativity_probs(prior, game, dc, coeffs):
    """Positive past match-level chance creation/concession, never target stats."""
    pairs=[r for r in prior if "creative" in r]
    if len(pairs)<40:return None
    h=_profile(prior,game["h"],game["date"],"xa")
    a=_profile(prior,game["a"],game["date"],"xa")
    if h is None or a is None:return None
    rates=[]
    for side,team,opponent in (("home",game["h"],game["a"]),
                                ("away",game["a"],game["h"])):
        power=1.0
        for name,coeff in zip(FIELDS,coeffs):
            league_mean=sum(r["creative"]["home_"+name]+r["creative"]["away_"+name]
                            for r in pairs)/(2*len(pairs))
            if league_mean<.01:return None
            own=_profile(prior,team,game["date"],name)
            other=_profile(prior,opponent,game["date"],name)
            if own is None or other is None:return None
            # Team xA and opponent xA conceded; both are match-roster data.
            smooth_for=(20*own["for"]+6*league_mean)/(26*league_mean)
            smooth_concede=(20*other["against"]+6*league_mean)/(26*league_mean)
            power*= _clip(smooth_for*smooth_concede,.55,1.7)**coeff
        rates.append(_clip(power,.75,1.30))
    base=stage1_probs(prior,game,dc,STAGE1_FIXED)
    if base is None:return None
    # Bounded probability adjustment preserving total; prior1 stage produces
    # calibrated ratios; no pretending to know scoreline rates from 1X2.
    adjusted={"home":base["home"]*rates[0],
              "away":base["away"]*rates[1],
              "draw":base["draw"]}
    s=sum(adjusted.values())
    return {k:adjusted[k]/s for k in OUTCOMES}


def run_stage2(rows,creativity, *, min_test=80):
    verified=[verified_row(r) for r in rows]
    creativity_rows=[validate_creativity(r) for r in creativity]
    index={r["id"]:r for r in creativity_rows}
    if len(index)!=len(creativity_rows):
        raise ValueError("Duplicate creativity data")
    enriched=[]
    for r in verified:
        meta=index.get(r["id"])
        if meta is not None:
            if (r["source_match_id"]!=meta["source_match_id"] or
                r["league"]!=meta["league"] or r["date"]!=meta["date"]):
                raise ValueError("Creativity fixture mismatch")
            r={**r,"creative":meta}
        enriched.append(r)
    cohorts=_split_by_league(enriched)
    buckets={"validation":[],"test":[]}
    for league,cohort in cohorts.items():
        history=cohort["history"]
        valday,testday=cohort["validation_start"],cohort["test_start"]
        prior=[]
        rating={}
        for day,group in groupby(history,key=lambda m:m["date"]):
            batch=list(group)
            split="train" if day<valday else "validation" if day<testday else "test"
            if split!="train":
                cutoff=(date.fromisoformat(day)-timedelta(days=900)).isoformat()
                recent=[r for r in prior if r["date"]>=cutoff]
                if len(recent)>=40:
                    for m in batch:
                        available=sum("creative" in r for r in recent)
                        if available<60 or available<.50*len(recent):
                            # Withhold if real pre-match creativity coverage is sparse.
                            # No season totals or fabricated metrics can fill gaps.
                            continue
                        fixture={"date":day,"league":league,"h":m["h"],"a":m["a"]}
                        base,_=predict_xgq({"league":league,"date":day,
                                             "home_team":m["home"],"away_team":m["away"]},prior,day)
                        dc=_dc_baseline(recent,fixture)
                        elo=_elo_probs(recent,rating,fixture)
                        hybrid=hybrid_probs(recent,fixture,dc,(.35,.30)) if dc else None
                        if not all((base,dc,elo,hybrid)):continue
                        stage1=stage1_probs(recent,fixture,dc,STAGE1_FIXED)
                        if stage1 is None:continue
                        candidates={str(params):creativity_probs(recent,fixture,dc,params)
                                    for params in CANDIDATES}
                        if any(p is None for p in candidates.values()):continue
                        buckets[split].append({"date":day,"league":league,
                           "actual":actual_outcome(m),
                           "xgq":{k:base["probabilities"][k] for k in OUTCOMES},
                           "dc":dc,"elo":elo,"hybrid_fixed":hybrid,
                           "stage1_fixed":stage1,"variants":candidates})
            _update_elo_batch(rating,batch)
            prior.extend(batch)
    val,test=buckets["validation"],buckets["test"]
    report={"stage":2,"status":"insufficient_coverage","historical_matches":len(verified),
      "creativity_enriched_matches":len(index),
      "validation_paired":len(val),"test_paired":len(test),
      "method":"same_match_chronological_40_15_45",
      "actual_match_roster_xa_key_passes":True,
      "big_chances_are_proxy_not_opta":True,
      "note":"No historical skill claim until authenticated creativity features reach enough PRIOR fixtures; no season-end data leakage.",
      "production_unchanged":True,"generated_at":datetime.now(timezone.utc).isoformat()}
    if len(val)<30 or len(test)<min_test:return report
    scores_val={str(p):_metrics([{"actual":r["actual"],"m":r["variants"][str(p)]}
                               for r in val],"m") for p in CANDIDATES}
    best=min(CANDIDATES,key=lambda p:(scores_val[str(p)]["log_loss"],p))
    for r in test:r["stage2"]=r["variants"][str(best)]
    names=("xgq","dc","elo","hybrid_fixed","stage1_fixed","stage2")
    report.update(status="retrospective",selected={"params":best,
        "selected_by":"earlier_validation_only"},
        scores={name:_metrics(test,name) for name in names})
    return report


def main():
    db=D1()
    db.query(f"CREATE TABLE IF NOT EXISTS {TABLE}(id TEXT PRIMARY KEY,payload TEXT NOT NULL)")
    rows=[]
    for offset in range(0,20000,250):
        page=db.query(f"SELECT payload FROM {TABLE} ORDER BY id LIMIT ? OFFSET ?",(250,offset))
        rows.extend(json.loads(r["payload"]) for r in page)
        if len(page)<250:break
    report=run_stage2(db.history(),rows)
    db.query("INSERT OR REPLACE INTO metadata(k,v) VALUES(?,?)",
             ("understat_feature_stage2",json.dumps(report,separators=(",",":"))))
    print(json.dumps({k:v for k,v in report.items() if k in
                     ("stage","status","historical_matches","creativity_enriched_matches",
                      "validation_paired","test_paired","scores","selected")},sort_keys=True))
    return report


if __name__=="__main__":main()
