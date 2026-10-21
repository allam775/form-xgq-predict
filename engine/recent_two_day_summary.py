"""Read-only prospective model scorecard for requested completed match dates.

Prints aggregates only; never exposes private fixture/provider IDs and never
replays, refits, or modifies immutable frozen predictions or their grades.
A supplementary model is scored only if frozen before the kickoff and its
final-result grade exists. One match may be counted for different models,
but never twice for the same model.
"""
import json
from collections import defaultdict
from datetime import datetime
from .understat_d1 import D1

DAYS=("2026-10-19","2026-10-20")
TABLES=("private_daily_forecasts","private_daily_grades",
        "private_daily_supplemental_forecasts","private_daily_supplemental_grades")
MODELS=(
 "xgq_production_formula","goal_fixed_rho","elo",
 "hybrid_393_validation","stage1_volume_xgq",
 "stage3_opponent_form","penniless_comprehensive",
 "penniless_draw_calibrated"
)

def fetch_rows(db,table):
    if table not in TABLES:raise ValueError("Unknown private table")
    result=[]
    start=0
    while True:
        batch=db.query("SELECT payload FROM "+table+" ORDER BY id LIMIT ? OFFSET ?",(200,start))
        result.extend(json.loads(x["payload"]) for x in batch)
        if len(result)>20000:raise ValueError("Unreasonably large ledger")
        if len(batch)<200:return result
        start+=len(batch)

def summarize(forecasts,grades,supplements,supplement_grades):
    base={r["id"]:r for r in forecasts}
    grades_by={r["id"]:r for r in grades}
    supp={r["id"]:r for r in supplements}
    supp_grades_by={r["id"]:r for r in supplement_grades}
    result={}
    for day in DAYS:
        day_forecasts={i:p for i,p in base.items() if p["date"]==day and p.get("status")=="frozen"}
        bymodel={}
        certified={i:g for i,g in grades_by.items()
                   if i in day_forecasts and g.get("date")==day}
        for name in MODELS:
            n=correct=draw_picks=draw_hits=actual_draws=0
            loss=brier=0.
            for match_id,old in day_forecasts.items():
                primary=certified.get(match_id)
                if not primary:continue
                g=primary.get("models",{}).get(name)
                forecast_model=old.get("models",{}).get(name)
                if g is None or forecast_model is None:
                    secondary=supp_grades_by.get(match_id)
                    supplemental=supp.get(match_id)
                    if (not secondary or not supplemental or
                        secondary.get("date")!=day or
                        name not in secondary.get("models",{}) or
                        name not in supplemental.get("models",{})):
                        continue
                    # True pre-match supplement; never use retrospective predictions.
                    if datetime.fromisoformat(supplemental["frozen_at_utc"]) >= datetime.fromisoformat(supplemental["kickoff_utc"]):
                        raise ValueError("Postkickoff supplement detected")
                    g=secondary["models"][name]
                    expected_pick=supplemental["picks"][name]
                else:
                    expected_pick=old["picks"][name]
                if datetime.fromisoformat(old["frozen_at_utc"]) >= datetime.fromisoformat(old["kickoff_utc"]):
                    raise ValueError("Postkickoff original prediction detected")
                if g["pick"] != expected_pick:
                    raise ValueError("Mismatch with genuinely frozen model pick")
                true=primary["outcome"]
                n+=1
                correct+=int(bool(g["correct"]))
                draw_picks+=int(expected_pick=="draw")
                draw_hits+=int(expected_pick=="draw" and true=="draw")
                actual_draws+=int(true=="draw")
                loss+=g["log_loss"]
                brier+=g["brier"]
            bymodel[name]=dict(
                n=n,correct=correct,accuracy_pct=round(100*correct/n,2) if n else None,
                predicted_draws=draw_picks,correct_draws=draw_hits,
                actual_draws=actual_draws,
                log_loss=round(loss/n,5) if n else None,
                brier=round(brier/n,5) if n else None)
        result[day]=dict(
            original_frozen=len(day_forecasts),
            graded_officially=len(certified),
            pending=len(day_forecasts)-len(certified),
            supplementary_frozen=sum(x in supp for x in day_forecasts),
            models=bymodel)
    return result

def main():
    db=D1()
    sources=[fetch_rows(db,t) for t in TABLES]
    summary=summarize(*sources)
    # Public Actions contains aggregates only; no fixture names or provider IDs.
    print(json.dumps({"source":"frozen prospective predictions plus verified Understat grades",
                      "dates":summary,
                      "note":"Original grades only; later retrospective replays excluded."},
                     ensure_ascii=False,sort_keys=True))
    return summary

if __name__=="__main__":
    main()
