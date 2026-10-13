"""Phase 3: lagged opponent quality, 5/10/20-match form and venue shrinkage.

No same-date results, no future Elo, no published prediction rewrites.
Comparisons are done on exactly the same league/date-blocked fixtures as
stage 1 and the goal / Elo / shot-quality baselines.
"""
from __future__ import annotations
from collections import defaultdict
from datetime import date,datetime,timezone,timedelta
from itertools import groupby
import json
import math
from .feature_ladder import stage1_probs, _split_by_league, _metrics
from .understat_quality import actual_outcome
from .understat_championship import _dc_baseline,_elo_probs,_update_elo_batch
from .understat_hybrid import hybrid_probs
from .understat_d1 import D1
from .understat_private import verified_row
from .xgq import predict_xgq

OUTCOMES=("home","draw","away")
STAGE1_SELECTED=(.50,.25,.30)
# Validation grid. No test-window feature tuning.
PARAMS=((0.,0.),(.15,0.),(.25,0.),(.15,.15),(.25,.15),(.35,.25))


def clip(value,lo,hi):return max(lo,min(hi,value))


def _team_form(prior,team,day,window,*,venue=None):
    filtered=[r for r in prior if (team in (r["h"],r["a"]) and
         r["date"]<day and (venue is None or
            (r["h"]==team)==(venue=="home"))]
    recent=sorted(filtered,key=lambda r:(r["date"],r["id"]),reverse=True)[:window]
    if len(recent)<5:return None
    weighted=[0.,0.,0.]
    now=date.fromisoformat(day)
    for m in recent:
        at_home=m["h"]==team
        created=m["home_xg"] if at_home else m["away_xg"]
        conceded=m["away_xg"] if at_home else m["home_xg"]
        oppElo=m.get("prior_opponent_elo_home" if at_home else "prior_opponent_elo_away")
        if type(oppElo) not in (int,float):
            return None
        adjustment=clip(10**((oppElo-1500)/1400),.80,1.25)
        w=2**(-(now-date.fromisoformat(m["date"])).days/90)
        weighted[0]+=w*created*adjustment
        weighted[1]+=w*conceded/adjustment
        weighted[2]+=w
    return {"for":weighted[0]/weighted[2],"against":weighted[1]/weighted[2],
            "games":len(recent)}


def stage3_probs(prior,game,dc,params):
    """Weight lagged Elo opponent strength, recent xG form and home/away form."""
    base=stage1_probs(prior,game,dc,STAGE1_SELECTED)
    if base is None:return None
    trend,venue=params
    if not trend and not venue:return base
    forms={}
    for side,team,where in (("home",game["h"],"home"),("away",game["a"],"away")):
        global20=_team_form(prior,team,game["date"],20)
        global10=_team_form(prior,team,game["date"],10)
        global5=_team_form(prior,team,game["date"],5)
        stadium=_team_form(prior,team,game["date"],20,venue=where)
        if not all((global20,global10,global5)):
            return None
        forms[side]=(global20,global10,global5,stadium)
    multipliers={}
    for side,opponent in (("home","away"),("away","home")):
        baseline,recent10,recent5,stadium=forms[side]
        opponent20=forms[opponent][0]
        opp5=forms[opponent][2]
        # Ratio of opponent-adjusted short form vs longer-run attack and defence.
        trend_factor=clip(
          ((.60*recent5["for"]+.40*recent10["for"]+.05)/
             (baseline["for"]+.05))*
          ((opp5["against"]+.05)/(opponent20["against"]+.05)),.6,1.6)
        # Venue-specific effect estimates need >=5 actual games at this venue.
        # Shrink to 20-match overall to avoid overreacting to one/two fixtures.
        stadium_factor=1.
        if stadium is not None:
            attack_ratio=(stadium["for"]+.05)/(baseline["for"]+.05)
            stadium_factor=clip((stadium["games"]*attack_ratio+6)/(stadium["games"]+6),.8,1.2)
        multipliers[side]=clip(trend_factor**trend*stadium_factor**venue,.8,1.25)
    adjusted={"home":base["home"]*multipliers["home"],
              "away":base["away"]*multipliers["away"],
              "draw":base["draw"]}
    total=sum(adjusted.values())
    return {k:adjusted[k]/total for k in OUTCOMES}


def run_stage3(rows,*,min_test=80):
    records=[verified_row(r) for r in rows]
    cohorts=_split_by_league(records)
    val=[]
    test=[]
    for league,cohort in cohorts.items():
        prior=[]
        rating={}
        for day,group in groupby(cohort["history"],lambda r:r["date"]):
            batch=list(group)
            split=("train" if day<cohort["validation_start"] else
                   "validation" if day<cohort["test_start"] else "test")
            if split!="train":
                cutoff=(date.fromisoformat(day)-timedelta(days=900)).isoformat()
                recent=[r for r in prior if r["date"]>=cutoff]
                if len(recent)>=40:
                    for m in batch:
                        game={"league":league,"date":day,"h":m["h"],"a":m["a"]}
                        primary,_=predict_xgq({"league":league,"date":day,
                          "home_team":m["home"],"away_team":m["away"]},prior,day)
                        dc=_dc_baseline(recent,game)
                        elo=_elo_probs(recent,rating,game)
                        hy=hybrid_probs(recent,game,dc,(.35,.30)) if dc else None
                        if not all((primary,dc,elo,hy)):continue
                        stage1=stage1_probs(recent,game,dc,STAGE1_SELECTED)
                        if stage1 is None:continue
                        variants={str(p):stage3_probs(recent,game,dc,p) for p in PARAMS}
                        if not all(variants.values()):continue
                        r={"league":league,"date":day,"actual":actual_outcome(m),
                           "xgq":{k:primary["probabilities"][k] for k in OUTCOMES},
                           "dc":dc,"elo":elo,"hybrid_fixed":hy,"stage1_fixed":stage1,
                           "variants":variants}
                        (val if split=="validation" else test).append(r)
            annotated=[]
            for m in batch:
                annotated.append({**m,
                    "prior_opponent_elo_home":rating.get(m["a"],1500),
                    "prior_opponent_elo_away":rating.get(m["h"],1500)})
            _update_elo_batch(rating,batch)
            prior.extend(annotated)
    report={"stage":3,"status":"insufficient","historical_matches":len(records),
      "validation_matches":len(val),"test_matches":len(test),
      "method":"chronological_40_15_45_league_day_before_match_elo",
      "opponent_rating_timing":"Elo before each historical match day",
      "venue_min_games":5,"form_windows":[5,10,20],
      "retrospective_overlap_warning":"Existing history was already examined by earlier research; do not claim blind out-of-sample validation.",
      "production_unchanged":True,"generated_at":datetime.now(timezone.utc).isoformat()}
    if len(val)<30 or len(test)<min_test:return report
    metrics={str(p):_metrics([{"actual":r["actual"],"p":r["variants"][str(p)]}
                             for r in val],"p") for p in PARAMS}
    selected=min(PARAMS,key=lambda p:(metrics[str(p)]["log_loss"],p))
    for r in test:r["stage3"]=r["variants"][str(selected)]
    names=("xgq","dc","elo","hybrid_fixed","stage1_fixed","stage3")
    report.update(status="retrospective",selected={"params":selected,
      "chosen_on":"validation_only"},
      scores={k:_metrics(test,k) for k in names},
      "per_league":{league:{name:_metrics([r for r in test if r["league"]==league],name)
         for name in names} for league in sorted({r["league"] for r in test})})
    return report


def main():
    db=D1()
    report=run_stage3(db.history())
    db.query("INSERT OR REPLACE INTO metadata(k,v) VALUES(?,?)",
             ("understat_feature_stage3",json.dumps(report,separators=(",",":"))))
    print(json.dumps({k:v for k,v in report.items()
                      if k in ("stage","status","validation_matches","test_matches",
                               "selected","scores")},sort_keys=True))
    return report


if __name__=="__main__":main()
