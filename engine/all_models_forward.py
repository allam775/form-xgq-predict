"""Pre-kickoff supplement for already-frozen legacy Penniless match ledgers.

New forecasts always contain the complete 8-model suite in the primary ledger.
A previously frozen fixture may legitimately lack a newly approved model.
We NEVER change the primary immutable record; write missing *model* predictions
in a separate ledger only if computed before kickoff using earlier-day history.
Evaluate the supplement separately after a verified Understat final.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
import json
import math

from .daily_forecast import (
    MODEL_SUITE, MODEL_SUITE_VERSION, LEAD, FORECASTS, OUTCOMES,
    _forecast, _utc, fetch_upcoming, ensure_tables,
)
from .prematch_ledger import _ratings_by_league
from .provider_understat import SOURCE, fetch as understat_fetch
from .understat_backfill import validate_config
from .understat_d1 import D1

TABLE = "private_daily_supplemental_forecasts"
GRADES = "private_daily_supplemental_grades"
LIMIT = 20000


def _rows(db, table):
    if table not in (FORECASTS, TABLE, GRADES):
        raise ValueError("Unknown forecast ledger")
    all_rows = []
    offset = 0
    while True:
        chunk = db.query(
            f"SELECT payload FROM {table} ORDER BY id LIMIT ? OFFSET ?",
            (250,offset),
        )
        all_rows.extend(json.loads(item["payload"]) for item in chunk)
        if len(all_rows) > LIMIT:
            raise ValueError("Forecast ledger exceeded safety bound")
        if len(chunk) < 250:
            break
        offset += len(chunk)
    return all_rows


def _ensure(db):
    ensure_tables(db)
    db.query(f"CREATE TABLE IF NOT EXISTS {TABLE} (id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
    db.query(f"CREATE TABLE IF NOT EXISTS {GRADES} (id TEXT PRIMARY KEY, payload TEXT NOT NULL)")


def make_supplement(fixture, original, suite, *, now):
    """A supplement is limited to genuinely absent models for this same fixture."""
    now = _utc(now)
    original_ko = datetime.fromisoformat(original["kickoff_utc"])
    ko = datetime.fromisoformat(fixture["kickoff_utc"])
    frozen = datetime.fromisoformat(original["frozen_at_utc"])
    if (original["id"] != fixture["id"] or
        str(original["source_match_id"]) != str(fixture["source_match_id"]) or
        original["home_id"] != fixture["h"] or original["away_id"] != fixture["a"] or
        original["date"] != fixture["date"] or original_ko != ko):
        raise ValueError("Conflicting frozen fixture identity or kickoff; do not supplement")
    if (frozen >= ko or now + LEAD >= ko):
        raise ValueError("Supplement must be created safely before kickoff")
    already = set(original["models"])
    missing = set(MODEL_SUITE) - already
    if not missing:
        return None
    if (suite is None or set(suite["models"]) != set(MODEL_SUITE) or
        suite.get("stage3_missing_replaced_by_stage1") is not False):
        raise ValueError("Incomplete or substituted newly computed model suite")
    models = {name:suite["models"][name] for name in MODEL_SUITE if name in missing}
    picks = {name:suite["picks"][name] for name in models}
    for name,prob in models.items():
        if (set(prob) != set(OUTCOMES) or
            abs(sum(prob.values())-1) > 1e-6 or
            any(not isinstance(v,(int,float)) or not math.isfinite(v) or v < 0
                for v in prob.values()) or
            picks[name] != max(OUTCOMES,key=lambda k:prob[k])):
            raise ValueError("Invalid saved supplemental model "+name)
    return {
        "id":original["id"],"league":original["league"],
        "date":original["date"],"source_match_id":original["source_match_id"],
        "home_id":original["home_id"],"away_id":original["away_id"],
        "kickoff_utc":fixture["kickoff_utc"],"frozen_at_utc":now.isoformat(),
        "status":"frozen_supplement_no_original_rewrite",
        "suite_version":MODEL_SUITE_VERSION,
        "models":models,"picks":picks,
        "original_frozen_model":original["model"],
        "existing_original_models":sorted(already),
        "no_postkickoff_prediction":True,
        "no_original_prediction_changed":True,
        "source":SOURCE,
    }


def freeze(db, *, now=None, fetcher=understat_fetch):
    now = _utc(now or datetime.now(timezone.utc))
    leagues,_,_=validate_config(db.get_setting())
    _ensure(db)
    upcoming=fetch_upcoming(leagues,now=now,fetcher=fetcher)
    originals={row["id"]:row for row in _rows(db,FORECASTS)}
    existing={row["id"] for row in _rows(db,TABLE)}
    candidates=[f for f in upcoming if f["id"] in originals]
    # Compute pre-match suite only when the original fixture truly lacks models.
    pending=[f for f in candidates if f["id"] not in existing and
             set(originals[f["id"]]["models"]) != set(MODEL_SUITE)]
    if pending:
        prior=[r for r in db.history() if r["source"]==SOURCE and
               r["date"] < now.date().isoformat()]
        ratings=_ratings_by_league(prior)
        by_league=defaultdict(list)
        for r in prior:by_league[r["league"]].append(r)
    else:
        ratings={}
        by_league={}
    a=Counter()
    a["upcoming_registered"]=len(upcoming)
    a["older_originals_present"]=len(candidates)
    a["existing_supplements"]=len(existing)
    for f in pending:
        old=originals[f["id"]]
        suite,why=_forecast(f,by_league[f["league"]],
                            ratings.get(f["league"],{}),now=now)
        if suite is None:
            a["withheld"]+=1
            a["withheld_"+str(why)]+=1
            continue
        new=make_supplement(f,old,suite,now=now)
        if new:
            db.query(f"INSERT OR IGNORE INTO {TABLE}(id,payload) VALUES (?,?)",
                     (new["id"],json.dumps(new,ensure_ascii=False,separators=(",",":"))))
            a["supplemented_fixtures"]+=1
            a["new_model_predictions"]+=len(new["models"])
    # Exact models in the immutable primary ledger OR in an independent
    # pre-kickoff supplement. Missing genuine models remain visible.
    supplements={row["id"]:row for row in _rows(db,TABLE)}
    incomplete=0
    for f in upcoming:
        base=originals.get(f["id"])
        if not base:
            # This job follows the main freeze step, so unknowns must be surfaced.
            a["upcoming_not_in_primary_ledger"]+=1
            continue
        present=set(base["models"])
        if f["id"] in supplements:
            present.update(supplements[f["id"]]["models"])
        if present == set(MODEL_SUITE):
            a["complete_suite_fixtures"]+=1
        else:
            incomplete+=1
    a["incomplete_suite_fixtures"]=incomplete
    a["total_supplemented"]=len(supplements)
    return dict(a)


def grade(db, *, now=None):
    now = _utc(now or datetime.now(timezone.utc))
    _ensure(db)
    preds=_rows(db,TABLE)
    already={row["id"] for row in _rows(db,GRADES)}
    history={(r["league"],str(r["source_match_id"])):r for r in db.history()}
    added=0
    for row in preds:
        if row["id"] in already:continue
        kickoff=datetime.fromisoformat(row["kickoff_utc"])
        frozen=datetime.fromisoformat(row["frozen_at_utc"])
        if frozen >= kickoff:
            raise ValueError("Invalid supplemental kickoff integrity")
        if now < kickoff+timedelta(minutes=115):
            continue
        actual=history.get((row["league"],str(row["source_match_id"])))
        if not actual or (actual["date"]!=row["date"] or
            actual["h"]!=row["home_id"] or actual["a"]!=row["away_id"]):
            continue
        result="home" if actual["hg"]>actual["ag"] else (
            "away" if actual["hg"]<actual["ag"] else "draw")
        scores={}
        for name,prob in row["models"].items():
            scores[name]={
                "pick":row["picks"][name],
                "correct":row["picks"][name]==result,
                "log_loss":round(-math.log(max(prob[result],1e-12)),8),
                "brier":round(sum((prob[k]-int(k==result))**2 for k in OUTCOMES),8),
            }
        report={"id":row["id"],"date":row["date"],
                "verified_understat_match_id":actual["source_match_id"],
                "outcome":result,"hg":actual["hg"],"ag":actual["ag"],
                "frozen_at_utc":row["frozen_at_utc"],
                "graded_at_utc":now.isoformat(),"models":scores}
        db.query(f"INSERT OR IGNORE INTO {GRADES}(id,payload) VALUES (?,?)",
                 (report["id"],json.dumps(report,ensure_ascii=False,separators=(",",":"))))
        added+=1
    return {"newly_graded_supplements":added,
            "total_supplemented":len(preds),
            "total_graded_supplements":len(_rows(db,GRADES))}


def main(argv=None):
    parser=argparse.ArgumentParser()
    parser.add_argument("action",choices=("freeze","grade"))
    args=parser.parse_args(argv)
    db=D1()
    result=freeze(db) if args.action=="freeze" else grade(db)
    print(json.dumps(result,sort_keys=True))
    return result

if __name__=="__main__":
    main()
