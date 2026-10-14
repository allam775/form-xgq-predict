"""Detailed PRIVATE classification of the eleven 365Scores rejected matches.

We already know each individual shot xG and total snapshots remain stable
across both previously used endpoints. Find evidence of extra types,
disallowed goals, periods, penalties or status flags in chart events.

Only per-category COUNTS are retained in D1: NO per-shot arrays, shot xG,
shot IDs, player IDs, locations, or raw provider responses.
NO modification of previous verification, XGQ or model.
Bounded to 11 match-detail requests with 1.5 s pause.
"""
from __future__ import annotations
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path
import importlib
import json
import math
import time

from engine import provider365 as p
from engine.competition365 import resolve
from engine.understat_d1 import D1,D1Error
base=importlib.import_module("research.365_stats_completeness_batch")
OUT=Path("research/reports/365_rejected_event_categories.json")
MAX_CALLS=11

def label(value):
    if isinstance(value,dict):
        value=value.get("name") or value.get("description") or value.get("id") or value.get("type")
    if value is None:return "absent"
    if isinstance(value,bool):return str(value).lower()
    if not isinstance(value,(str,int,float)):return type(value).__name__
    return str(value).strip().casefold()[:60] or "empty"

def time_bucket(value):
    if isinstance(value,dict):
        return "object:"+",".join(sorted(str(k) for k in value.keys()))[:90]
    if isinstance(value,(int,float)) and math.isfinite(value):
        return "0-45" if value<=45 else "46-90" if value<=90 else "91plus"
    if isinstance(value,str):
        return "string_time"
    return type(value).__name__

def group_event_classes(game):
    home=p._side(game,"home")
    away=p._side(game,"away")
    hi=str(home.get("id") or home.get("competitorId") or "")
    ai=str(away.get("id") or away.get("competitorId") or "")
    if not hi or not ai or hi==ai:raise ValueError("not_a_two_team_game")
    events=game.get("chartEvents") or game.get("chart_events")
    if isinstance(events,dict):events=events.get("events") or events.get("chartEvents") or events.get("items")
    if not isinstance(events,list) or not events or len(events)>500:
        raise ValueError("chart_events_not_bounded")
    groups={s:{k:Counter() for k in ("outcome","subtype","status","goal_description","body_part",
                                   "time_bucket","outcome_x_subtype_x_status",
                                   "xgot_display_presence","event_type")}
            for s in ("home","away")}
    for e in events:
        if not isinstance(e,dict) or not p._is_shot(e):continue
        who=e.get("competitor") if isinstance(e.get("competitor"),dict) else {}
        team=str(e.get("competitorId") or e.get("teamId") or who.get("id") or "")
        if team==hi:side="home"
        elif team==ai:side="away"
        elif type(e.get("isHome")) is bool:side="home" if e["isHome"] else "away"
        elif e.get("competitorNum") in (1,2):side="home" if e["competitorNum"]==1 else "away"
        else:raise ValueError("unknown_shot_side")
        goal=label(e.get("goalDescription"))
        # Do NOT include possibly identifying freeform detail; classify only.
        if any(word in goal for word in ("penalty","pen","spot")):goal="penalty"
        elif "own" in goal:goal="own_goal"
        elif goal not in ("absent","empty"):goal="other_goal_description"
        vals={
            "outcome":label(e.get("outcome")),
            "subtype":label(e.get("subType")),
            "status":label(e.get("status")),
            "goal_description":goal,
            "body_part":label(e.get("bodyPart")),
            "time_bucket":time_bucket(e.get("time")),
            "event_type":label(e.get("type")),
            "xgot_display_presence":("present" if e.get("xgot") not in ("-",None,"") else "missing"),
            "outcome_x_subtype_x_status":
                label(e.get("outcome"))+"|"+label(e.get("subType"))+"|"+label(e.get("status"))
        }
        for key,val in vals.items():groups[side][key][val]+=1
    return {side:{k:dict(sorted(counts.items())) for k,counts in fields.items()}
            for side,fields in groups.items()}

def main():
    d=D1()
    candidates=base.candidates(d)
    audits=base.prior_audits(d)
    rejected=sorted(mid for mid in candidates if
                    mid in audits and audits[mid].get("complete") is False)
    if len(rejected)!=11:
        raise ValueError("Expected exactly 11 rejected original cases")
    d.query("""CREATE TABLE IF NOT EXISTS private_365_event_category_audit(
        id TEXT PRIMARY KEY NOT NULL,payload TEXT NOT NULL)""")
    completed=0
    summary={"case_count":len(rejected),"requests":0,"completed":0,
             "raw_events_stored":False,"match_identifiers_exposed":False,
             "xg_probabilities_stored":False,"verified_archive_changed":False,
             "classification_keys":[],"errors":{}}
    errors=Counter()
    for mid in rejected:
        try:
            summary["requests"]+=1
            response=p.fetch("game/",{"gameId":mid,"topBookmaker":"14"})
            game=response.get("game",response)
            if p._game_id(game)!=mid or not p._final(game):
                raise ValueError("match_identity_not_final")
            comp=resolve(response)
            if not comp["ok"] or comp["league"]!=candidates[mid]["league"]:
                raise ValueError("competition_not_verified")
            g=group_event_classes(game)
            d.query("INSERT OR REPLACE INTO private_365_event_category_audit(id,payload) VALUES(?,?)",
                    (mid,json.dumps({"groups":g,
                       "prior":audits[mid]["status"],
                       "checked_at":datetime.now(timezone.utc).isoformat()},
                       separators=(",",":"))))
            completed+=1
        except p.AccessDenied:
            errors["access_denied_stopped"]+=1
            break
        except (ValueError,TypeError,KeyError,D1Error) as exc:
            errors[type(exc).__name__ if not isinstance(exc,ValueError) else str(exc)[:80]]+=1
        finally:
            time.sleep(1.5)
    summary["completed"]=completed
    summary["classification_keys"]=[
        "outcome","subtype","status","goal_description",
        "body_part","time_bucket","xgot_display_presence","event_type",
        "outcome_x_subtype_x_status"]
    summary["errors"]=dict(errors)
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps(summary,ensure_ascii=False))
    return summary
if __name__=="__main__":main()
