"""Five-case privately vetted excess-event repair attempt for 365Scores.

Use already independently verified 365Scores game/stats/ evidence stored in
PRIVATE D1 and fetch the actual original game/ once for each precisely
overcounted fixture. No replacement/made-up shots. The class of the extra
event must be independently known and there must be exactly one possible
xG correction with a unique xG value across all valid removals.

Store verified proposals in separate PRIVATE D1 table, NOT production and NOT
the published research-verified table. Existing audit/rejection preserved.
All public outputs are counts/status only, not per-match data.
"""
from __future__ import annotations
from collections import Counter
from pathlib import Path
import importlib
import json
import time
from urllib.error import HTTPError,URLError

from engine import provider365 as p
from engine.understat_d1 import D1,D1Error
from engine.repair365 import repair

base=importlib.import_module("research.365_stats_completeness_batch")
OUT=Path("research/reports/365_excess_event_repair_summary.json")

def run(db=None,detail_fetch=None):
    d=db if db is not None else D1()
    cand=base.candidates(d);old=base.prior_audits(d)
    matches=sorted(mid for mid in cand if mid in old and
                   old[mid].get("status")=="shot_count_mismatch")
    if len(matches)!=5:
        raise ValueError("Expected exactly original five count-mismatch cases")
    d.query("""CREATE TABLE IF NOT EXISTS private_365_repair_evaluations(
        id TEXT PRIMARY KEY NOT NULL,payload TEXT NOT NULL)""")
    d.query("""CREATE TABLE IF NOT EXISTS private_365_repair_proposals(
        id TEXT PRIMARY KEY NOT NULL,payload TEXT NOT NULL)""")
    summary={"kind":"five_original_365scores_count_mismatch_repair",
       "original_cases":5,"details_requested":0,
       "evaluated":0,"proposals_generated":0,
       "not_reconcilable":0,"rejection_reasons":{},
       "verified_original_audit_rows_changed":0,
       "published_private_match_details":0,
       "raw_events_written":0,"model_changed":False}
    counts=Counter()
    getter=detail_fetch if detail_fetch is not None else (
        lambda mid:p.fetch("game/",{"gameId":mid,"topBookmaker":"14"}))
    for mid in matches:
        try:
            saved=d.query("SELECT payload FROM private_365_rejected_diagnosis WHERE id=?",(mid,))
            categories=d.query("SELECT payload FROM private_365_rejected_stat_breakdown WHERE id=?",(mid,))
            if len(saved)!=1 or len(categories)!=1:
                raise ValueError("missing_independent_evidence")
            independent=json.loads(saved[0]["payload"])["source_stats"]
            breakdown=json.loads(categories[0]["payload"])["by_side"]
            summary["details_requested"]+=1
            detail=getter(mid)
            outcome=repair(cand[mid],detail,independent,breakdown)
            summary["evaluated"]+=1
            result={"status":outcome["reason"],"ok":outcome["ok"]}
            d.query("INSERT OR REPLACE INTO private_365_repair_evaluations(id,payload) VALUES(?,?)",
                    (mid,json.dumps(result,separators=(",",":"))))
            if outcome["ok"]:
                # Quarantined from model; research review is still required.
                proposal=outcome["private_row"]
                d.query("INSERT OR REPLACE INTO private_365_repair_proposals(id,payload) VALUES(?,?)",
                        (mid,json.dumps(proposal,ensure_ascii=False,separators=(",",":"))))
                summary["proposals_generated"]+=1
            else:
                summary["not_reconcilable"]+=1
            counts[outcome["reason"]]+=1
        except p.AccessDenied:
            counts["provider_denied_stopped"]+=1
            break
        except (ValueError,TypeError,KeyError,HTTPError,URLError,TimeoutError,D1Error) as exc:
            counts[type(exc).__name__ if not isinstance(exc,ValueError)
                   else str(exc)[:80]]+=1
        finally:
            if detail_fetch is None:time.sleep(1.5)
    summary["rejection_reasons"]=dict(sorted(counts.items()))
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps(summary,ensure_ascii=False))
    return summary

if __name__=="__main__":run()
