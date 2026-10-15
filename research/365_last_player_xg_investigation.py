"""Last of eight: test explicitly present alternate per-shot xG against player stats.

Exactly one previously rejected 365Scores match ID, one documented game/
request. Do not infer xG from player aggregates, guess player identity or
promote unless both sides' official xG and per-player totals reconcile.
Keep provider event data private and original failed audit untouched.
"""
from __future__ import annotations
from pathlib import Path
from collections import Counter
import importlib,json
from engine import provider365 as p
from engine.alternate_player_shot_xg365 import repair,repair_two_players
from engine.understat_d1 import D1,D1Error
from engine.xgq import normalized

original=importlib.import_module("research.365_original_ingestion_comparison")
player=importlib.import_module("research.365_eight_player_witness")
OUT=Path("research/reports/365_last_player_xg_investigation.json")

def attempt(*,db=None,fetch=None):
    d=db if db is not None else D1()
    rem=original.unresolved(d)
    observed=d.query("SELECT id,payload FROM private_365_player_witness ORDER BY id LIMIT 50")
    records={str(r["id"]):json.loads(r["payload"]) for r in observed}
    candidate_ids=[]
    for mid,row in rem.items():
        pv=records.get(mid)
        if not pv or pv.get("player_evidence_complete") is True:continue
        if pv.get("aggregate",{}).get("unmapped_shots"):continue
        if pv.get("aggregate",{}).get("players_with_shot_gap"):continue
        if pv.get("aggregate",{}).get("players_with_xg_gap",0)>0:
            candidate_ids.append(mid)
    if len(candidate_ids)!=1:
        # Most important: DO NOT mislabel a team-vs-player count mismatch as
        # an xG-only problem. No source request is made for an ineligible case.
        signatures={}
        for mid,pv in records.items():
            if mid not in rem or pv.get("player_evidence_complete") is True:
                continue
            if pv.get("extra_shot_isolatable_to_one_player") is True:
                continue
            agg=pv.get("aggregate",{})
            kind=("missing_shooter" if agg.get("unmapped_shots") else
                  "individual_shot_gap" if agg.get("players_with_shot_gap") else
                  "individual_xg_gap" if agg.get("players_with_xg_gap") else
                  "player_vs_team_total_count_or_chart_disagreement")
            signatures[kind]=signatures.get(kind,0)+1
        return {"status":"not_eligible_for_alternate_shot_xg_test",
                "original_remaining_cases":len(rem),
                "eligible_xg_only_player_conflicts":len(candidate_ids),
                "other_issues":signatures,
                "provider_requests":0,"strict_xg_repaired":0,
                "training_release":False,"original_audit_preserved":True,
                "raw_events_written":False,"public_player_identifiers":False,
                "public_match_identifiers":False}
    mid=candidate_ids[0];row=rem[mid]
    discrepant_players=int(records[mid]["aggregate"]["players_with_xg_gap"])
    d.query("""CREATE TABLE IF NOT EXISTS private_365_last_xg_investigation(
        id TEXT PRIMARY KEY NOT NULL,payload TEXT NOT NULL)""")
    previous=d.query("SELECT payload FROM private_365_last_xg_investigation WHERE id=?",(mid,))
    if previous and json.loads(previous[0]["payload"]).get("algorithm_version")==2:
        known=json.loads(previous[0]["payload"])
        return {"original_last_cases":1,"provider_requests":0,"already_checked":1,
                "strict_xg_repaired":int(known["ok"]),"reason":known["status"],
                "training_release":False,"original_audit_preserved":True,
                "raw_events_written":False,"public_player_identifiers":False,
                "public_match_identifiers":False,"status":"cached"}
    ind=d.query("SELECT payload FROM private_365_rejected_diagnosis WHERE id=?",(mid,))
    orig=d.query("SELECT payload FROM private_365_stats_audit WHERE id=?",(mid,))
    if len(ind)!=1 or len(orig)!=1:
        raise ValueError("original_private_independent_evidence_missing")
    stats=json.loads(ind[0]["payload"])["source_stats"]
    old=json.loads(orig[0]["payload"])
    get=fetch if fetch is not None else lambda mid:p.fetch(
        "game/",{"gameId":mid,"topBookmaker":"14"})
    detail=get(mid)
    game=player.validate(detail,row,mid)
    outcome=repair(row,game,stats,old)
    if not outcome["ok"] and outcome["reason"]=="not_one_isolated_player_xg_conflict":
        outcome=repair_two_players(row,game,stats,old)
    d.query("INSERT OR REPLACE INTO private_365_last_xg_investigation(id,payload) VALUES(?,?)",
            (mid,json.dumps({"ok":outcome["ok"],"status":outcome["reason"],"algorithm_version":2},
                            separators=(",",":"))))
    if outcome["ok"]:
        approved=outcome["private_row"]
        approved["id"]=f"{approved['league']}|{approved['date']}|{normalized(approved['home'])}|{normalized(approved['away'])}"
        approved["h"]=normalized(approved["home"])
        approved["a"]=normalized(approved["away"])
        d.query("INSERT OR REPLACE INTO private_365_research_verified(id,payload) VALUES(?,?)",
                (approved["id"],json.dumps(approved,separators=(",",":"),ensure_ascii=False)))
    totals=d.query("SELECT COUNT(*) AS n FROM private_365_research_verified")
    return {"original_last_cases":1,"provider_requests":1,"already_checked":0,
            "independent_player_xg_conflicts":discrepant_players,
            "explicit_alternative_counts":outcome.get("explicit_alternative_counts",[]),
            "strict_xg_repaired":int(outcome["ok"]),"reason":outcome["reason"],
            "strict_private_research_total":int(totals[0]["n"]),
            "training_release":False,"original_audit_preserved":True,
            "raw_events_written":False,"public_player_identifiers":False,
            "public_match_identifiers":False,"status":"completed"}

def main():
    try:v=attempt()
    except (D1Error,ValueError,KeyError,TypeError) as e:
        v={"status":"fail_closed","reason_type":type(e).__name__,
           "provider_requests":0,"strict_xg_repaired":0,
           "training_release":False,"original_audit_preserved":True,
           "raw_events_written":False,"public_player_identifiers":False,
           "public_match_identifiers":False}
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(v,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print(json.dumps(v,ensure_ascii=False))
    return v

if __name__=="__main__":main()
