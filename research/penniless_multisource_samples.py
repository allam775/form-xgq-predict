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
    """Sample multiple genuine open cohorts and sparse men's UCL seasons.

    No synthetic XGQ. Errors for one archive never break other archives.
    Match events are read in memory and only compact derived source-attributed
    summaries are retained. These are SAMPLES, not incremental D1 inserts.
    """
    cohorts=[
        ("en.1",2,27),("de.1",9,281),("de.1",9,27),
        ("es.1",11,90),("fr.1",7,27),("it.1",12,27)
    ]
    response={"status":"not_started","indexes_checked":0,
      "sampled":0,"accepted":0,"rejected":{},"samples":[],
      "reusable_new_archive_rows":0,
      "sample_vs_incremental":"sampling only: archive dedup not assessed",
      "license_note":"StatsBomb Open Data: credit Hudl StatsBomb"}
    bad=Counter()
    try:
        competitions=json.loads(get("https://raw.githubusercontent.com/hudl/open-data/master/data/competitions.json",limit=2_000_000))
        if not isinstance(competitions,list):raise ValueError("Invalid competition catalog")
        available={(m.get("competition_id"),m.get("season_id")) for m in competitions
                   if isinstance(m,dict) and m.get("competition_gender")=="male"}
    except (HTTPError,URLError,TimeoutError,ValueError) as e:
        response["status"]="catalog_unavailable"
        response["rejected"]={"catalog_"+type(e).__name__:1}
        return response
    cohorts=[c for c in cohorts if (c[1],c[2]) in available]
    ucl=sorted((c for c in competitions if isinstance(c,dict)
         and c.get("competition_id")==16 and c.get("competition_gender")=="male"
         and isinstance(c.get("season_id"),int)),
         key=lambda c:c.get("season_name",""),reverse=True)
    cohorts += [("uefa.cl",16,c["season_id"]) for c in ucl[:4]]
    used=set()
    for league,comp,season in cohorts:
        if response["sampled"]>=18:break
        try:
            matches=json.loads(get(
                f"https://raw.githubusercontent.com/hudl/open-data/master/data/matches/{comp}/{season}.json",
                limit=5_000_000))
            if not isinstance(matches,list):raise ValueError("Invalid match index")
            response["indexes_checked"]+=1
        except (HTTPError,URLError,TimeoutError,ValueError) as e:
            bad["index_"+type(e).__name__]+=1;continue
        available_matches=sorted((m for m in matches if isinstance(m,dict)
            and type(m.get("match_id")) is int
            and m["match_id"] not in used
            and type(m.get("home_score")) is int
            and type(m.get("away_score")) is int
            and isinstance(m.get("match_date"),str)),
            key=lambda m:(m["match_date"],m["match_id"]))
        if not available_matches:continue
        indices=([len(available_matches)//2] if league=="uefa.cl"
                 else [len(available_matches)//4,len(available_matches)*3//4])
        for index in dict.fromkeys(indices):
            if response["sampled"]>=18:break
            match=available_matches[index]
            mid=match["match_id"];used.add(mid);response["sampled"]+=1
            try:
                events=json.loads(get(URLS["statsbomb_event"].format(match_id=mid)))
                row=statsbomb_to_row(match,events,league)
                if row["home_shots"]<1 or row["away_shots"]<1:
                    raise ValueError("One team missing original shot xG")
                response["samples"].append({
                    "date":row["date"],"competition":league,
                    "source_match_id":row["source_match_id"],
                    "home":row["home"],"away":row["away"],
                    "home_shots":row["home_shots"],"away_shots":row["away_shots"],
                    "home_xg":row["home_xg"],"away_xg":row["away_xg"],
                    "home_xgq":row["home_xgq"],"away_xgq":row["away_xgq"],
                    "verified_shot_events":True,"source":"StatsBomb Open Data"})
                response["accepted"]+=1
            except (HTTPError,URLError,TimeoutError,ValueError,TypeError,KeyError) as e:
                bad["event_"+type(e).__name__]+=1
    response["rejected"]=dict(bad)
    response["unique_accepted_match_ids"]=len(set(
        m["source_match_id"] for m in response["samples"]))
    response["status"]="sampled_public_shot_events" if response["sampled"] else "no_source_matches"
    return response


def run_openfootball():
    """Use published match results, never claim individual-shot xG.

    UCL source uses the OpenFootball Champions League results-only archive;
    domestic coverage comes from published OpenFootball football.json files.
    """
    report={"status":"results_only","shot_level_xg":False,
            "competition_coverage":{},"completed_result_matches":0,
            "sample_season":"2025-26","kind":"results_only_never_xgq"}
    try:
        raw=get(URLS["openfootball"],limit=200_000)
        count=len([x for x in raw.splitlines() if re.search(
            r"\([A-Z]{3}\)\s+v\s+.*\([A-Z]{3}\)\s+\d+-\d+",x)])
        report["source_games_detected"]=count
        report["competition_coverage"]["uefa.cl"]={"result_rows":count}
    except (HTTPError,URLError,TimeoutError,ValueError) as e:
        report["competition_coverage"]["uefa.cl"]={"error":type(e).__name__}
    leagues=("en.1","de.1","es.1","it.1","fr.1","pt.1","tr.1","nl.1","be.1")
    for league in leagues:
        try:
            url=f"https://raw.githubusercontent.com/openfootball/football.json/master/2025-26/{league}.json"
            content=json.loads(get(url,limit=3_000_000))
            matchlist=content.get("matches")
            if not isinstance(matchlist,list):raise ValueError("Missing games array")
            def valid_score(s):
                if isinstance(s,dict):s=s.get("ft")
                return isinstance(s,list) and len(s)==2 and all(
                    type(x) is int and 0<=x<=30 for x in s)
            completed=[m for m in matchlist if isinstance(m,dict)
                and valid_score(m.get("score"))
                and isinstance(m.get("date"),str)
                and m["date"][:10]<=datetime.now(timezone.utc).date().isoformat()]
            report["competition_coverage"][league]={
                "listed_matches":len(matchlist),"completed_result_matches":len(completed)}
            report["completed_result_matches"]+=len(completed)
        except (HTTPError,URLError,TimeoutError,ValueError,KeyError) as e:
            report["competition_coverage"][league]={"error":type(e).__name__}
    return report


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


def get_prefix(url,limit=10_000):
    """Retrieve only an initial byte range from a large MIT-licensed CSV."""
    p=urlparse(url)
    if p.scheme!="https" or p.hostname!="raw.githubusercontent.com":
        raise ValueError("Unapproved open dataset location")
    req=Request(url,headers={"Accept":"text/csv",
                             "User-Agent":"Penniless-XGQ-Research/0.4",
                             "Range":f"bytes=0-{limit-1}"})
    with urlopen(req,timeout=25) as res:
        raw=res.read(limit)
    return raw.decode("utf-8-sig",errors="replace")


def run_clubelo_catalog():
    """Actual small historical Elo+match CSV header samples; NO bulk download."""
    root="https://raw.githubusercontent.com/xgabora/Club-Football-Match-Data/main/data/"
    result={"status":"not_started","license":"MIT repository license",
            "large_files_downloaded":0,"csv_samples":{}}
    for kind,name in (("elo_ratings","EloRatings.csv"),
                      ("club_matches","Matches.csv")):
        try:
            prefix=get_prefix(root+name)
            reader=csv.reader(io.StringIO(prefix))
            header=next(reader)
            next(reader)
            result["csv_samples"][kind]={
                "readable_header":True,
                "first_fields":header[:25],
                "sample_first_rows_requested":True,
                "bytes_downloaded_max":10_000}
        except Exception as e:
            result["csv_samples"][kind]={"readable_header":False,
                                          "reason":type(e).__name__}
    result["status"]="real_csv_sample_available" if all(
       x["readable_header"] for x in result["csv_samples"].values()) else "partial_or_unavailable"
    return result


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
    display=str(match.get("competitionDisplayName") or "").strip().casefold()
    known_competitions=(payload.get("competitions") or []) if isinstance(payload,dict) else []
    catalog=next((item for item in known_competitions
                  if isinstance(item,dict) and
                  str(item.get("id") or "")==str(cid) and
                  str(item.get("name") or "").strip().casefold()==display),
                 None)
    catalog_verified=bool(display and catalog and catalog.get("countryId") is not None)
    def safe_fieldnames(obj):
        return sorted(str(k) for k in obj.keys()
                      if isinstance(k,str) and re.search(
                          r"score|competit|league|tourna|stat|result|chart|game|team|fixture",
                          k,re.I))[:35] if isinstance(obj,dict) else []
    status="partial_unverified"
    if bad:status="missing_individual_shot_xg"
    elif unassigned:status="shots_without_team"
    elif not shots[hi] or not shots[ai]:status="missing_one_team_shots"
    elif not ((name and country) or catalog_verified):
        status="missing_competition_identity"
    # 365Scores sometimes serializes actual integer goal counts as 1.0.
    # Accept ONLY an exact integral float within 0..30, never decimal goals.
    def verified_score(side,direction):
        v=side.get("score")
        if type(v) is float and v.is_integer() and 0<=v<=30:
            return int(v)
        from engine.provider365 import _score
        return _score(match,direction,side)
    score_ok=True
    try:
        score=[verified_score(home,"home"),verified_score(away,"away")]
    except (ValueError,KeyError,TypeError):
        score_ok=False
    # Return only counts and Boolean checks, not raw provider data / derived xGQ.
    return {"status":status,"shot_events":len(shots[hi])+len(shots[ai]),
            "home_shots_detected":len(shots[hi]),"away_shots_detected":len(shots[ai]),
            "shots_missing_xg":bad,"shots_unassigned":unassigned,
            "score_present":score_ok,
            "competition_identity_present":bool((name and country) or catalog_verified),
            "competition_catalog_identity_confirmed":catalog_verified,
            "competition_display_name_present":bool(match.get("competitionDisplayName")),
            "home_score_field_kind":type(home.get("score")).__name__,
            "away_score_field_kind":type(away.get("score")).__name__,
            "home_score_nested_fields":sorted(str(k) for k in home.get("score",{})
                 if isinstance(k,str))[:15] if isinstance(home.get("score"),dict) else [],
            "away_score_nested_fields":sorted(str(k) for k in away.get("score",{})
                 if isinstance(k,str))[:15] if isinstance(away.get("score"),dict) else [],
            "root_competition_item_fields":sorted(str(k) for k in
                ((payload.get("competitions") or [{}])[0].keys()
                 if isinstance(payload.get("competitions"),list) and
                    payload["competitions"] and isinstance(payload["competitions"][0],dict)
                 else []))[:25],
            "game_field_names":safe_fieldnames(match),
            "home_field_names":safe_fieldnames(home),
            "away_field_names":safe_fieldnames(away),
            "root_field_names":safe_fieldnames(payload),
            "independent_team_shot_totals_matched":False,
            "accepted_complete_xgq":False}


def run_365(*,transport=None,limit=4,sleep=1.5,team_ids=("224",)):
    """Bounded, known real 365Scores club IDs, not brute-force discovery.

    '224' appears in verified legacy tests for Inter. Club Brugge '1169'
    and Sporting CP '890' appear in published official 365Scores match
    page URLs, and the results listing must independently confirm membership.
    """
    if not team_ids or len(team_ids)>3 or any(
       t not in ("224","1169","890") for t in team_ids):
        raise ValueError("Only known, page-documented research IDs permitted")
    report={"status":"not_started","known_configured_team_ids":list(team_ids),
            "request_cap":len(team_ids)*(1+limit),"queries_made":0,
            "details":[],"accepted_complete_xgq":0,
            "source_authorization":"owner reports prior private XGQ consent",
            "bulk_scope_not_assumed":True,"raw_provider_bytes_written":0}
    def query(path,params):
        result=fetch(path,params,transport=transport)
        report["queries_made"]+=1
        return result
    listings=0
    try:
        for team_id in team_ids:
            index=query("games/results/",{"competitors":team_id})
            eligible={}
            for game in _unpack_games(index):
                ident=_game_id(game)
                if ident and team_id in _identity(game):
                    eligible[ident]=1
            if team_id=="224":
                # One confirmed old test match, even if outside index horizon.
                eligible.setdefault("4732693",1)
            listings+=len(eligible)
            for mid in list(eligible)[:limit]:
                if transport is None:time.sleep(sleep)
                try:
                    payload=query("game/",{"gameId":mid,"topBookmaker":"14"})
                except AccessDenied:
                    report["status"]="access_denied_stopped";return report
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
                info["ordinal"]=len(report["details"])+1
                report["details"].append(info)
        report["status"]="candidate_samples_inspected"
        report["listings_with_configured_team"]=listings
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
     ("365scores_legacy_authorized_pilot",
      lambda:run_365(team_ids=("224","1169","890"),limit=2)),
    )
    for name,fn in funcs:
        try:sources[name]=fn()
        except Exception as e:
            sources[name]={"status":"unavailable","reason":type(e).__name__}
    # This repository is public: NEVER publish per-game 365Scores details.
    # Keep in-memory diagnostic details only during processing and retain a
    # league-agnostic summary of reason counts, not scorelines/shot arrays.
    private=sources.get("365scores_legacy_authorized_pilot")
    if isinstance(private,dict) and isinstance(private.get("details"),list):
        reasons=Counter(d.get("status","unidentified") for d in private["details"])
        private["detail_diagnostic_status_counts"]=dict(sorted(reasons.items()))
        private["matches_inspected"]=len(private["details"])
        # Share field NAME patterns only, never provider field values or
        # per-match shot series, scores, xG or match IDs.
        private["observed_score_field_kinds"]=dict(Counter(
            r.get("home_score_field_kind","missing") for r in private["details"]))
        private["games_with_competition_display_name"]=sum(
            bool(r.get("competition_display_name_present")) for r in private["details"])
        private["games_with_competition_catalog_match"]=sum(
            bool(r.get("competition_catalog_identity_confirmed"))
            for r in private["details"])
        private["games_with_readable_final_score"]=sum(
            bool(r.get("score_present")) for r in private["details"])
        for field in ("home_score_nested_fields","away_score_nested_fields",
                      "root_competition_item_fields"):
            private["observed_"+field]=sorted(set(
                name for row in private["details"] for name in row.get(field,[])))[:30]
        for field in ("game_field_names","home_field_names",
                      "away_field_names","root_field_names"):
            private["observed_"+field]=sorted(set(
                name for row in private["details"]
                for name in row.get(field,[])))[:45]
        del private["details"]
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
