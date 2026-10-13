"""Penniless football multi-source sample matrix (no paid APIs).

Sources: existing private Understat D1, open StatsBomb events, public
OpenFootball results, football-data.co.uk results, 365Scores owner-authorized
bounded legacy adapter, and MIT historical club-match/Elo catalog.

Only StatsBomb's openly distributable shot XGQ is reported per match.
365Scores raw payloads or individual shots are never persisted or logged.
Private Understat rows are never emitted; only league-level row counts.
365Scores matches are CANDIDATES, never accepted as full XGQ unless verified
against independent shot totals, final score and competition identity.
"""
from __future__ import annotations
import csv
import io
import json
import os
import re
import time
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path
from urllib.error import HTTPError,URLError
from urllib.request import Request,urlopen
from urllib.parse import urlparse

from engine.provider365 import (_unpack_games,_game_id,_side,_identity,_final,_is_shot,
    _xg,_competition,fetch,AccessDenied)
from engine.xgq import statsbomb_to_row
from engine.understat_d1 import D1

MAX_READ=15_000_000
OUT=Path("research/reports/penniless_sample_matrix.json")
URLS={
 "statsbomb_index":"https://raw.githubusercontent.com/hudl/open-data/master/data/matches/2/27.json",
 "statsbomb_event":"https://raw.githubusercontent.com/hudl/open-data/master/data/events/{match_id}.json",
 "openfootball":"https://raw.githubusercontent.com/openfootball/champions-league/master/2025-26/cl.txt",
 "football_data":"https://www.football-data.co.uk/mmz4281/2526/E0.csv",
 "clubelo_catalog":"https://raw.githubusercontent.com/xgabora/Club-Football-Match-Data/main/README.md",
}


def get(url,limit=MAX_READ):
    p=urlparse(url)
    if p.scheme!="https" or p.hostname not in (
         "raw.githubusercontent.com","www.football-data.co.uk"):
        raise ValueError("Unapproved public sample host")
    req=Request(url,headers={"Accept":"application/json,text/csv,text/plain",
                              "User-Agent":"Penniless-XGQ-Research/0.4"})
    with urlopen(req,timeout=25) as res:
        raw=res.read(limit+1)
    if len(raw)>limit:
        raise ValueError("Open sample response too large")
    return raw.decode("utf-8-sig",errors="replace")


def run_understat():
    """D1 only: previously owner-authorized compact shot match archive."""
    try:
        history=D1().history()
    except Exception as e:
        return {"status":"not_available","reason":type(e).__name__,
                "private_rows_exported":0}
    valid=[r for r in history if isinstance(r,dict) and isinstance(r.get("league"),str)]
    leagues=Counter(r["league"] for r in valid)
    return {
      "status":"existing_private_shot_history",
      "rows_available":len(valid),
      "by_league":dict(sorted(leagues.items())),
      "private_rows_exported":0,
      "is_fresh_365scores_source":False,
      "note":"Already collected privately; this batch only examines counts."
    }


def run_statsbomb():
    try:
        games=json.loads(get(URLS["statsbomb_index"],limit=4_000_000))
        if not isinstance(games,list):raise ValueError("Invalid index JSON")
        candidates=sorted((g for g in games if g.get("match_id") and
                           isinstance(g.get("home_score"),int)),
                          key=lambda r:(r.get("match_date",""),r["match_id"]))[:2]
        accepted=[]
        rejected=Counter()
        for match in candidates:
            try:
                url=URLS["statsbomb_event"].format(match_id=int(match["match_id"]))
                events=json.loads(get(url))
                row=statsbomb_to_row(match,events,"en.1")
                accepted.append({
                    "date":row["date"],"source_match_id":row["source_match_id"],
                    "home":row["home"],"away":row["away"],
                    "home_shots":row["home_shots"],"away_shots":row["away_shots"],
                    "home_xg":row["home_xg"],"away_xg":row["away_xg"],
                    "home_xgq":row["home_xgq"],"away_xgq":row["away_xgq"],
                    "verified_shot_events":True,
                    "source":"StatsBomb Open Data"
                })
            except Exception as e:
                rejected[type(e).__name__]+=1
        return {"status":"sampled_public_shot_events",
                "index_matches":len(games),
                "sampled":len(candidates),"accepted":len(accepted),
                "rejected":dict(rejected),"samples":accepted,
                "license_note":"StatsBomb Open Data: attribute Hudl StatsBomb"}
    except Exception as e:
        return {"status":"unavailable","reason":type(e).__name__,"accepted":0}


def run_openfootball():
    try:
        raw=get(URLS["openfootball"],limit=200_000)
        count=len([x for x in raw.splitlines() if re.search(
            r"\([A-Z]{3}\)\s+v\s+.*\([A-Z]{3}\)\s+\d+-\d+",x)])
        return {"status":"results_only","source_games_detected":count,
                "shot_level_xg":False,"sample_season":"2025-26 UCL"}
    except Exception as e:
        return {"status":"unavailable","reason":type(e).__name__,
                "shot_level_xg":False}


def run_football_data():
    try:
        raw=get(URLS["football_data"],limit=500_000)
        entries=list(csv.DictReader(io.StringIO(raw)))
        valid=[x for x in entries if x.get("HomeTeam") and x.get("AwayTeam") and
               x.get("FTHG") and x.get("FTAG")]
        cols=list(entries[0]) if entries else []
        return {"status":"results_and_aggregates_only","rows":len(valid),
                "column_count":len(cols),
                "has_home_away_shots":"HS" in cols and "AS" in cols,
                "has_individual_shot_xg":False,"season":"2025-26 EPL"}
    except Exception as e:
        return {"status":"unavailable","reason":type(e).__name__,
                "has_individual_shot_xg":False}


def run_clubelo_catalog():
    """MIT-licensed club results/Elo dataset; don't bulk download 11+45 MB."""
    try:
        raw=get(URLS["clubelo_catalog"],limit=100_000)
        return {"status":"metadata_sample_only","readme_bytes":len(raw.encode()),
                "elo_csv_reference_present":"EloRatings.csv" in raw,
                "match_csv_reference_present":"Matches.csv" in raw,
                "large_files_downloaded":0,
                "license":"MIT (repository license; verify dataset provenance separately)"}
    except Exception as e:
        return {"status":"unavailable","reason":type(e).__name__,
                "large_files_downloaded":0}


def _shot_diagnostics(payload,match_id):
    match=payload.get("game",payload) if isinstance(payload,dict) else None
    if not isinstance(match,dict) or _game_id(match)!=match_id:
        return {"status":"unexpected_match"}
    if not _final(match):return {"status":"not_finished"}
    home=_side(match,"home");away=_side(match,"away")
    hi=str(home.get("id") or home.get("competitorId") or "")
    ai=str(away.get("id") or away.get("competitorId") or "")
    if not hi or not ai or hi==ai:
        return {"status":"missing_team_identity"}
    events=match.get("chartEvents") or match.get("chart_events")
    if isinstance(events,dict):
        events=events.get("events") or events.get("chartEvents") or events.get("items")
    if not isinstance(events,list):
        return {"status":"no_chart_events"}
    shots={hi:[],ai:[]}
    bad=unassigned=0
    for evt in events[:500]:
        if not isinstance(evt,dict) or not _is_shot(evt):continue
        v=_xg(evt)
        if v is None:bad+=1
        competitor=evt.get("competitor")
        competitor=competitor if isinstance(competitor,dict) else {}
        team=str(evt.get("competitorId") or evt.get("teamId") or
                 competitor.get("id") or "")
        if team not in shots:
            if type(evt.get("isHome")) is bool:
                team=hi if evt["isHome"] else ai
            elif evt.get("competitorNum") in (1,2):
                team=hi if evt["competitorNum"]==1 else ai
            else:
                unassigned+=1
                continue
        if v is not None:shots[team].append(v)
    cid,name,country=_competition(match)
    status="partial_unverified"
    if bad:status="missing_individual_shot_xg"
    elif unassigned:status="shots_without_team"
    elif not shots[hi] or not shots[ai]:status="missing_one_team_shots"
    elif not name or not country:status="missing_competition_identity"
    # Score may be omitted from detail JSON; never invent it.
    score_ok=True
    try:
        from engine.provider365 import _score
        score=[_score(match,"home",home),_score(match,"away",away)]
    except (ValueError,KeyError,TypeError):
        score_ok=False
    # Return only counts and Boolean checks, not raw provider data / derived xGQ.
    return {"status":status,"shot_events":len(shots[hi])+len(shots[ai]),
            "home_shots_detected":len(shots[hi]),"away_shots_detected":len(shots[ai]),
            "shots_missing_xg":bad,"shots_unassigned":unassigned,
            "score_present":score_ok,"competition_identity_present":bool(name and country),
            "independent_team_shot_totals_matched":False,
            "accepted_complete_xgq":False}


def run_365(*,transport=None,limit=4,sleep=1.5):
    """One known owner-configured Inter team results page + <=4 game details.

    Only existing team ID 224; no enumeration or guessed team IDs.
    Uses same endpoint patterns as previously authorized original model.
    Response is processed in memory and discarded. Never write raw responses.
    """
    report={"status":"not_started","known_configured_team_id":"224",
            "request_cap":1+limit,"queries_made":0,"details":[],
            "accepted_complete_xgq":0,
            "source_authorization":"owner reports prior private XGQ consent",
            "bulk_scope_not_assumed":True,"raw_provider_bytes_written":0}
    def query(path,params):
        result=fetch(path,params,transport=transport)
        report["queries_made"]+=1
        return result
    try:
        index=query("games/results/",{"competitors":"224"})
        eligible={}
        for game in _unpack_games(index):
            ident=_game_id(game)
            if ident and "224" in _identity(game):
                eligible[ident]=1
        # Prior known confirmed ID guarantees one match even if listing is empty.
        eligible.setdefault("4732693",1)
        ids=list(eligible)[:limit]
        report["listings_with_configured_team"]=len(eligible)
        for mid in ids:
            if transport is None:time.sleep(sleep)
            try:
                payload=query("game/",{"gameId":mid,"topBookmaker":"14"})
            except AccessDenied:
                report["status"]="access_denied_stopped"
                return report
            except HTTPError as e:
                if e.code in (401,403,429):
                    report["status"]="access_denied_stopped";return report
                report["details"].append({"status":"http_error","code":e.code})
                continue
            except (URLError,TimeoutError,ValueError) as e:
                report["details"].append({"status":"failed_request",
                                          "reason":type(e).__name__})
                continue
            info=_shot_diagnostics(payload,mid)
            # Use match ordinal to avoid accidental redistribution of IDs
            info["ordinal"]=len(report["details"])+1
            report["details"].append(info)
        report["status"]="candidate_samples_inspected"
        report["total_shot_events_with_individual_xg"]=sum(
           v.get("shot_events",0) for v in report["details"])
        return report
    except AccessDenied:
        report["status"]="access_denied_stopped"
        return report
    except HTTPError as e:
        report["status"]="http_error_stopped"
        report["http_code"]=int(e.code)
        return report
    except (URLError,TimeoutError,ValueError) as e:
        report["status"]="unavailable"
        report["reason"]=type(e).__name__
        return report


def main():
    start=datetime.now(timezone.utc)
    sources={}
    funcs=(
     ("understat_private",run_understat),
     ("statsbomb_open",run_statsbomb),
     ("openfootball",run_openfootball),
     ("football_data_uk",run_football_data),
     ("club_elo_catalog",run_clubelo_catalog),
     ("365scores_legacy_authorized_pilot",run_365),
    )
    for name,fn in funcs:
        try:sources[name]=fn()
        except Exception as e:
            sources[name]={"status":"unavailable","reason":type(e).__name__}
    report={
      "created_at_utc":start.isoformat(),
      "scope":"zero-cost bounded source samples; private XGQ inputs unchanged",
      "production_modified":False,"all_live_sources_unrestricted":False,
      "candidate_does_not_equal_accepted_xgq":True,
      "source_count":len(sources),"sources":sources,
    }
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
    concise={name:{
        "status":info.get("status"),
        "accepted":info.get("accepted",info.get("accepted_complete_xgq",None)),
        "sampled":info.get("sampled",info.get("queries_made",info.get("rows",None)))}
      for name,info in sources.items()}
    print(json.dumps({"summary":concise,"report_path":str(OUT)},sort_keys=True))
    return report


if __name__=="__main__":main()
