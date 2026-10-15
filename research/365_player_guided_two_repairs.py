"""Try to resolve exactly two original ambiguous 365Scores shots by player stats.

Fetch <=2 previously known match IDs. Require the *same* chart shot exclusion
to satisfy the independent published player xG, player shot count, team xG,
team shot count and on/off-target breakdown. If more than one different
xG can be removed, do NOT guess or approve.

Strict successes enter the existing private research verified table with a
separate player-guided proof tier, never training. The old failed original
audit remains unchanged. All raw events and player IDs stay off GitHub.
"""
from __future__ import annotations
import importlib,json,time
from pathlib import Path
from collections import Counter
from engine import provider365 as p
from engine.player_guided_repair365 import repair
from engine.understat_d1 import D1,D1Error
from engine.xgq import normalized

old=importlib.import_module("research.365_original_ingestion_comparison")
OUT=Path("research/reports/365_player_guided_two_repairs.json")


def attempt(*,db=None,fetch=None,delay=1.5):
    d=db if db is not None else D1()
    cases=old.unresolved(d)
    sources=d.query("SELECT id,payload FROM private_365_repair_evaluations ORDER BY id LIMIT 50")
    selected=[str(v["id"]) for v in sources if json.loads(v["payload"]).get("status")==
              "multiple_distinct_shots_would_match" and str(v["id"]) in cases]
    if len(selected)!=2:
        raise ValueError("expected_exactly_two_original_ambiguous_cases")
    d.query("""CREATE TABLE IF NOT EXISTS private_365_player_guided_repair_results(
        id TEXT PRIMARY KEY NOT NULL,payload TEXT NOT NULL)""")
    d.query("""CREATE TABLE IF NOT EXISTS private_365_research_verified(
        id TEXT PRIMARY KEY NOT NULL,payload TEXT NOT NULL)""")
    getter=fetch if fetch is not None else lambda mid:p.fetch(
        "game/",{"gameId":mid,"topBookmaker":"14"})
    existing={str(r["id"]) for r in d.query(
        "SELECT id FROM private_365_player_guided_repair_results ORDER BY id LIMIT 50")}
    totals=d.query("SELECT COUNT(*) AS n FROM private_365_research_verified")
    start=int(totals[0]["n"])
    report={"original_ambiguous":2,"request_cap":2,"requests":0,"tested":0,
            "previously_tested":0,"uniquely_fixed":0,"still_ambiguous":0,
            "reasons":{},"verified_research_total_before":start,
            "verified_research_total_after":start,
            "training_release":False,"original_match_audits_changed":False,
            "individual_player_details_published":False,
            "raw_events_written":False,"private_match_rows_published":0,
            "status":"completed"}
    freq=Counter()
    for mid in selected:
        if mid in existing:
            report["previously_tested"]+=1;continue
        row=cases[mid]
        if report["requests"]>=2:break
        try:
            source=d.query("SELECT payload FROM private_365_rejected_diagnosis WHERE id=?",(mid,))
            categories=d.query("SELECT payload FROM private_365_rejected_stat_breakdown WHERE id=?",(mid,))
            witness=d.query("SELECT payload FROM private_365_player_witness WHERE id=?",(mid,))
            if any(len(t)!=1 for t in (source,categories,witness)):
                raise ValueError("independent_witness_missing")
            original=json.loads(source[0]["payload"])["source_stats"]
            breakdown=json.loads(categories[0]["payload"])["by_side"]
            player=json.loads(witness[0]["payload"])
            if player.get("extra_shot_isolatable_to_one_player") is not True:
                raise ValueError("player_count_did_not_isolate_shooter")
            report["requests"]+=1
            detail=getter(mid)
            proof=repair(row,detail,original,breakdown)
            report["tested"]+=1
            if proof["ok"]:
                approved=proof["private_row"]
                approved["id"]=f"{approved['league']}|{approved['date']}|{normalized(approved['home'])}|{normalized(approved['away'])}"
                approved["h"]=normalized(approved["home"])
                approved["a"]=normalized(approved["away"])
                approved["independent_completeness"]="both_sides_team_and_player_stats_unique_exclusion"
                approved["verified_stats_endpoint"]=True
                d.query("INSERT OR REPLACE INTO private_365_research_verified(id,payload) VALUES(?,?)",
                        (approved["id"],json.dumps(approved,ensure_ascii=False,separators=(",",":"))))
                report["uniquely_fixed"]+=1
            else:
                report["still_ambiguous"]+=1
            freq[proof["reason"]]+=1
            d.query("INSERT OR REPLACE INTO private_365_player_guided_repair_results(id,payload) VALUES(?,?)",
                    (mid,json.dumps({"ok":proof["ok"],"status":proof["reason"]},
                                    separators=(",",":"))))
        except p.AccessDenied:
            report["status"]="provider_access_denied_stopped";freq["access_denied"]+=1;break
        except (D1Error,ValueError,TypeError,KeyError) as exc:
            freq[str(exc)[:70]]+=1
        finally:
            if fetch is None:time.sleep(delay)
    report["reasons"]=dict(sorted(freq.items()))
    after=d.query("SELECT COUNT(*) AS n FROM private_365_research_verified")
    report["verified_research_total_after"]=int(after[0]["n"])
    return report

def main():
    try:r=attempt()
    except (D1Error,ValueError,TypeError,KeyError) as e:
        r={"status":"failed_closed","reason_type":type(e).__name__,
           "request_cap":2,"requests":0,"uniquely_fixed":0,
           "training_release":False,"original_match_audits_changed":False,
           "individual_player_details_published":False,"raw_events_written":False,
           "private_match_rows_published":0}
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(r,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print(json.dumps(r,ensure_ascii=False))
    return r

if __name__=="__main__":main()
