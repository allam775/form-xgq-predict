"""Owner-authorized, bounded 365Scores historical-match candidate collection.

Scope: at most 3 known, public-page-documented team IDs; 4 games per team.
365Scores returns shot xG on chartEvents, but a subset of chart events must
NOT be passed to the real XGQ model without independent shot/xG totals.
This module stores compact *PROVISIONAL* summaries in PRIVATE Cloudflare D1;
it never writes raw shots or original provider payload to GitHub or artifacts.

Fetches stop on denied access and obey conservative pacing. No ID guessing.
GitHub runner must have Cloudflare D1 secrets to persist; failing private
storage does NOT convert provisional rows to public exports.
"""
from __future__ import annotations
import json
import math
import os
import time
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path
from urllib.error import HTTPError,URLError

from engine import provider365 as p
from engine.competition365 import resolve
from engine.understat_d1 import D1,D1Error

OWNERSHIP_SCOPE="prior 365Scores permission for private noncommercial XGQ research"
SOURCE_NAME="365Scores"
OUTPUT=Path("research/reports/365_private_batch_status.json")
TEAM_IDS=("224","1169","890")  # Inter, Club Brugge, Sporting CP
MAX_TEAMS=3
MAX_DETAILS_EACH=4
MAX_TOTAL_REQUESTS=MAX_TEAMS*(1+MAX_DETAILS_EACH)
PAUSE_SECONDS=1.5
MAX_EVENTS=500


def _shot_samples(game):
    home=p._side(game,"home");away=p._side(game,"away")
    h=str(home.get("id") or home.get("competitorId") or "")
    a=str(away.get("id") or away.get("competitorId") or "")
    if not h or not a or h==a:
        raise ValueError("team_identity")
    events=game.get("chartEvents") or game.get("chart_events")
    if isinstance(events,dict):
        events=events.get("events") or events.get("chartEvents") or events.get("items")
    if not isinstance(events,list) or not events or len(events)>MAX_EVENTS:
        raise ValueError("shot_chart_absent")
    shots={h:[],a:[]}
    for e in events:
        if not isinstance(e,dict):
            raise ValueError("malformed_event")
        if not p._is_shot(e):continue
        x=p._xg(e)
        if x is None:raise ValueError("shot_without_individual_xg")
        team=e.get("competitor") if isinstance(e.get("competitor"),dict) else {}
        who=str(e.get("competitorId") or e.get("teamId") or team.get("id") or "")
        if who not in shots:
            if type(e.get("isHome")) is bool:
                who=h if e["isHome"] else a
            elif e.get("competitorNum") in (1,2):
                who=h if e["competitorNum"]==1 else a
            else:raise ValueError("unknown_shooting_team")
        shots[who].append(x)
    if not shots[h] or not shots[a]:
        raise ValueError("one_side_has_no_shots")
    return (shots[h],shots[a])


def provisional_match(payload,mid,team_id):
    game=payload.get("game",payload) if isinstance(payload,dict) else None
    if not isinstance(game,dict) or p._game_id(game)!=mid or not p._final(game):
        raise ValueError("not_verified_final_identity")
    if str(team_id) not in p._identity(game):
        raise ValueError("listing_team_absent")
    competition=resolve(payload)
    if not competition["ok"]:
        raise ValueError("competition_"+competition["reason"])
    home=p._side(game,"home");away=p._side(game,"away")
    hname=str(home.get("name") or home.get("displayName") or "").strip()
    aname=str(away.get("name") or away.get("displayName") or "").strip()
    if not hname or not aname or hname.casefold()==aname.casefold():
        raise ValueError("invalid_team_names")
    score=[p._score(game,"home",home),p._score(game,"away",away)]
    shots=_shot_samples(game)
    nums=[len(x) for x in shots]
    sums=[round(sum(x),6) for x in shots]
    xgqs=[round(sum(v*v for v in xs)/len(xs),8) for xs in shots]
    dt=p._date(game)
    # These are compact PRIVATE candidates, not verified complete match rows.
    return {
        "source":SOURCE_NAME, "source_match_id":mid,
        "league":competition["league"],
        "competition_id":competition["provider_competition_id"],
        "competition_identity_basis":competition["competition_identity_basis"],
        "catalog_verified":competition["catalog_verified"],
        "date":dt,"home":hname,"away":aname,
        "hg":score[0],"ag":score[1],
        "home_chart_shots":nums[0],"away_chart_shots":nums[1],
        "home_chart_xg_sum":sums[0],"away_chart_xg_sum":sums[1],
        "home_provisional_xgq":xgqs[0],"away_provisional_xgq":xgqs[1],
        "completeness":"NOT_VERIFIED_INDEPENDENT_TOTALS",
        "eligible_for_forecast":False,
        "raw_events_stored":False
    }


def _unique_results(raw,team_id):
    ids=[]
    for g in p._unpack_games(raw):
        mid=p._game_id(g)
        if mid and str(team_id) in p._identity(g) and mid not in ids:
            ids.append(mid)
    return ids


def persist_private(rows,db):
    """Idempotent per-match UPSERT in PRIVATE D1, no raw shots."""
    db.query("""CREATE TABLE IF NOT EXISTS private_365_research_candidates(
        id TEXT PRIMARY KEY NOT NULL, payload TEXT NOT NULL)""")
    # Full private rows, not public GitHub logs.
    for row in rows:
        db.query("INSERT OR REPLACE INTO private_365_research_candidates(id,payload) VALUES(?,?)",
                 (row["source_match_id"],json.dumps(row,ensure_ascii=False,separators=(",",":"))))
    # Number of rows is checked in the same private table, no values exported.
    count=db.query("SELECT COUNT(*) AS n FROM private_365_research_candidates")
    return int(count[0]["n"])


def collect(transport=None,db=None,*,team_ids=TEAM_IDS,per_team=MAX_DETAILS_EACH,
            delay=PAUSE_SECONDS):
    if not team_ids or len(team_ids)>MAX_TEAMS or per_team<1 or per_team>MAX_DETAILS_EACH:
        raise ValueError("Exceeded bounded source research limits")
    if any(team not in TEAM_IDS for team in team_ids):
        raise ValueError("Only known team IDs may be used")
    report={"source":"365Scores","scope":OWNERSHIP_SCOPE,
            "request_cap":len(team_ids)*(1+per_team),
            "requests":0,"listing_candidates":0,"details_inspected":0,
            "competition_verified":0,"provisional_candidates":0,
            "accepted_complete_xgq":0,"private_candidates_saved":0,
            "private_candidate_archive_total":None,
            "private_storage_status":"not_started",
            "rejections":{},"by_competition":{},
            "raw_provider_payloads_stored":0,"published_private_match_rows":0,
            "status":"not_started"}
    bad=Counter();leagues=Counter();found=[];known=set()
    def get(path,params):
        # Only the two existing documented endpoints; obey request cap.
        if report["requests"]>=report["request_cap"]:
            raise ValueError("request_limit")
        # increment for attempted requests, including provider denial.
        report["requests"]+=1
        return p.fetch(path,params,transport=transport)
    try:
        for team in team_ids:
            index=get("games/results/",{"competitors":team})
            candidates=_unique_results(index,team)
            report["listing_candidates"]+=len(candidates)
            if transport is None:time.sleep(delay)
            for mid in candidates[:per_team]:
                if mid in known:continue
                known.add(mid)
                try:
                    response=get("game/",{"gameId":mid,"topBookmaker":"14"})
                    report["details_inspected"]+=1
                    state=resolve(response)
                    if state["ok"]:
                        report["competition_verified"]+=1
                    try:
                        row=provisional_match(response,mid,team)
                    except (ValueError,TypeError,KeyError) as exc:
                        bad[str(exc).split(":")[0][:90]]+=1
                        continue
                    found.append(row)
                    leagues[row["league"]]+=1
                except p.AccessDenied:
                    report["status"]="provider_access_denied_stopped"
                    break
                except HTTPError as exc:
                    if exc.code in (401,403,429):
                        report["status"]="provider_access_denied_stopped"
                        break
                    bad["http_"+str(exc.code)]+=1
                except (URLError,TimeoutError,ValueError) as exc:
                    bad["detail_"+type(exc).__name__]+=1
                finally:
                    if transport is None:time.sleep(delay)
            if report["status"]=="provider_access_denied_stopped":
                break
    except p.AccessDenied:
        report["status"]="provider_access_denied_stopped"
    except (HTTPError,URLError,TimeoutError,ValueError) as exc:
        bad["listing_"+type(exc).__name__]+=1
        report["status"]="listing_failed_stopped"

    report["provisional_candidates"]=len(found)
    report["by_competition"]=dict(sorted(leagues.items()))
    report["rejections"]=dict(sorted(bad.items()))
    # D1 is mandatory to save a candidate; nothing secret enters public audit.
    if found:
        try:
            database=db if db is not None else D1()
            report["private_candidate_archive_total"]=persist_private(found,database)
            report["private_candidates_saved"]=len(found)
            report["private_storage_status"]="success"
        except (D1Error,ValueError,TypeError,KeyError) as exc:
            report["private_storage_status"]="failed_"+type(exc).__name__
    else:
        report["private_storage_status"]="no_qualifying_candidates"
    if report["status"]=="not_started":
        report["status"]="completed_provisional_research_batch"
    return report


def main():
    result=collect()
    OUTPUT.parent.mkdir(parents=True,exist_ok=True)
    OUTPUT.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print(json.dumps(result,ensure_ascii=False))
    return result

if __name__=="__main__":main()
