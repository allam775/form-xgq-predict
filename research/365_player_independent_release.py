"""Private alternate proof for XGQ when 365Scores team xG conflicts with player sums.

Original 365Scores match-page Total Shots, chart shot XGQ, and every individual
player's independent Total Shots / Expected Goals agree. The separate team xG
aggregate disagrees, so preserve BOTH conflicting measures and explicitly
record proof tier 'PLAYER_INDEPENDENT_WITH_TEAM_XG_CONFLICT'.

This is not the same as fully team-stat-verified evidence. It cannot be moved
to the ordinary 365Scores verified table or training automatically.
"""
from __future__ import annotations
import importlib,json,math
from pathlib import Path
from collections import Counter

from engine.understat_d1 import D1,D1Error
from engine.xgq import normalized

base=importlib.import_module("research.365_stats_completeness_batch")
original=importlib.import_module("research.365_original_ingestion_comparison")
OUT=Path("research/reports/365_player_independent_release.json")


def proof(candidate,old_audit,independent,player):
    if old_audit.get("complete") is not False or old_audit.get("status") not in (
        "home_xg_mismatch","away_xg_mismatch"):
        raise ValueError("not_original_same_shot_count_xg_conflict")
    if (candidate.get("catalog_verified") is not True or
        candidate.get("eligible_for_forecast") is not False or
        candidate.get("completeness")!="NOT_VERIFIED_INDEPENDENT_TOTALS"):
        raise ValueError("invalid_original_provisional_candidate")
    if player.get("player_evidence_complete") is not True:
        raise ValueError("individual_player_witness_incomplete")
    if player.get("aggregate",{}).get("unmapped_shots")!=0:
        raise ValueError("unmapped_player_shots")
    if player.get("aggregate",{}).get("players_missing_xg")!=0:
        raise ValueError("missing_published_player_xg")
    for side in ("home","away"):
        st=independent[side]
        evidence=player["by_side"][side]
        count=candidate[side+"_chart_shots"]
        if (evidence["chart_shots_total"]!=count or
            evidence["stat_shots_total"]!=count or
            evidence["independent_team_shots"]!=count or
            st["shots"]!=count or
            evidence.get("players_all_shots_match") is not True or
            evidence.get("players_all_xg_match") is not True):
            raise ValueError("player_and_team_shot_count_mismatch")
        if evidence.get("player_count_mismatch") or evidence.get("player_xg_mismatch") or evidence.get("player_xg_missing"):
            raise ValueError("some_player_stat_unreconciled")
        members=evidence["members"]
        if not members:raise ValueError("no_independent_player_statistics")
        actual_n=sum(v["chart_count"] for v in members.values())
        actual_sum=sum(v["chart_sum_xg"] for v in members.values())
        if actual_n!=count or abs(actual_sum-candidate[side+"_chart_xg_sum"])>1e-6:
            raise ValueError("private_shot_original_mismatch")
        for rec in members.values():
            xg=rec.get("stats_sum_xg")
            n=rec["chart_count"]
            if n>0 and (type(xg) not in (int,float) or
                        not math.isfinite(xg)):
                raise ValueError("shooter_missing_independent_xg")
            if rec["chart_count"]!=rec["stats_count"]:
                raise ValueError("player_shot_count_mismatch")
            if xg is not None:
                prec=rec["stats_xg_precision"]
                if type(prec) is not int or not 0<=prec<=5:
                    raise ValueError("player_stat_xg_precision_missing")
                tol=.005*n+.5*10**(-prec)+1e-9
                if abs(rec["chart_sum_xg"]-xg)>tol:
                    raise ValueError("player_xg_total_mismatch")
    return True


def export_private(*,db=None):
    d=db if db is not None else D1()
    unresolved=original.unresolved(d)
    audit=base.prior_audits(d)
    raw=d.query("SELECT id,payload FROM private_365_player_witness ORDER BY id LIMIT 50")
    records={str(r["id"]):json.loads(r["payload"]) for r in raw}
    d.query("""CREATE TABLE IF NOT EXISTS private_365_research_player_verified(
        id TEXT PRIMARY KEY NOT NULL,payload TEXT NOT NULL)""")
    before=d.query("SELECT COUNT(*) AS n FROM private_365_research_player_verified")
    start=int(before[0]["n"])
    accepted=Counter();rejected=Counter()
    for mid,c in unresolved.items():
        player=records.get(mid)
        if not player or player.get("player_evidence_complete") is not True:
            rejected["incomplete_player_witness"]+=1;continue
        evidence=d.query("SELECT payload FROM private_365_rejected_diagnosis WHERE id=?",(mid,))
        if len(evidence)!=1:
            rejected["missing_official_stat_snapshot"]+=1;continue
        independent=json.loads(evidence[0]["payload"])["source_stats"]
        try:
            proof(c,audit[mid],independent,player)
        except (ValueError,KeyError,TypeError) as exc:
            rejected[str(exc)[:70]]+=1;continue
        row={
            "id":f"{c['league']}|{c['date']}|{normalized(c['home'])}|{normalized(c['away'])}",
            "date":c["date"],"league":c["league"],
            "home":c["home"],"away":c["away"],
            "h":normalized(c["home"]),"a":normalized(c["away"]),
            "hg":c["hg"],"ag":c["ag"],
            "home_xg":c["home_chart_xg_sum"],
            "away_xg":c["away_chart_xg_sum"],
            "home_xgq":c["home_provisional_xgq"],
            "away_xgq":c["away_provisional_xgq"],
            "home_shots":c["home_chart_shots"],
            "away_shots":c["away_chart_shots"],
            "source":"365Scores (opt-in; rights required)",
            "source_match_id":mid,
            "proof_tier":"PLAYER_INDEPENDENT_WITH_TEAM_XG_CONFLICT",
            "individual_player_shot_count_verified":True,
            "individual_player_xg_sum_verified":True,
            "official_team_shots_match":True,
            "official_team_xg_conflicts":True,
            "original_audit_preserved":True,
            "training_release":False
        }
        d.query("INSERT OR REPLACE INTO private_365_research_player_verified(id,payload) VALUES(?,?)",
                (row["id"],json.dumps(row,separators=(",",":"),ensure_ascii=False)))
        accepted[c["league"]]+=1
    after=d.query("SELECT COUNT(*) AS n FROM private_365_research_player_verified")
    return {"kind":"365scores_alternative_player_evidence",
            "original_eight":len(unresolved),"approved_player_evidence":sum(accepted.values()),
            "new_private_rows":int(after[0]["n"])-start,
            "private_total_player_verified":int(after[0]["n"]),
            "by_competition":dict(sorted(accepted.items())),
            "unresolved_or_disputed":sum(rejected.values()),
            "unresolved_reasons":dict(sorted(rejected.items())),
            "ordinary_fully_verified_archive_changed":False,
            "original_match_audits_changed":False,
            "training_release":False,"provider_requests":0,
            "raw_shot_events_exported":False,
            "public_player_identifiers":False,
            "private_match_rows_published":0}


def main():
    try:r=export_private();r["status"]="complete"
    except (D1Error,ValueError,TypeError,KeyError) as exc:
        r={"status":"fail_closed","reason_type":type(exc).__name__,
           "provider_requests":0,"training_release":False,
           "ordinary_fully_verified_archive_changed":False,
           "raw_shot_events_exported":False,"public_player_identifiers":False,
           "private_match_rows_published":0}
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(r,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print(json.dumps(r,ensure_ascii=False))
    return r

if __name__=="__main__":main()
