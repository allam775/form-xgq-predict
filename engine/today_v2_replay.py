"""Read-only replay of today's pre-existing fixtures using current approved V2.

Intentionally retrospective: new V2 did NOT exist when Oct 17 games kicked off.
No historical result, current-day shot statistic or prior frozen forecast is
used in feature construction. Never overwrite frozen rows.
Results may become available to the Understat database after the match.
"""
from __future__ import annotations
from collections import Counter, defaultdict
from datetime import datetime,timezone
import json,sys,os
from .understat_d1 import D1
from .daily_forecast import _forecast
from .prematch_ledger import _ratings_by_league
from .understat_quality import actual_outcome
from .xgq import normalized

MODELS=("penniless_draw_calibrated","penniless_comprehensive",
        "stage1_volume_xgq","stage3_opponent_form","elo",
        "goal_fixed_rho","xgq_production_formula")
TARGET="2026-10-17"
KEY="penniless_20261017_v2_replay"

def replay(saved, history, *, target=TARGET):
    cutoff=target
    prior=[r for r in history if r["date"] < cutoff]
    ratings=_ratings_by_league(prior)
    byleague=defaultdict(list)
    for r in prior: byleague[r["league"]].append(r)
    by_source={(r["league"],str(r["source_match_id"])):r
               for r in history if r["date"] == target}
    scored=[]
    withheld=Counter()
    aggregate={m:{"n":0,"correct":0,"draw_picks":0,"log_loss_total":0.,
                   "brier_total":0.} for m in MODELS}
    for old in sorted(saved,key=lambda r:(r["kickoff_utc"],r["id"])):
        if old["date"] != target:
            raise ValueError("Replay only the exact requested match day")
        league=old["league"]
        fixture={"id":old["id"],"date":old["date"],"league":league,
                 "home":old["home"],"away":old["away"],
                 "h":old.get("home_id",normalized(old["home"])),
                 "a":old.get("away_id",normalized(old["away"])),
                 "kickoff_utc":old["kickoff_utc"],
                 "source_match_id":old["source_match_id"]}
        # Artificial clock is only for the strict date cutoff; this is
        # explicitly NOT presented as the original pre-match frozen V2 record.
        now=datetime.fromisoformat(target+"T00:00:00+00:00")
        new,reason=_forecast(fixture,byleague[league],ratings.get(league,{}),now=now)
        if not new:
            withheld[reason or "model_unavailable"]+=1
            scored.append({"fixture":fixture["home"]+" - "+fixture["away"],
                           "fixture_id":fixture["id"],"league":league,
                           "kickoff":fixture["kickoff_utc"],
                           "status":"withheld","reason":reason})
            continue
        item={"fixture":fixture["home"]+" - "+fixture["away"],"fixture_id":fixture["id"],
              "league":league,"kickoff":fixture["kickoff_utc"],
              "status":"retrospective_replay_not_frozen",
              "original_frozen_model":old["model"],
              "model_version":new["model_version"],
              "selected":new["picks"],"models":new["models"],
              "original_frozen_pick":old["picks"][old["model"]]}
        actual=by_source.get((league,str(old["source_match_id"])))
        if actual and actual["h"] == fixture["h"] and actual["a"] == fixture["a"]:
            outcome=actual_outcome(actual)
            item.update({"result_status":"provider_verified_final",
                         "score":f'{actual["hg"]}-{actual["ag"]}',"outcome":outcome})
            for m in MODELS:
                if m not in new["models"]:continue
                a=aggregate[m]
                p=new["models"][m]
                a["n"]+=1
                a["correct"]+=new["picks"][m]==outcome
                a["draw_picks"]+=new["picks"][m]=="draw"
                import math
                a["log_loss_total"]-=math.log(max(1e-12,p[outcome]))
                a["brier_total"]+=sum((p[k]-int(k==outcome))**2
                                       for k in ("home","draw","away"))
        else:
            item.update({"result_status":"awaiting_verified_final"})
        scored.append(item)
    for m,a in aggregate.items():
        if a["n"]:
            a["accuracy"]=round(a["correct"]/a["n"],6)
            a["log_loss"]=round(a.pop("log_loss_total")/a["n"],6)
            a["brier"]=round(a.pop("brier_total")/a["n"],6)
        else:
            a.pop("log_loss_total",None)
            a.pop("brier_total",None)
    return {"date":target,"status":"retrospective_read_only","registered":len(saved),
            "generated":len(scored)-sum(withheld.values()),
            "withheld":dict(withheld),"verified_finals":sum(x.get("result_status")=="provider_verified_final" for x in scored),
            "model_scores_on_verified_finals":aggregate,
            "games":scored,
            "claims":[f"Recomputed after the day began using history before {target} only.",
                      "NOT actual frozen V2 forecasts, and not a prospective performance test.",
                      "Finals are only auto-scored when matched to authentic Understat completed history.",
                      "No frozen source forecast was updated."]}

def main():
    db=D1()
    target=os.environ.get("PENNILESS_RETRO_TARGET",TARGET)
    if target not in ("2026-10-17","2026-10-18"):
        raise ValueError("Only the explicitly authorized frozen historical days are supported")
    rows=[json.loads(x["payload"]) for x in db.query(
         "SELECT payload FROM private_daily_forecasts WHERE json_extract(payload,'$.date')=? ORDER BY id",
         (target,))]
    result=replay(rows,db.history(),target=target)
    db.query("INSERT OR REPLACE INTO metadata(k,v) VALUES (?,?)",
        (f"penniless_{target.replace('-','')}_v2_replay",json.dumps(result,ensure_ascii=False,separators=(",",":"))))
    print(json.dumps({k:result[k] for k in
       ("status","date","registered","generated","verified_finals",
        "withheld","model_scores_on_verified_finals")},sort_keys=True))
    return result

if __name__=="__main__":
    main()
