"""Diagnose the eight unresolved 365Scores matches using each player's own stats.

One already known game/ request per private match (maximum 8).
All player IDs, match IDs, xG values and detailed evidence remain in private
Cloudflare D1. GitHub receives counts only. No raw events or model changes.
"""
from __future__ import annotations
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path
from urllib.error import HTTPError,URLError
import importlib,json,time

from engine import provider365 as p
from engine.competition365 import resolve
from engine.player_shot_witness365 import compare_players
from engine.understat_d1 import D1,D1Error
from engine.xgq import normalized

original=importlib.import_module("research.365_original_ingestion_comparison")
OUT=Path("research/reports/365_eight_player_witness.json")
MAX_REQUESTS=8

def validate(payload,row,mid):
    game=payload.get("game",payload) if isinstance(payload,dict) else None
    if not isinstance(game,dict) or p._game_id(game)!=mid or not p._final(game):
        raise ValueError("match_id_or_final_status_disagrees")
    identity=resolve(payload)
    if not identity["ok"] or identity["league"]!=row["league"] or (
        identity["provider_competition_id"]!=row["competition_id"]):
        raise ValueError("league_or_competition_identity_disagrees")
    if p._date(game)!=row["date"]:raise ValueError("match_date_disagrees")
    for side in ("home","away"):
        actual=p._side(game,side)
        if normalized(actual.get("name"))!=normalized(row[side]):
            raise ValueError("team_identity_disagrees")
        if p._score(game,side,actual)!=row["hg" if side=="home" else "ag"]:
            raise ValueError("score_disagrees")
    return game

def isolated_extra_shooter(evidence,witness):
    """Exactly one player has one surplus chart shot; no shot is yet deleted."""
    sides=evidence["by_side"]
    if evidence["aggregate"]["unmapped_shots"]:
        return False
    if evidence["aggregate"]["stats_shots_sum_diff"]!={"home":0,"away":0}:
        return False
    problem=[]
    for side in ("home","away"):
        gaps=sides[side]["gaps"]
        if not gaps:continue
        if len(gaps)!=1 or gaps[0][1]!=1:return False
        problem.append(side)
    return len(problem)==1 and all(sides[s]["stat_shots_total"]==witness[s]["shots"]
                                   for s in ("home","away"))

def private_projection(result):
    """Drop per-shot records before private persistence."""
    by_side={}
    for side in ("home","away"):
        rec=result["by_side"][side]
        members={}
        for pid,v in rec["members"].items():
            members[pid]={k:v[k] for k in (
                "chart_count","stats_count","chart_sum_xg","stats_sum_xg",
                "stats_xg_precision","on_target_stats","off_target_stats",
                "blocked_stats")}
        by_side[side]={k:v for k,v in rec.items() if k!="members"}
        by_side[side]["members"]=members
    return {"player_evidence_complete":result["player_evidence_complete"],
            "by_side":by_side,"aggregate":result["aggregate"],
            "unknown":result["unknown"],
            "checked_at":datetime.now(timezone.utc).isoformat()}

def audit(*,db=None,fetch=None,limit=MAX_REQUESTS,delay=1.5):
    if type(limit) is not int or not 1<=limit<=MAX_REQUESTS or delay<0:
        raise ValueError("unsafe_player_match_request_limit")
    d=db if db is not None else D1()
    remaining=original.unresolved(d)
    d.query("""CREATE TABLE IF NOT EXISTS private_365_player_witness(
        id TEXT PRIMARY KEY NOT NULL,payload TEXT NOT NULL)""")
    known={str(v["id"]) for v in d.query(
        "SELECT id FROM private_365_player_witness ORDER BY id LIMIT 50")}
    getter=fetch if fetch is not None else lambda mid:p.fetch(
        "game/",{"gameId":mid,"topBookmaker":"14"})
    report={"kind":"eight_365scores_player_stats_differential",
            "original_unresolved":len(remaining),
            "request_cap":limit,"provider_requests":0,
            "previously_diagnosed":0,"new_cases_diagnosed":0,
            "cases_with_all_player_shots_and_xg_verified":0,
            "cases_where_player_only_evidence_conflicts_with_team_total":0,
            "extra_shot_isolatable_to_one_player":0,
            "cases_with_player_shot_count_differences":0,
            "cases_with_player_xg_differences":0,
            "cases_with_player_xg_missing":0,
            "cases_with_unmapped_shooter":0,
            "error_reasons":{},
            "player_id_public":False,"individual_xg_public":False,
            "provider_match_id_public":False,"raw_shots_written":False,
            "match_promotions":0,"training_modified":False,
            "status":"complete"}
    errors=Counter()
    for mid,row in sorted(remaining.items()):
        if mid in known:
            report["previously_diagnosed"]+=1
            continue
        if report["provider_requests"]>=limit:
            report["status"]="request_budget_reached";break
        try:
            source=d.query("SELECT payload FROM private_365_rejected_diagnosis WHERE id=?",(mid,))
            if len(source)!=1:raise ValueError("private_stats_witness_missing")
            stats=json.loads(source[0]["payload"])["source_stats"]
            report["provider_requests"]+=1
            payload=getter(mid)
            game=validate(payload,row,mid)
            evidence=compare_players(game,stats)
            prior=d.query("SELECT payload FROM private_365_stats_audit WHERE id=?",(mid,))
            reason=json.loads(prior[0]["payload"]).get("status","unknown") if len(prior)==1 else "unknown"
            isolated=isolated_extra_shooter(evidence,stats)
            saved=private_projection(evidence)
            saved["original_reason"]=reason
            saved["extra_shot_isolatable_to_one_player"]=isolated
            d.query("INSERT OR REPLACE INTO private_365_player_witness(id,payload) VALUES(?,?)",
                    (mid,json.dumps(saved,ensure_ascii=False,separators=(",",":"))))
            report["new_cases_diagnosed"]+=1
            report["cases_with_all_player_shots_and_xg_verified"]+=int(
                evidence["player_evidence_complete"])
            report["cases_where_player_only_evidence_conflicts_with_team_total"]+=int(
                evidence["player_evidence_complete"] and reason.endswith("_xg_mismatch"))
            report["extra_shot_isolatable_to_one_player"]+=int(isolated)
            report["cases_with_player_shot_count_differences"]+=int(
                evidence["aggregate"]["players_with_shot_gap"]>0)
            report["cases_with_player_xg_differences"]+=int(
                evidence["aggregate"]["players_with_xg_gap"]>0)
            report["cases_with_player_xg_missing"]+=int(
                evidence["aggregate"]["players_missing_xg"]>0)
            report["cases_with_unmapped_shooter"]+=int(
                evidence["aggregate"]["unmapped_shots"]>0)
        except (p.AccessDenied,HTTPError) as exc:
            errors[type(exc).__name__]+=1
            if isinstance(exc,p.AccessDenied) or getattr(exc,"code",0) in (401,403,429):
                report["status"]="provider_denied_stopped";break
        except (URLError,TimeoutError,D1Error,ValueError,TypeError,KeyError) as exc:
            errors[(str(exc)[:70] if isinstance(exc,ValueError)
                    else type(exc).__name__)]+=1
        finally:
            if fetch is None:time.sleep(delay)
    report["error_reasons"]=dict(sorted(errors.items()))
    try:
        rows=d.query("SELECT id,payload FROM private_365_player_witness ORDER BY id LIMIT 50")
        report["cumulative_player_diagnoses"]=len(rows)
        report["cumulative_player_witness_complete"]=sum(
            json.loads(x["payload"]).get("player_evidence_complete") is True
            for x in rows if str(x["id"]) in remaining)
    except (D1Error,ValueError,TypeError,KeyError):
        report["status"]="private_summary_unavailable"
    return report

def main():
    try:result=audit()
    except (D1Error,ValueError,TypeError,KeyError) as e:
        result={"kind":"eight_365scores_player_stats_differential",
                "status":"failed_closed","reason_type":type(e).__name__,
                "provider_requests":0,"match_promotions":0,
                "player_id_public":False,"individual_xg_public":False,
                "provider_match_id_public":False,"raw_shots_written":False,
                "training_modified":False}
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print(json.dumps(result,ensure_ascii=False))
    return result

if __name__=="__main__":main()
