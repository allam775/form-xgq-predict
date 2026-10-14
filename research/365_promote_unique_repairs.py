"""Promote only rigorously unique 365Scores one-excess-shot repairs to PRIVATE research.

No new third-party requests. Revalidate the three bounded D1 proposals against
their original rejected audit, original identity, independent game/stats count
and xG totals, and categorical proof. Training and production remain disabled.
Leave original audit immutable; provenance records explicit correction.
Never store or publish raw shot streams or per-shot values.
"""
from __future__ import annotations
from collections import Counter
from datetime import datetime,timezone
import importlib
import json
import math
from pathlib import Path

from engine.understat_d1 import D1,D1Error
from engine.xgq import normalized

base=importlib.import_module("research.365_stats_completeness_batch")
OUT=Path("research/reports/365_unique_repairs_promotion.json")

ALLOWED_OUTCOMES={
  "on_target":{"goal","saved"},
  "off_target":{"missed","post"},
  "blocked":{"blocked"}
}

def proof(candidate,old,independent,categories,proposal):
    if (old.get("complete") is not False or
        old.get("status")!="shot_count_mismatch"):
        raise ValueError("not_original_extra_event_rejection")
    if (candidate.get("catalog_verified") is not True or
        candidate.get("eligible_for_forecast") is not False or
        candidate.get("completeness")!="NOT_VERIFIED_INDEPENDENT_TOTALS"):
        raise ValueError("invalid_original_candidate_state")
    if (proposal.get("training_release") is not False
        or proposal.get("correction_proof")!="one_unique_observed_overcounted_outcome_with_independent_stats"):
        raise ValueError("not_independently_proved")
    if any(proposal.get(k)!=candidate.get(k) for k in
           ("league","date","home","away","hg","ag","source_match_id")):
        raise ValueError("match_identity_changed")
    side=proposal.get("corrected_side")
    other="away" if side=="home" else "home"
    if side not in ("home","away") or not proposal.get("disallowed_event_outcome") in ALLOWED_OUTCOMES.get(
        proposal.get("corrected_outcome_class"),set()):
        raise ValueError("ambiguous_outcome_class")
    cat=proposal["corrected_outcome_class"]
    delta=categories[side]["differences"]
    if (delta.get(cat)!=-1 or delta.get("total")!=-1
        or any(delta.get(k)!=0 for k in ("on_target","off_target","blocked") if k!=cat)):
        raise ValueError("outcome_counts_unreconciled")
    if (candidate[side+"_chart_shots"]!=independent[side]["shots"]+1
        or candidate[other+"_chart_shots"]!=independent[other]["shots"]):
        raise ValueError("not_exactly_one_extra_shot")
    for k in ("home","away"):
        n=independent[k]["shots"]
        v=proposal[k+"_xg"]
        q=proposal[k+"_xgq"]
        if (proposal[k+"_shots"]!=n or type(v) not in (float,int) or
            type(q) not in (float,int) or not math.isfinite(v) or
            not math.isfinite(q) or not 0<=q<=1 or not 0<=v<=n):
            raise ValueError("bad_repaired_match_statistic")
        precision=independent[k]["xg_display_decimals"]
        if not (0<=precision<=4):
            raise ValueError("unverified_total_precision")
        tol=.005*n+.5*(10**-precision)+1e-9
        if abs(v-independent[k]["xg"])>tol:
            raise ValueError("repaired_independent_xg_disagrees")
    if abs(proposal[other+"_xg"]-candidate[other+"_chart_xg_sum"])>1e-6:
        raise ValueError("untouched_team_changed")
    if proposal[side+"_xg"]>candidate[side+"_chart_xg_sum"]+1e-6:
        raise ValueError("removed_shot_cannot_increase_xg")
    return True


def promote(db=None):
    d=db if db is not None else D1()
    candidates=base.candidates(d);audits=base.prior_audits(d)
    evaluations=d.query("SELECT id,payload FROM private_365_repair_evaluations LIMIT 50")
    evals={str(v["id"]):json.loads(v["payload"]) for v in evaluations}
    proposals=d.query("SELECT id,payload FROM private_365_repair_proposals LIMIT 50")
    if len(proposals)!=3:
        raise ValueError("expected_exactly_three_unique_private_proposals")
    d.query("""CREATE TABLE IF NOT EXISTS private_365_research_verified(
        id TEXT PRIMARY KEY NOT NULL,payload TEXT NOT NULL)""")
    d.query("""CREATE TABLE IF NOT EXISTS private_365_repair_acceptance(
        id TEXT PRIMARY KEY NOT NULL,payload TEXT NOT NULL)""")
    pre=d.query("SELECT COUNT(*) AS n FROM private_365_research_verified")
    start=int(pre[0]["n"])
    outcomes=Counter()
    for item in proposals:
        mid=str(item["id"])
        c=candidates[mid]
        o=audits[mid]
        if evals.get(mid)!={"status":"uniquely_reconciled_overcounted_chart_shot","ok":True}:
            raise ValueError("separate_mathematical_evaluation_unverified")
        original=d.query("SELECT payload FROM private_365_rejected_diagnosis WHERE id=?",(mid,))
        categories=d.query("SELECT payload FROM private_365_rejected_stat_breakdown WHERE id=?",(mid,))
        if len(original)!=1 or len(categories)!=1:
            raise ValueError("missing_independent_source_witness")
        w=json.loads(original[0]["payload"])["source_stats"]
        cat=json.loads(categories[0]["payload"])["by_side"]
        proposal=json.loads(item["payload"])
        proof(c,o,w,cat,proposal)
        row={k:v for k,v in proposal.items()
             if k not in ("correction_proof","number_of_equivalent_removals")}
        row["id"]=f"{row['league']}|{row['date']}|{normalized(row['home'])}|{normalized(row['away'])}"
        row["h"]=normalized(row["home"]);row["a"]=normalized(row["away"])
        row["independent_completeness"]="deterministic_single_excess_chart_shot_removed"
        row["verified_stats_endpoint"]=True
        row["training_release"]=False
        row["correction_audit"]="original_immutable_audit_plus_unique_outcome_and_independent_totals"
        d.query("INSERT OR REPLACE INTO private_365_research_verified(id,payload) VALUES(?,?)",
                (row["id"],json.dumps(row,separators=(",",":"),ensure_ascii=False)))
        d.query("INSERT OR REPLACE INTO private_365_repair_acceptance(id,payload) VALUES(?,?)",
                (mid,json.dumps({"proof":"independent_shots_xg_outcome_reconciled",
                   "date":datetime.now(timezone.utc).isoformat(),
                   "production_release":False},separators=(",",":"))))
        outcomes[c["league"]]+=1
    after=d.query("SELECT COUNT(*) AS n FROM private_365_research_verified")
    finish=int(after[0]["n"])
    return {"verified_research_total":finish,
            "unique_corrections_confirmed":len(proposals),
            "new_verified_research_rows":finish-start,
            "by_competition":dict(sorted(outcomes.items())),
            "original_rejection_audit_unchanged":True,
            "training_release":False,
            "provider_requests":0,
            "published_private_rows":0,
            "raw_event_data_written":0}


def main():
    try:r=promote()
    except (D1Error,KeyError,ValueError,TypeError) as e:
        r={"status":"fail_closed","reason_type":type(e).__name__,
           "provider_requests":0,"published_private_rows":0,
           "raw_event_data_written":0,"training_release":False}
    else:r["status"]="success"
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(r,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps(r,ensure_ascii=False))
    return r
if __name__=="__main__":main()
