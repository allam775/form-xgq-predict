"""Compare eleven rejected 365Scores chart outcomes to independently reported shot categories.

Every match ID is read from private D1 audit. Exactly one documented
game/stats/ request per rejected match (11 maximum). Independent metrics:
Total Shots, Shots On Target, Shots Off Target, Shots Blocked, Hit Woodwork,
Expected Goals. Compare them with aggregated chart outcomes already stored
in private D1; do NOT re-download or store raw chart events/shot xG.

Per-match/side results go ONLY to private D1. Public report is counts.
NO automated approval, no modification of original audits or training.
"""
from __future__ import annotations
from collections import Counter
from pathlib import Path
import importlib
import json
import time

from engine.understat_d1 import D1
from engine.xgq import normalized
from engine.stats365 import stats_witness,_as_decimal
from engine.provider365 import AccessDenied
fetch_stats=importlib.import_module("research.365_stats_schema_probe").fetch_stats
base=importlib.import_module("research.365_stats_completeness_batch")
OUT=Path("research/reports/365_rejected_stat_breakdown_summary.json")
MAX_REQUESTS=11
NAMES=("Shots On Target","Shots Off Target","Shots Blocked","Hit Woodwork","Total Shots","Expected Goals")


def map_breakdown(payload,candidate,source_aggregates):
    witness=stats_witness(payload,candidate)
    teams=payload["competitors"]
    actual={normalized(x.get("name")):str(x["id"]) for x in teams}
    stats=payload["statistics"]
    record={}
    for side in ("home","away"):
        sid=actual[normalized(candidate[side])]
        numeric={}
        for name in NAMES:
            rows=[x for x in stats if isinstance(x,dict)
                  and str(x.get("competitorId"))==sid and x.get("name")==name]
            if name=="Hit Woodwork" and not rows:
                # Optional category not returned by all competitions/matches.
                # Unknown is NOT a zero count, so never fabricate it.
                numeric[name]=None
                continue
            if len(rows)!=1:
                raise ValueError("ambiguous_category_"+name)
            count,_=_as_decimal(rows[0].get("value"),integer=name!="Expected Goals")
            numeric[name]=float(count) if name=="Expected Goals" else int(count)
        if numeric["Total Shots"]!=witness[side]["shots"]:
            raise ValueError("inconsistent_official_totals")
        by_outcome=Counter()
        for entry in source_aggregates[side]:
            sig=entry.get("signature","").split("|")
            if len(sig)<4:raise ValueError("malformed_preaggregated_signature")
            by_outcome[sig[3]]+=entry["count"]
        chart={
          "On Target":by_outcome["saved"]+by_outcome["goal"],
          "Off Target":by_outcome["missed"]+by_outcome["post"],
          "Blocked":by_outcome["blocked"],
          "Posts":by_outcome["post"],
          "Total":sum(by_outcome.values())
        }
        differences={
          "on_target":numeric["Shots On Target"]-chart["On Target"],
          "off_target":numeric["Shots Off Target"]-chart["Off Target"],
          "blocked":numeric["Shots Blocked"]-chart["Blocked"],
          "woodwork":(numeric["Hit Woodwork"]-chart["Posts"]
                      if numeric["Hit Woodwork"] is not None else None),
          "total":numeric["Total Shots"]-chart["Total"],
        }
        record[side]={"stats":numeric,"chart":chart,"differences":differences}
    return record


def main():
    db=D1()
    candidates=base.candidates(db)
    audits=base.prior_audits(db)
    mids=sorted(i for i in candidates if i in audits and audits[i].get("complete") is False)
    if len(mids)!=11:
        raise ValueError("Expected 11 originally rejected matches")
    db.query("""CREATE TABLE IF NOT EXISTS private_365_rejected_stat_breakdown(
      id TEXT PRIMARY KEY NOT NULL,payload TEXT NOT NULL)""")
    already={str(r["id"]) for r in db.query(
        "SELECT id FROM private_365_rejected_stat_breakdown LIMIT 100")}
    freq=Counter();errors=Counter()
    output={"source":"365Scores","rejected_cases":len(mids),"requests":0,
       "checked":0,"already_checked_skipped":0,"raw_shots_written":0,"public_private_rows":0,
       "old_verification_modified":False,
       "category_gap_patterns":{},"errors":{}}
    for mid in mids:
        if mid in already:
            output["already_checked_skipped"]+=1
            continue
        try:
            saved=db.query("SELECT payload FROM private_365_rejected_diagnosis WHERE id=?",(mid,))
            if len(saved)!=1:
                raise ValueError("original_private_event_aggregate_missing")
            diagnostic=json.loads(saved[0]["payload"])
            source=diagnostic["new_chart"]["groups"]
            output["requests"]+=1
            stats=fetch_stats(mid)
            reconstructed=map_breakdown(stats,candidates[mid],source)
            db.query("INSERT OR REPLACE INTO private_365_rejected_stat_breakdown(id,payload) VALUES(?,?)",
                    (mid,json.dumps({"by_side":reconstructed,"previous":audits[mid]["status"]},
                          separators=(",",":"))))
            output["checked"]+=1
            for side in ("home","away"):
                diffs=reconstructed[side]["differences"]
                if any(v is not None and v!=0 for v in diffs.values()):
                    freq["gap_"+"/".join(f"{k}:{v}" for k,v in sorted(diffs.items()) if v is not None and v!=0)] += 1
                else:freq["all_categories_match"]+=1
        except AccessDenied:
            errors["source_denied_stopped"]+=1
            break
        except (ValueError,TypeError,KeyError) as e:
            errors[str(e)[:55]]+=1
        finally:
            time.sleep(1.3)
    archived=db.query("SELECT COUNT(*) AS n FROM private_365_rejected_stat_breakdown")
    output["cumulative_checked"]=int(archived[0]["n"])
    output["category_gap_patterns"]=dict(freq)
    output["errors"]=dict(errors)
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(output,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps(output,ensure_ascii=False))
    return output

if __name__=="__main__":main()
