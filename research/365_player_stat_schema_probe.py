"""One bounded, private schema probe for player-specific 365Scores match statistics.

The original site allam775/xgq-project-365/server.py walks lineups and
game.members; this checks whether player shot counts / xG are actually
available in those arrays, instead of assuming team aggregates suffice.

Exactly ONE already known unresolved match game/ request (max 1). Public
output is taxonomy only: NEVER player names/IDs, per-player values, match
IDs, raw events, provider payload or individual xG.
"""
from __future__ import annotations
from collections import Counter
import importlib
import json
from pathlib import Path
from engine import provider365 as p
from engine.understat_d1 import D1, D1Error
from engine.competition365 import resolve
from engine.xgq import normalized

original=importlib.import_module("research.365_original_ingestion_comparison")
OUT=Path("research/reports/365_player_stat_schema.json")
MAX_NODES=15000
MAX_DEPTH=12
KNOWN_STAT_KEYS={
    "statistics","playerStatistics","playerStats","stats","items",
    "stat","statValue","value","totalShots","shots","shotsOnTarget",
    "shotsOffTarget","shotsBlocked","blockedShots","xg","xG",
    "expectedGoals","expectedGoalsValue","expectedGoal","expected_goals",
    "shotAttempts","shotsTotal","shotsOnGoal","member","memberId",
    "player","playerId","athleteId","type","name","title","label",
    "competitorId","entityId","isHome","away","home","lineups",
    "members","players","formations","groups","categories",
}
STAT_WORDS=("shot","goal","xg","attempt","block","target","chance")

def _safe_label(value):
    # Only statistic metric labels (never player names or match metadata).
    if not isinstance(value,str):return None
    cleaned=value.strip().lower()
    if len(cleaned)>75 or len(cleaned)<2:return None
    if not any(s in cleaned for s in STAT_WORDS):return None
    if any(q in cleaned for q in ("/","http","www","@","#")):return None
    return cleaned

def profile(payload):
    if not isinstance(payload,dict):raise ValueError("game_payload_invalid")
    game=payload.get("game",payload)
    if not isinstance(game,dict):raise ValueError("game_missing")
    team_nodes=[p._side(game,"home"),p._side(game,"away")]
    counters=Counter()
    names=Counter()
    keys=Counter()
    examples=Counter()
    owners=Counter()
    sample_stat_shapes=Counter()
    coverage=Counter()
    def walk(node,context="",depth=0):
        if depth>MAX_DEPTH or counters["nodes"]>=MAX_NODES:return
        counters["nodes"]+=1
        if isinstance(node,list):
            if any(isinstance(x,dict) for x in node):
                counters["lists_of_objects"]+=1
            for child in node[:250]:walk(child,context,depth+1)
            return
        if not isinstance(node,dict):return
        for k in node:
            if k in KNOWN_STAT_KEYS:keys[k]+=1
        if "player" in node and isinstance(node["player"],dict):
            counters["player_objects"]+=1
        if "member" in node and isinstance(node["member"],dict):
            counters["member_objects"]+=1
        if any(k in node for k in ("playerId","memberId","athleteId")):
            counters["explicit_player_id_nodes"]+=1
        if any(k in node for k in ("statistics","playerStatistics","playerStats","stats")):
            counters["stats_containing_nodes"]+=1
            for key in ("statistics","playerStatistics","playerStats","stats"):
                statsv=node.get(key)
                if isinstance(statsv,(list,dict)):
                    keys_present=",".join(k for k in ("id","athleteId","playerId",
                        "memberId","competitorId","player","member","name","teamId")
                        if k in node)
                    owners[key+":"+type(statsv).__name__+":owner="+keys_present]+=1
                    rows=statsv if isinstance(statsv,list) else [statsv]
                    statnames=set()
                    for item in rows[:150]:
                        if isinstance(item,dict):
                            sample_stat_shapes[",".join(sorted(k for k in item if k in (
                                "name","label","type","key","value","stat","displayValue",
                                "title","stats","items","groups","athleteId","playerId")))] += 1
                            for kk in ("name","label","type","title"):
                                lbl=_safe_label(item.get(kk))
                                if lbl:statnames.add(lbl)
                    coverage["stat_container_with_total_shots"]+=int("total shots" in statnames)
                    coverage["stat_container_with_expected_goals"]+=int("expected goals" in statnames)
                    coverage["stat_container_with_both"]+=int(
                        "total shots" in statnames and "expected goals" in statnames)
        directstat = {k for k in node if k in (
            "shots","totalShots","shotsOnTarget","shotsOffTarget",
            "shotsBlocked","xg","xG","expectedGoals","expectedGoal",
            "expected_goals")}
        if directstat:
            counters["direct_stat_nodes"]+=1
            for k in directstat:examples[k]+=1
        if isinstance(node.get("name"),str):
            # Names of statistics ONLY when parent is specifically a stats container.
            if context in ("statistics","playerStatistics","playerStats","stats","items","groups","categories"):
                label=_safe_label(node["name"])
                if label:names[label]+=1
        for k,v in node.items():
            if isinstance(v,(dict,list)):
                walk(v,k,depth+1)
    for side in team_nodes:walk(side,"lineups",0)
    # Some member statistics are stored at game root, outside team nodes.
    for k in ("members","lineups","playerStatistics","statistics","players"):
        if k in game:walk(game[k],k,0)
    return {
        "nodes_inspected":counters["nodes"],
        "container_counts":{k:v for k,v in counters.items() if k!="nodes"},
        "stat_metric_field_occurrences":dict(sorted(examples.items())),
        "stat_container_keys":dict(sorted(keys.items())),
        "recognized_metric_labels":dict(sorted(names.items())),
        "stat_owner_shapes":dict(sorted(owners.items())),
        "stat_row_shapes":dict(sorted(sample_stat_shapes.items())),
        "stat_field_coverage":dict(sorted(coverage.items())),
    }

def main():
    state={"kind":"single_365scores_player_stats_schema",
           "request_cap":1,"provider_requests":0,
           "source":"365Scores","player_identifiers_published":0,
           "individual_player_stats_published":0,
           "match_identifiers_published":0,
           "raw_events_published":0,
           "match_promotions":0,"status":"not_started"}
    try:
        d=D1()
        remaining=original.unresolved(d)
        mid=sorted(remaining)[0]
        state["provider_requests"]=1
        payload=p.fetch("game/",{"gameId":mid,"topBookmaker":"14"})
        obj=payload.get("game",payload)
        if p._game_id(obj)!=mid or not p._final(obj):
            raise ValueError("match_id_or_status_mismatch")
        expected=remaining[mid]
        identity=resolve(payload)
        if not identity["ok"] or identity["league"]!=expected["league"]:
            raise ValueError("league_identity_mismatch")
        if p._date(obj)!=expected["date"]:
            raise ValueError("match_date_mismatch")
        for side in ("home","away"):
            item=p._side(obj,side)
            if normalized(item.get("name"))!=normalized(expected[side]):
                raise ValueError("team_identity_mismatch")
        state["taxonomy"]=profile(payload)
        state["status"]="schema_confirmed"
    except (p.AccessDenied,D1Error,ValueError,KeyError,TypeError) as e:
        state["status"]="unavailable"
        state["reason_type"]=type(e).__name__
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(state,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print(json.dumps(state,ensure_ascii=False))
    return state

if __name__=="__main__":main()
