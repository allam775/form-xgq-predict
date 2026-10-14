"""Bounded autonomous 365Scores shot-event COMPLETENESS audit.

Read existing 365Scores candidates from private Cloudflare D1. For each *new*
candidate, request its independently documented game/stats/ full-match figures:
'Total Shots', 'Expected Goals', and 'Shots Blocked' for both sides. Cross-check
count EXACTLY and shot-xG totals within display precision; reject all
incomplete samples. Save any complete compact XGQ statistics ONLY to a
separate private D1 research table. Never publish raw events, per-match
records, xG or shot arrays or training samples in the public GitHub repository.

The sources are two 365Scores endpoints accessed under user-asserted prior
noncommercial XGQ research permission. Per-run request count <= 18; no
enumeration, retries, cookies, proxy, browser impersonation or bypasses.
On 401/403/429, STOP immediately. Aggregate report only is published.
"""
from __future__ import annotations
from collections import Counter,defaultdict
from datetime import datetime,timezone
import importlib
import json
import re
import time
from pathlib import Path
from urllib.error import HTTPError,URLError

from engine.understat_d1 import D1,D1Error
from engine.provider365 import AccessDenied
from engine.stats365 import stats_witness,reconcile,verified_research_row

# Reuse the already single-tested official game/stats/ accessor.
FETCH=importlib.import_module("research.365_stats_schema_probe").fetch_stats
OUT=Path("research/reports/365_stats_completeness_batch.json")
MAX_REQUESTS=18
DELAY=1.5


def prior_audits(db):
    """Audit rows hold no raw shots, only status for dedup across runs."""
    db.query("""CREATE TABLE IF NOT EXISTS private_365_stats_audit(
        id TEXT PRIMARY KEY NOT NULL, payload TEXT NOT NULL)""")
    rows=db.query("SELECT id,payload FROM private_365_stats_audit LIMIT 250")
    return {str(x["id"]):json.loads(x["payload"]) for x in rows}


def candidates(db):
    raw=db.query("SELECT payload FROM private_365_research_candidates LIMIT 250")
    result={}
    for row in raw:
        v=json.loads(row["payload"])
        mid=str(v.get("source_match_id") or "")
        if not re.fullmatch(r"[1-9][0-9]{1,13}",mid):
            raise ValueError("invalid_private_candidate_id")
        if mid in result:
            raise ValueError("duplicate_candidate_id")
        if v.get("catalog_verified") is not True:
            raise ValueError("candidate_has_unverified_competition")
        result[mid]=v
    return result


def store_audit(db,match_id,row):
    """One compact private match-level audit. Does not store third-party events."""
    db.query("INSERT OR REPLACE INTO private_365_stats_audit(id,payload) VALUES(?,?)",
             (match_id,json.dumps(row,ensure_ascii=False,separators=(",",":"))))


def store_verified(db,row):
    """Private research table is separate from any production prediction input."""
    db.query("""CREATE TABLE IF NOT EXISTS private_365_research_verified(
        id TEXT PRIMARY KEY NOT NULL,payload TEXT NOT NULL)""")
    db.query("INSERT OR REPLACE INTO private_365_research_verified(id,payload) VALUES(?,?)",
             (row["id"],json.dumps(row,ensure_ascii=False,separators=(",",":"))))


def batch(*,db=None,get_stats=None,max_requests=MAX_REQUESTS,delay=DELAY):
    if type(max_requests) is not int or not 1<=max_requests<=MAX_REQUESTS or delay<0:
        raise ValueError("unsafe_completeness_audit_limits")
    report={"source":"365Scores","kind":"independent_full_match_stats_vs_shot_events",
            "private_only":True,"raw_events_written":0,
            "public_private_match_rows":0,"production_predictions_changed":False,
            "request_cap":max_requests,"stats_requests":0,
            "candidate_archive_total":0,"already_audited":0,
            "new_candidates_checked":0,"new_verified_complete_xgq":0,
            "new_incomplete":0,"independent_stats_obtained":0,
            "total_count_shortfall_home":0,"total_count_shortfall_away":0,
            "cases_with_blocked_shots_explaining_both_gaps":0,
            "by_competition":{},"reasons":{},"errors":{},
            "status":"not_started"}
    counts=Counter();reasons=Counter();errors=Counter()
    connection=db if db is not None else D1()
    old=prior_audits(connection)
    incoming=candidates(connection)
    report["candidate_archive_total"]=len(incoming)
    getter=get_stats if get_stats is not None else FETCH
    ids=sorted(incoming, key=lambda i:(incoming[i].get("date",""),i))
    for mid in ids:
        if mid in old:
            report["already_audited"]+=1
            continue
        if report["stats_requests"]>=max_requests:
            report["status"]="request_budget_reached"
            break
        row=incoming[mid]
        # This query uses only known exact game IDs already saved in D1.
        report["stats_requests"]+=1
        try:
            payload=getter(mid)
            witness=stats_witness(payload,row)
            result=reconcile(row,witness)
            report["independent_stats_obtained"]+=1
            report["new_candidates_checked"]+=1
            status=result["reason"]
            audit={"status":status,"checked_at":datetime.now(timezone.utc).isoformat(),
                   "competition":row["league"],"complete":result["ok"],
                   "blocked_shots_explain_gap":result["blocked_shots_explain_gap"],
                   "home_count_difference":result["count_gap"]["home"],
                   "away_count_difference":result["count_gap"]["away"]}
            if result["ok"]:
                store_verified(connection,verified_research_row(row))
                report["new_verified_complete_xgq"]+=1
                counts[row["league"]]+=1
            else:
                report["new_incomplete"]+=1
                # Sum positive shot shortages only, never negative surplus.
                report["total_count_shortfall_home"]+=max(0,result["count_gap"]["home"])
                report["total_count_shortfall_away"]+=max(0,result["count_gap"]["away"])
                if result["blocked_shots_explain_gap"]:
                    report["cases_with_blocked_shots_explaining_both_gaps"]+=1
            store_audit(connection,mid,audit)
            reasons[status]+=1
        except (AccessDenied,HTTPError) as exc:
            errors[type(exc).__name__]+=1
            if isinstance(exc,AccessDenied) or getattr(exc,"code",0) in (401,403,429):
                report["status"]="provider_denied_stopped"
                break
        except (URLError,TimeoutError,ValueError,KeyError,TypeError,D1Error) as exc:
            # Don't persist an inconclusive request as terminally checked;
            # a later run may retry it, but only when new explicit schedule.
            errors[type(exc).__name__ if not isinstance(exc,ValueError)
                   else str(exc).split(":")[0][:70]]+=1
        finally:
            if get_stats is None:time.sleep(delay)
    report["reasons"]=dict(sorted(reasons.items()))
    report["errors"]=dict(sorted(errors.items()))
    report["by_competition"]=dict(sorted(counts.items()))
    if report["status"]=="not_started":
        report["status"]="completed"
    return report


def main():
    try:
        report=batch()
    except (D1Error,ValueError,TypeError,KeyError,URLError,TimeoutError) as exc:
        report={"source":"365Scores","status":"private_storage_unavailable",
                "reason_type":type(exc).__name__,"raw_events_written":0,
                "public_private_match_rows":0,"production_predictions_changed":False,
                "new_verified_complete_xgq":0}
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False))
    return report

if __name__=="__main__":
    main()
