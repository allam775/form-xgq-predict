"""Independent same-provider web-stat witness for one published UCL match.

Do not try to bootstrap user-facing historical match data from incomplete
chartEvents. Independently published 365Scores match-page TOTAL SHOTS
and team xG are reconciled with privately stored chart-event aggregates.

Official 365Scores page (viewed 2026-10-14):
https://www.365scores.com/en-us/football/match/-572/club-brugge-inter-milan-224-1169-572
Inter 3–4 Club Brugge on 2026-10-13:
Shots 29–15, xG 3.79–3.68 (rounded to 2 decimals).
Source: match page, NOT estimated from existing chartEvents.

Only if *both* counts equal EXACTLY and total xG sums reconcile under
per-shot rounding tolerance may the candidate move to a separate private
verified-research table. No raw shot data or match-level 365 values are
published in the workflow audit. User reports prior private XGQ permission.
"""
from __future__ import annotations
from datetime import date
import json
from pathlib import Path

from engine.understat_d1 import D1,D1Error
from engine.xgq import normalized
from engine.private_history import SOURCE as PRIVATE_SOURCE

OUT=Path("research/reports/365_witness_audit.json")
WITNESS={
    "date":"2026-10-13","league":"uefa.cl",
    "home":"Inter Milan","away":"Club Brugge",
    "hg":3,"ag":4,
    "home_shots":29,"away_shots":15,
    "home_xg":3.79,"away_xg":3.68,
    "shot_decimals":2,"aggregate_decimals":2,
    "source_url":"https://www.365scores.com/en-us/football/match/-572/club-brugge-inter-milan-224-1169-572",
}


def find_candidates(rows,witness=WITNESS):
    good=[]
    for row in rows:
        if (row.get("league")==witness["league"]
            and row.get("date")==witness["date"]
            and normalized(row.get("home"))==normalized(witness["home"])
            and normalized(row.get("away"))==normalized(witness["away"])
            and row.get("hg")==witness["hg"] and row.get("ag")==witness["ag"]
            and row.get("competition_id")=="572"
            and row.get("catalog_verified") is True):
            good.append(row)
    return good


def validate_witness(row,w=WITNESS):
    if row.get("eligible_for_forecast") is not False or row.get("completeness")!="NOT_VERIFIED_INDEPENDENT_TOTALS":
        raise ValueError("Unexpected candidate evidence state")
    if len(find_candidates([row],w))!=1:
        raise ValueError("Match identity/competition/score not confirmed")
    for side in ("home","away"):
        count=row[side+"_chart_shots"]
        if type(count) is not int or count!=w[side+"_shots"]:
            raise ValueError(side+"_shot_count_disagrees")
        observed=row[side+"_chart_xg_sum"]
        if type(observed) not in (float,int):
            raise ValueError(side+"_shot_xg_sum_unavailable")
        tol=0.5*10**(-w["shot_decimals"])*count+0.5*10**(-w["aggregate_decimals"])+1e-8
        if abs(observed-w[side+"_xg"])>tol:
            raise ValueError(side+"_sum_xg_disagrees")
    return True


def compact_verified(row):
    """Already xGq-derived individual event squares, independently reconciled."""
    if not validate_witness(row):
        raise ValueError("Independent reconciliation failed")
    day=row["date"];home=row["home"];away=row["away"]
    return {
        "id":f"uefa.cl|{day}|{normalized(home)}|{normalized(away)}",
        "date":day,"league":"uefa.cl",
        "home":home,"away":away,
        "h":normalized(home),"a":normalized(away),
        "hg":row["hg"],"ag":row["ag"],
        "home_xg":row["home_chart_xg_sum"],
        "away_xg":row["away_chart_xg_sum"],
        "home_xgq":row["home_provisional_xgq"],
        "away_xgq":row["away_provisional_xgq"],
        "home_shots":row["home_chart_shots"],
        "away_shots":row["away_chart_shots"],
        "source":PRIVATE_SOURCE,
        "source_match_id":row["source_match_id"],
        "evidence":"two-sided shot count and xG sum reconciled to dated 365Scores 90-min published stats",
        "model_eligible_only_after_private_validation":True,
    }


def main():
    status={"source":"365Scores","witness_source":"official published 90-minute match stats",
            "cases_checked":1,"candidate_matches_found":0,
            "independently_verified":0,"private_verified_saved":0,
            "private_match_records_published":0,"raw_shot_events_exported":0,
            "reason":"not_started"}
    try:
        d=D1()
        found=d.query("SELECT payload FROM private_365_research_candidates LIMIT 250")
        rows=[json.loads(v["payload"]) for v in found]
        matches=find_candidates(rows)
        status["candidate_matches_found"]=len(matches)
        if len(matches)!=1:
            status["reason"]="no_unique_precollected_matching_candidate"
        else:
            try:
                verified=compact_verified(matches[0])
            except ValueError as exc:
                status["reason"]=str(exc)
            else:
                # Independent validation done. Separate table so no public or
                # legacy production XGQ cache can see the record accidentally.
                d.query("""CREATE TABLE IF NOT EXISTS private_365_research_verified(
                    id TEXT PRIMARY KEY NOT NULL,payload TEXT NOT NULL)""")
                d.query("INSERT OR REPLACE INTO private_365_research_verified(id,payload) VALUES(?,?)",
                        (verified["id"],json.dumps(verified,separators=(",",":"))))
                status["independently_verified"]=1
                status["private_verified_saved"]=1
                status["reason"]="two_sided_shots_and_xg_reconciled"
    except (D1Error,ValueError,TypeError,KeyError) as exc:
        status["reason"]="private_db_"+type(exc).__name__
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(status,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print(json.dumps(status,ensure_ascii=False))
    return status

if __name__=="__main__":
    main()
