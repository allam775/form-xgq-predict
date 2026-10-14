"""Private duplicate-ID diagnostic for exactly two ambiguous extra-shot cases.

No guessed exclusion, no provider endpoint discovery, no raw shots published.
Look for duplicate chart-event key, and same (playerId,time,outcome)
collisions, without persisting identifiers or per-shot probabilities.
Two bounded game-detail requests. No original audit changes.
"""
from __future__ import annotations
from collections import Counter
from pathlib import Path
import json
import time

from engine import provider365 as p
from engine.understat_d1 import D1
OUT=Path("research/reports/365_ambiguous_identity_diagnostic.json")

def _signature(e):
    out=e.get("outcome")
    if isinstance(out,dict):out=out.get("name")
    return (str(e.get("playerId")),str(e.get("time")),
            str(out).lower(),str(e.get("competitorNum")))

def classify(g):
    ev=g.get("chartEvents") or g.get("chart_events")
    if isinstance(ev,dict):ev=ev.get("events") or ev.get("chartEvents") or ev.get("items")
    if not isinstance(ev,list) or not ev or len(ev)>500:
        raise ValueError("unexpected_events")
    objs=[e for e in ev if isinstance(e,dict) and p._is_shot(e)]
    counts=Counter(str(e.get("key")) for e in objs if e.get("key") is not None)
    compound=Counter(_signature(e) for e in objs)
    goal_fields=Counter(type(e.get("goalDescription")).__name__ for e in objs)
    key_types=Counter(type(e.get("key")).__name__ for e in objs)
    return {"num_shots":len(objs),
         "key_duplicates":sum(n-1 for n in counts.values() if n>1),
         "same_player_time_outcome_duplicates":sum(n-1 for n in compound.values() if n>1),
         "goalDescription_value_types":dict(goal_fields),
         "key_value_types":dict(key_types),
         "explicit_event_flags":sorted(set(
           k for e in objs for k in e if any(t in str(k).lower()
                                            for t in ("offside","cancel","disallow","var","valid"))))}

def main():
    db=D1()
    db.query("""CREATE TABLE IF NOT EXISTS private_365_ambiguous_id_checks(
       id TEXT PRIMARY KEY NOT NULL,payload TEXT NOT NULL)""")
    rows=db.query("SELECT id,payload FROM private_365_repair_evaluations ORDER BY id")
    ids=[str(x["id"]) for x in rows if json.loads(x["payload"]).get("status")==
                                     "multiple_distinct_shots_would_match"]
    if len(ids)!=2:
        raise ValueError("Expected exactly two still-ambiguous cases")
    total=0;dupes=0;errs=Counter()
    for mid in ids:
        try:
            response=p.fetch("game/",{"gameId":mid,"topBookmaker":"14"})
            g=response.get("game",response)
            if p._game_id(g)!=mid or not p._final(g):
                raise ValueError("match_id_mismatch")
            data=classify(g)
            db.query("INSERT OR REPLACE INTO private_365_ambiguous_id_checks(id,payload) VALUES(?,?)",
                (mid,json.dumps(data,separators=(",",":"))))
            total+=1
            dupes+=data["key_duplicates"]
        except p.AccessDenied:
            errs["provider_denied_stopped"]+=1
            break
        except (ValueError,TypeError,KeyError) as e:
            errs[str(e)[:65]]+=1
        finally:time.sleep(1.5)
    report={"original_ambiguous_cases":2,"requests":total,"diagnosed":total,
            "key_collision_candidates":dupes,"errors":dict(errs),
            "shot_probability_values_stored":0,"public_match_ids":0,
            "original_verified_rows_changed":0}
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(report,indent=2)+"\n")
    print(json.dumps(report))
    return report

if __name__=="__main__":main()
