"""Single-match 365Scores stats-source schema diagnostic (owner research).

Public third-party reference documents GET /web/game/stats/?games=<match id>.
Read one match ID from private D1; do not discover or enumerate IDs.
No raw responses, team names/IDs, shots or match IDs leave the job.
"""
from __future__ import annotations
import json
import re
from pathlib import Path
from collections import Counter
from urllib.parse import urlencode
from urllib.request import Request,urlopen
from urllib.error import HTTPError,URLError

from engine.understat_d1 import D1,D1Error
from engine.provider365 import HOST,DEFAULT_QUERY,MAX_RESPONSE,AccessDenied
from engine.xgq import normalized

REPORT=Path("research/reports/365_stats_schema_audit.json")
KNOWN_DATE="2026-10-13"
KNOWN_LEAGUE="uefa.cl"
KNOWN_HOME="Inter Milan"
KNOWN_AWAY="Club Brugge"
ALLOWED_FIELDS={"statistics","competitors","actualGameStatistics","statisticsFilters"}
MAX_STAT_ROWS=500


def inspect_statistics(payload):
    """Only schema/key/taxonomy information, not match-specific values."""
    if not isinstance(payload,dict):
        return {"valid_json":False}
    stats=payload.get("statistics")
    out={"valid_json":True,
         "root_keys":sorted(str(k)[:50] for k in payload)[:40],
         "statistics_type":type(stats).__name__,
         "statistics_length":len(stats) if isinstance(stats,list) else None,
         "statistics_row_keys":[],
         "statistics_categories":[],
         "statistics_names":[],
         "competitor_count":len(payload.get("competitors",[]))
             if isinstance(payload.get("competitors"),list) else None,
         "competitor_field_names":[],
         "actual_statistics_type":type(payload.get("actualGameStatistics")).__name__,
         "statistics_filters_type":type(payload.get("statisticsFilters")).__name__}
    if isinstance(stats,list) and len(stats)<=MAX_STAT_ROWS:
        out["statistics_row_keys"]=sorted({
            str(key)[:60] for row in stats if isinstance(row,dict) for key in row})[:35]
        out["statistics_categories"]=sorted({
            str(row.get("categoryName"))[:65] for row in stats if isinstance(row,dict)
            and row.get("categoryName")})[:80]
        # Names of STATS (not values or player names) can identify which
        # metric is total shots versus on-target versus blocked.
        out["statistics_names"]=sorted({
            str(row.get("name"))[:65] for row in stats if isinstance(row,dict)
            and row.get("name")})[:130]
        out["values_kinds"]=dict(Counter(type(row.get("value")).__name__
            for row in stats if isinstance(row,dict)))
    competitors=payload.get("competitors")
    if isinstance(competitors,list):
        out["competitor_field_names"]=sorted({str(k)[:60] for obj in competitors
            if isinstance(obj,dict) for k in obj.keys()})[:30]
    actual=payload.get("actualGameStatistics")
    if isinstance(actual,dict):
        out["actual_game_statistics_keys"]=sorted(map(str,actual.keys()))[:45]
    return out


def _private_known_match(db):
    rows=db.query("SELECT payload FROM private_365_research_candidates LIMIT 250")
    found=[]
    for row in rows:
        v=json.loads(row["payload"])
        if (v.get("date")==KNOWN_DATE and v.get("league")==KNOWN_LEAGUE
            and normalized(v.get("home"))==normalized(KNOWN_HOME)
            and normalized(v.get("away"))==normalized(KNOWN_AWAY)
            and v.get("catalog_verified") is True
            and re.fullmatch(r"[1-9][0-9]{1,13}",str(v.get("source_match_id") or ""))):
            found.append(v)
    if len(found)!=1: raise ValueError("expected_unique_known_match_not_found")
    return found[0]


def fetch_stats(match_id):
    if not re.fullmatch(r"[1-9][0-9]{1,13}",match_id):
        raise ValueError("not_a_verified_match_id")
    # One publicly documented endpoint only, not new endpoint enumeration.
    url=HOST+"/game/stats/?"+urlencode({**DEFAULT_QUERY,"games":match_id})
    req=Request(url,headers={"Accept":"application/json",
                             "User-Agent":"FormXGQ-Research/0.3 (contact via project owner)"})
    try:
        with urlopen(req,timeout=18) as resp:
            data=resp.read(MAX_RESPONSE+1)
            if len(data)>MAX_RESPONSE: raise ValueError("provider_response_oversized")
            return json.loads(data)
    except HTTPError as exc:
        if exc.code in (401,403,429):
            raise AccessDenied("provider_denied_stopped_no_retry") from exc
        raise


def main():
    info={"status":"not_started","provider_requests":0,"complete_xgq_verified":0,
          "private_data_exported":False,"stats_taxonomy":{},
          "note":"Only one already-held documented match; no raw response stored."}
    try:
        db=D1()
        candidate=_private_known_match(db)
        info["private_source_candidate_found"]=True
        info["provider_requests"]=1
        response=fetch_stats(candidate["source_match_id"])
        info["stats_taxonomy"]=inspect_statistics(response)
        info["status"]="statistics_schema_retrieved"
    except (AccessDenied,HTTPError,URLError,TimeoutError,D1Error,ValueError,TypeError,KeyError) as exc:
        info["status"]="blocked_or_unavailable"
        info["reason_type"]=type(exc).__name__
    REPORT.parent.mkdir(parents=True,exist_ok=True)
    REPORT.write_text(json.dumps(info,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print(json.dumps(info,ensure_ascii=False))
    return info

if __name__=="__main__":main()
