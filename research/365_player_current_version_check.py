"""Recheck ONE current chart that every PLAYER confirms but differs from old archive.

The old candidate snapshot stays immutable. A previously verified player
reconciliation may disagree with the first cached chart xG sum (could be a
later source revision OR a normalization issue; do not assume which).

Fetch just that ONE known match ID again; recompute exact XGQ from current
individual shots, independently match every player's published Total Shots
and Expected Goals and the OFFICIAL team Total Shots, and save to a separate
player-source-witness tier. Preserve contradictory team aggregate xG and
training_release=False. All provider match/player data stays in private D1.
"""
from __future__ import annotations
import importlib,json,time,math
from pathlib import Path
from engine import provider365 as p
from engine.player_shot_witness365 import compare_players
from engine.understat_d1 import D1,D1Error
from engine.xgq import normalized

old=importlib.import_module("research.365_original_ingestion_comparison")
audit=importlib.import_module("research.365_eight_player_witness")
base=importlib.import_module("research.365_stats_completeness_batch")
OUT=Path("research/reports/365_player_current_version_check.json")


def candidate_sides_recheck(candidate,game,stats):
    proof=compare_players(game,stats)
    if proof["player_evidence_complete"] is not True:
        raise ValueError("individual_player_xg_or_shots_not_complete")
    recalculated={}
    changed_sides=[]
    for side in ("home","away"):
        allshots=[v["xg"] for m in proof["by_side"][side]["members"].values()
                  for v in m["shot_events"]]
        if not allshots:raise ValueError("no_player_shot_events")
        if len(allshots)!=candidate[side+"_chart_shots"] or len(allshots)!=stats[side]["shots"]:
            raise ValueError("shot_counts_changed")
        v=sum(allshots)
        if abs(v-candidate[side+"_chart_xg_sum"])>1e-6:
            changed_sides.append(side)
        recalculated[side]={"xg":round(v,6),"shots":len(allshots),
                           "xgq":round(sum(x*x for x in allshots)/len(allshots),8)}
    if not changed_sides:
        raise ValueError("no_original_chart_discrepancy")
    return recalculated,tuple(changed_sides)


def run(*,db=None,fetch=None):
    d=db if db is not None else D1()
    remaining=old.unresolved(d)
    witnessed=d.query("SELECT id,payload FROM private_365_player_witness ORDER BY id LIMIT 50")
    proofrows={str(x["id"]):json.loads(x["payload"]) for x in witnessed}
    selected=[]
    for mid,candidate in remaining.items():
        pv=proofrows.get(mid)
        if pv is None or pv.get("player_evidence_complete") is not True:continue
        mismatch=False
        for side in ("home","away"):
            v=pv["by_side"][side]
            total=sum(q["chart_sum_xg"] for q in v["members"].values())
            if abs(total-candidate[side+"_chart_xg_sum"])>1e-6:
                mismatch=True
        if mismatch:selected.append(mid)
    if len(selected)!=1:
        raise ValueError("expected_one_original_vs_current_chart_conflict")
    mid=selected[0];candidate=remaining[mid]
    state={"original_variant_cases":1,"provider_requests":0,
           "reverified_current_chart":0,"private_research_saved":0,
           "official_team_xg_disagreement_preserved":True,
           "original_candidates_mutated":False,"original_rejection_audits_mutated":False,
           "training_release":False,"private_match_rows_published":0,
           "public_player_identifiers":False,"raw_shots_written":False,
           "status":"not_started"}
    source=d.query("SELECT payload FROM private_365_rejected_diagnosis WHERE id=?",(mid,))
    if len(source)!=1:raise ValueError("original_independent_team_stats_missing")
    witness=json.loads(source[0]["payload"])["source_stats"]
    getter=fetch if fetch is not None else lambda x:p.fetch(
        "game/",{"gameId":x,"topBookmaker":"14"})
    state["provider_requests"]=1
    payload=getter(mid)
    game=audit.validate(payload,candidate,mid)
    try:
        totals,changed=candidate_sides_recheck(candidate,game,witness)
    except (ValueError,TypeError,KeyError) as exc:
        state["status"]="source_data_not_reconciled"
        state["reason_type"]=type(exc).__name__
        return state
    d.query("""CREATE TABLE IF NOT EXISTS private_365_research_player_verified(
        id TEXT PRIMARY KEY NOT NULL,payload TEXT NOT NULL)""")
    row={
      "id":f"{candidate['league']}|{candidate['date']}|{normalized(candidate['home'])}|{normalized(candidate['away'])}",
      "source_match_id":mid,
      "league":candidate["league"],"date":candidate["date"],
      "home":candidate["home"],"away":candidate["away"],
      "h":normalized(candidate["home"]),"a":normalized(candidate["away"]),
      "hg":candidate["hg"],"ag":candidate["ag"],
      "home_xg":totals["home"]["xg"],"away_xg":totals["away"]["xg"],
      "home_xgq":totals["home"]["xgq"],"away_xgq":totals["away"]["xgq"],
      "home_shots":totals["home"]["shots"],"away_shots":totals["away"]["shots"],
      "source":"365Scores (opt-in; rights required)",
      "proof_tier":"CURRENT_FULL_PLAYER_WITNESS_OLD_CANDIDATE_DIFFERS",
      "full_player_counts_and_xg_match":True,
      "official_team_shot_counts_match":True,
      "official_team_xg_conflicts":True,
      "original_chart_summary_differs":True,
      "original_chart_discrepancy_sides":changed,
      "training_release":False}
    d.query("INSERT OR REPLACE INTO private_365_research_player_verified(id,payload) VALUES(?,?)",
            (row["id"],json.dumps(row,ensure_ascii=False,separators=(",",":"))))
    count=d.query("SELECT COUNT(*) AS n FROM private_365_research_player_verified")
    state["status"]="current_player_source_reverified"
    state["reverified_current_chart"]=1
    state["private_research_saved"]=1
    state["private_player_evidence_archive_total"]=int(count[0]["n"])
    return state


def main():
    try:s=run()
    except (D1Error,ValueError,TypeError,KeyError) as e:
        s={"status":"fail_closed","error_type":type(e).__name__,
           "provider_requests":0,"private_research_saved":0,
           "original_candidates_mutated":False,
           "original_rejection_audits_mutated":False,
           "official_team_xg_disagreement_preserved":True,
           "training_release":False,"private_match_rows_published":0,
           "public_player_identifiers":False,"raw_shots_written":False}
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(s,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print(json.dumps(s,ensure_ascii=False))
    return s

if __name__=="__main__":main()
