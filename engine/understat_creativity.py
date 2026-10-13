"""Understat match-level creativity, strictly private and source verified.

xA/key_passes are summed from ACTUAL match rosters (not season aggregates).
High-xG attempts at threshold .30 are a proxy, NOT official Big Chances.
Only aggregate team-match values are stored; no player data or shot events.
"""
from __future__ import annotations
import argparse
import json
import math
import re
import time
from .provider_understat import SOURCE, AccessDenied, fetch, parse_match
from .understat_backfill import validate_config
from .understat_d1 import D1

TABLE="private_understat_creativity"
FIELDS=("xa","key_passes","npxg","high_xg_attempts","assisted_shots",
        "open_play_shots","xg_chain","xg_buildup")


def number(value, *, maxvalue=100.0, integer=False):
    if type(value) is bool:
        raise ValueError("Invalid boolean football stat")
    if isinstance(value,str):
        if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?",value.strip()):
            raise ValueError("Invalid numeric match stat")
        value=float(value)
    if type(value) not in (int,float) or not math.isfinite(value) or not 0<=value<=maxvalue:
        raise ValueError("Invalid football stat")
    if integer and value!=int(value):
        raise ValueError("Fractional key passes")
    return int(value) if integer else float(value)


def parse_creativity(indexed, payload, *, previous=None):
    """Tie roster totals to an independently verified finished league match."""
    row=parse_match(indexed,payload)
    if previous is not None:
        if row["id"]!=previous["id"] or row["source_match_id"]!=previous["source_match_id"]:
            raise ValueError("Historical fixture identity mismatch")
        for side in ("home","away"):
            for stat in ("shots","xg","xgq"):
                if abs(row[side+"_"+stat]-previous[side+"_"+stat])>0.00002:
                    raise ValueError("Underlying historical shot data changed")
    rosters=payload.get("rosters")
    if not isinstance(rosters,dict):
        raise ValueError("Match roster missing")
    result={"id":row["id"],"league":row["league"],"date":row["date"],
            "source_match_id":row["source_match_id"],"source":SOURCE,
            "big_chance_metric":"nonpenalty_shots_with_xg_at_least_0.30_proxy"}
    for side,letter in (("home","h"),("away","a")):
        team_players=rosters.get(letter)
        events=payload.get("shots",{}).get(letter)
        if not isinstance(team_players,dict) or not team_players or not isinstance(events,list):
            raise ValueError("Rosters and shot events required")
        xa=key_passes=xgc=xgb=0.0
        for player in team_players.values():
            if not isinstance(player,dict) or str(player.get("team_id"))!=str(indexed[side+"_id"]):
                raise ValueError("Roster team ID mismatch")
            xa+=number(player.get("xA"),maxvalue=30)
            key_passes+=number(player.get("key_passes"),maxvalue=60,integer=True)
            xgc+=number(player.get("xGChain"),maxvalue=50)
            xgb+=number(player.get("xGBuildup"),maxvalue=50)
        if any(not isinstance(s.get("situation"),str) for s in events):
            raise ValueError("Cannot estimate non-penalty xG without shot situation")
        nonpen=[s for s in events if s["situation"]!="Penalty"]
        features={"xa":xa,"key_passes":int(key_passes),
                  "xg_chain":xgc,"xg_buildup":xgb,
                  "npxg":sum(float(s["xG"]) for s in nonpen),
                  "high_xg_attempts":sum(float(s["xG"])>=.3 for s in nonpen),
                  "assisted_shots":sum(bool(s.get("player_assisted")) for s in nonpen),
                  "open_play_shots":sum(s["situation"]=="OpenPlay" for s in nonpen)}
        for name,value in features.items():
            result[side+"_"+name]=round(value,6) if type(value) is float else value
    return validate_creativity(result)


def validate_creativity(row):
    if not isinstance(row,dict) or row.get("source")!=SOURCE:
        raise ValueError("Invalid Understat creativity provenance")
    if not isinstance(row.get("id"),str) or not re.fullmatch(
            r"(?:en|de|es|it|fr)\.1\|[0-9]{4}-[0-9]{2}-[0-9]{2}\|.+",row["id"]):
        raise ValueError("Invalid historical match ID")
    if not re.fullmatch(r"[1-9][0-9]{0,10}",str(row.get("source_match_id",""))):
        raise ValueError("Missing provider match ID")
    for side in ("home","away"):
        for name in FIELDS:
            value=row.get(side+"_"+name)
            if type(value) not in (int,float) or not math.isfinite(value) or value<0:
                raise ValueError("Missing verified team creativity metrics")
    return row


def enrich(db, *, max_new=100, pause=1.2, fetcher=fetch, sleeper=time.sleep):
    if type(max_new) is not int or not 1<=max_new<=250 or not .5<=pause<=15:
        raise ValueError("Invalid safe source request budget")
    validate_config(db.get_setting())
    db.query(f"CREATE TABLE IF NOT EXISTS {TABLE} (id TEXT PRIMARY KEY,payload TEXT NOT NULL)")
    known=set()
    for off in range(0,20000,250):
        page=db.query(f"SELECT id FROM {TABLE} ORDER BY id LIMIT ? OFFSET ?",(250,off))
        known.update(r["id"] for r in page)
        if len(page)<250:break
    historical=db.history()
    uncollected=[r for r in historical if r["id"] not in known]
    # Stratify each safe enrichment batch across historical periods and leagues.
    leagues=sorted({r["league"] for r in uncollected})
    pools={league:sorted((r for r in uncollected if r["league"]==league),
                         key=lambda r:(r["date"],r["id"])) for league in leagues}
    selection=[]
    quota=(max_new+max(1,len(leagues))-1)//max(1,len(leagues))
    for league in leagues:
        records=pools[league]
        n=min(len(records),quota,max_new-len(selection))
        for j in range(n):
            position=min(len(records)-1,((2*j+1)*len(records))//(2*n))
            selection.append(records[position])
    inserted=rejected=0
    for old in selection:
        try:
            payload=fetcher("match",old["source_match_id"])
            rosters=payload.get("rosters") if isinstance(payload,dict) else None
            if not isinstance(rosters,dict):
                raise ValueError("Missing match roster")
            indexed={"id":old["source_match_id"],"league":old["league"],
                     "date":old["date"],"home":old["home"],"away":old["away"],
                     "hg":old["hg"],"ag":old["ag"]}
            for side,letter in (("home","h"),("away","a")):
                team_roster=rosters.get(letter)
                if not isinstance(team_roster,dict) or not team_roster:
                    raise ValueError("Missing source team identity")
                ids={str(p.get("team_id")) for p in team_roster.values()
                     if isinstance(p,dict)}
                if len(ids)!=1 or not re.fullmatch(r"[1-9][0-9]*",next(iter(ids))):
                    raise ValueError("Ambiguous source team")
                indexed[side+"_id"]=next(iter(ids))
            new=parse_creativity(indexed,payload,previous=old)
            db.query(f"INSERT OR IGNORE INTO {TABLE}(id,payload) VALUES(?,?)",
                     (new["id"],json.dumps(new,separators=(",",":"))))
            inserted+=1
        except AccessDenied:
            raise
        except (ValueError,TypeError,KeyError):
            rejected+=1
        sleeper(pause)
    progress={"status":"partial_enrichment" if len(known)+inserted<len(historical) else "complete",
             "historical_matches":len(historical),"enriched_total":len(known)+inserted,
             "added":inserted,"inspected":len(selection),"rejected":rejected,
             "private_only":True}
    db.query("INSERT OR REPLACE INTO metadata(k,v) VALUES(?,?)",
             ("understat_creativity_progress",json.dumps(progress,separators=(",",":"))))
    return progress


def main(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument("--max-new",type=int,default=100)
    p.add_argument("--pause",type=float,default=1.2)
    a=p.parse_args(argv)
    report=enrich(D1(),max_new=a.max_new,pause=a.pause)
    print(json.dumps(report,sort_keys=True))
    return report


if __name__=="__main__":main()
