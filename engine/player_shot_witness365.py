"""Per-player shot/xG witness for 365Scores match-level chartEvents.

Adapted from the original XGQ site's approach to game.members and team lineups,
but no arbitrary aggregation fallback: real per-shot XGQ is possible only from
verified individual xG for EVERY included shot.

Independently validate players' published "Total Shots"/"Expected Goals" rows
in game.members[].stats against their chart-event shots and summed xG.

No network, file storage, player metadata export, team-level xG relaxation or
implicit promotion occurs in this module.
"""
from __future__ import annotations

from collections import Counter,defaultdict
from decimal import Decimal,InvalidOperation
import math,re
from engine import provider365 as p
from engine.competition365 import resolve
from engine.xgq import normalized

MAX_DEPTH=12
MAX_NODES=16000
SHOT_KEYS=("playerId","memberId","athleteId","entityId","shooterId")
NESTED_PLAYER_KEYS=("player","member","athlete","shooter","shot")
STAT_NAMES={
    "total shots":"shots",
    "expected goals":"xg",
    "shots on target":"on_target",
    "shots off target":"off_target",
    "shots blocked":"blocked",
}

def _number(value,*,integer=False):
    if isinstance(value,bool):
        raise ValueError("player_stat_is_boolean")
    if type(value) not in (int,float,str):
        raise ValueError("player_stat_number_missing")
    v=str(value).strip()
    if not re.fullmatch(r"(?:\d{1,3})(?:\.\d{1,5})?",v):
        raise ValueError("player_stat_not_a_decimal")
    try:d=Decimal(v)
    except InvalidOperation:raise ValueError("player_stat_invalid_number") from None
    if not d.is_finite() or d<0 or d>150:
        raise ValueError("player_stat_out_of_bounds")
    if integer and d!=d.to_integral_value():
        raise ValueError("player_shot_count_nonintegral")
    precision=len(v.split(".")[1]) if "." in v else 0
    return (int(d) if integer else float(d)),precision


def player_stats(game):
    """A single factual player stat row per explicit player+side.

    Original 365Scores response includes .members[].{id,competitorId,stats}
    with stats:[{name,type,value}]. Traverse safely over known containers.
    Conflicting repeated rows fail closed. A player with zero shots and no
    Expected Goals may have xG=0, but a shooter without xG remains unknown.
    """
    home=p._side(game,"home");away=p._side(game,"away")
    ids={s:str(v.get("id") or v.get("competitorId") or "")
         for s,v in (("home",home),("away",away))}
    if not all(ids.values()) or ids["home"]==ids["away"]:
        raise ValueError("ambiguous_teams")
    owners={"home":{},"away":{}}
    visited=[0]
    def walk(node,depth=0):
        if depth>MAX_DEPTH:return
        visited[0]+=1
        if visited[0]>MAX_NODES:
            raise ValueError("player_statistics_too_many_nodes")
        if isinstance(node,list):
            for child in node[:250]:walk(child,depth+1)
            return
        if not isinstance(node,dict):return
        entries=node.get("stats")
        if isinstance(entries,list) and node.get("id") is not None and node.get("competitorId") is not None:
            pid=str(node["id"]);tid=str(node["competitorId"])
            side=next((s for s,i in ids.items() if i==tid),None)
            if side is not None:
                extracted={}
                for entry in entries:
                    if not isinstance(entry,dict):continue
                    name=entry.get("name")
                    if not isinstance(name,str):continue
                    field=STAT_NAMES.get(" ".join(name.lower().strip().split()))
                    if field is None:continue
                    if field in extracted:raise ValueError("duplicate_player_stat_"+field)
                    value,precision=_number(entry.get("value"),integer=field!="xg")
                    extracted[field]=value
                    if field=="xg":extracted["xg_precision"]=precision
                if "shots" in extracted:
                    if extracted["shots"]>35:raise ValueError("player_shots_out_of_range")
                    if "xg" in extracted and extracted["xg"]>extracted["shots"]+1e-8:
                        raise ValueError("player_xg_exceeds_shots")
                    if pid in owners[side] and owners[side][pid]!=extracted:
                        raise ValueError("conflicting_player_stat_owners")
                    owners[side][pid]=extracted
        for item in node.values():
            if isinstance(item,(list,dict)):
                walk(item,depth+1)
    for team in (home,away):walk(team)
    # Members frequently have player statistics outside team lineups.
    for key in ("members","lineups","players","statistics"):
        if key in game:walk(game[key])
    return owners


def _shooter(event,owners,side):
    other="home" if side=="away" else "away"
    keys=[]
    for key in SHOT_KEYS:
        if event.get(key) is not None:keys.append(str(event[key]))
    for key in NESTED_PLAYER_KEYS:
        node=event.get(key)
        if isinstance(node,dict):
            for k in ("id",)+SHOT_KEYS:
                if node.get(k) is not None:keys.append(str(node[k]))
    matching={k for k in keys if k in owners[side]}
    incompatible={k for k in keys if k in owners[other]}
    if incompatible and not matching:
        raise ValueError("chart_shooter_from_opposite_team")
    if len(matching)!=1 or (matching and incompatible):
        return None
    return next(iter(matching))


def _chart_side(event,home_id,away_id):
    comp=event.get("competitor") if isinstance(event.get("competitor"),dict) else {}
    team=event.get("team") if isinstance(event.get("team"),dict) else {}
    ids=[event.get(k) for k in ("competitorId","competitorID","teamId",
                                 "team_id","participantId","participantID")]
    ids+=[comp.get("id"),team.get("id")]
    direct={str(v) for v in ids if v is not None}
    if home_id in direct and away_id in direct:
        raise ValueError("chart_shot_has_two_team_ids")
    if home_id in direct:return "home"
    if away_id in direct:return "away"
    for field in ("competitorNum","competitorNumber","teamNum","teamNumber"):
        x=event.get(field)
        if x in (1,"1"):return "home"
        if x in (2,"2"):return "away"
    for key in ("isHome","isHomeCompetitor","isHomeTeam"):
        if type(event.get(key)) is bool:
            return "home" if event[key] else "away"
    return None


def individual_shots(game,owners):
    """Map observed individual shots to published player's stat rows."""
    h=p._side(game,"home");a=p._side(game,"away")
    homeid=str(h.get("id") or h.get("competitorId") or "")
    awayid=str(a.get("id") or a.get("competitorId") or "")
    chart=game.get("chartEvents") or game.get("chart_events")
    events=chart.get("events") or chart.get("chartEvents") or chart.get("items") if isinstance(chart,dict) else chart
    if not isinstance(events,list) or len(events)>500 or not events:
        raise ValueError("invalid_match_shot_chart")
    out={"home":defaultdict(list),"away":defaultdict(list)}
    unknown=Counter();total=Counter()
    for shot in events:
        if not isinstance(shot,dict):raise ValueError("malformed_shot_event")
        if not p._is_shot(shot):continue
        x=p._xg(shot)
        if x is None:raise ValueError("shot_without_valid_individual_xg")
        side=_chart_side(shot,homeid,awayid)
        if side is None:
            unknown["side"]+=1;continue
        total[side]+=1
        pid=_shooter(shot,owners,side)
        if pid is None:
            unknown["shooter_"+side]+=1;continue
        outcome=shot.get("outcome")
        if isinstance(outcome,dict):outcome=outcome.get("name")
        out[side][pid].append({"xg":x,"outcome":str(outcome or "").strip().lower()})
    return out,dict(total),dict(unknown)


def _near(player_sum,player_stat,observed_n,shot_precision=2):
    decimals=player_stat.get("xg_precision")
    if not isinstance(decimals,int) or decimals<0 or decimals>5:return False
    tolerance=observed_n*.5*10**(-shot_precision)+.5*10**(-decimals)+1e-9
    return abs(player_sum-player_stat["xg"])<=tolerance


def compare_players(game,independent):
    """Return private, per-player evidence and aggregate-safe status.

    This does NOT authorize releasing a match when team-level xG differs:
    it provides an independent alternative witness for investigation.
    """
    owners=player_stats(game)
    seen,total,unknown=individual_shots(game,owners)
    sides={}
    aggregate={"stats_players":0,"shooting_players":0,"players_missing_xg":0,
               "players_with_shot_gap":0,"players_with_xg_gap":0,
               "unmapped_shots":sum(unknown.values()),"stats_shots_sum_diff":{}}
    for side in ("home","away"):
        if not owners[side]:raise ValueError("no_player_stats_for_"+side)
        gaps=[]
        good=0;missing_xg=0;xg_mismatch=0
        claimed=sum(rec["shots"] for rec in owners[side].values())
        official=independent[side]["shots"]
        by_player={}
        for pid,v in owners[side].items():
            xs=seen[side].get(pid,[])
            has_xg="xg" in v
            diff=len(xs)-v["shots"]
            if diff:gaps.append((pid,diff))
            if v["shots"]>0 and not has_xg:missing_xg+=1
            elif has_xg and not _near(sum(z["xg"] for z in xs),v,len(xs)):
                xg_mismatch+=1
            else:good+=1
            by_player[pid]={"chart_count":len(xs),"stats_count":v["shots"],
                            "chart_sum_xg":sum(z["xg"] for z in xs),
                            "stats_sum_xg":v.get("xg"),
                            "stats_xg_precision":v.get("xg_precision"),
                            "shot_events":xs,
                            "on_target_stats":v.get("on_target"),
                            "off_target_stats":v.get("off_target"),
                            "blocked_stats":v.get("blocked")}
        sides[side]={"chart_shots_total":total.get(side,0),
                     "stat_shots_total":claimed,
                     "independent_team_shots":official,
                     "player_stats_vs_team_count_equal":claimed==official,
                     "player_count":len(owners[side]),
                     "shooters_count":sum(1 for v in owners[side].values() if v["shots"]>0),
                     "player_count_mismatch":len(gaps),
                     "player_xg_missing":missing_xg,
                     "player_xg_mismatch":xg_mismatch,
                     "players_all_shots_match":not gaps and claimed==official,
                     "players_all_xg_match":xg_mismatch==0 and missing_xg==0,
                     "gaps":gaps,
                     "members":by_player}
        aggregate["stats_players"]+=len(owners[side])
        aggregate["shooting_players"]+=sides[side]["shooters_count"]
        aggregate["players_missing_xg"]+=missing_xg
        aggregate["players_with_shot_gap"]+=len(gaps)
        aggregate["players_with_xg_gap"]+=xg_mismatch
        aggregate["stats_shots_sum_diff"][side]=claimed-official
    # Team totals, individual chart and each shooting player must independently match.
    full_player_evidence=(
        aggregate["unmapped_shots"]==0 and
        all(sides[s]["players_all_shots_match"] and sides[s]["players_all_xg_match"]
            and sides[s]["chart_shots_total"]==independent[s]["shots"]
            for s in ("home","away"))
    )
    return {"player_evidence_complete":full_player_evidence,"by_side":sides,
            "aggregate":aggregate,"unknown":unknown}
