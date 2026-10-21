"""Penniless UCL pre-kickoff forecasts. Separately versioned continental suite.

- Official schedule is fixed in research/ucl_2026_27_fixtures.txt;
  dates without exact times get a strictly BEFORE-DAY 00:00 UTC deadline.
- Today (21 Oct) kickoff times are publicly reported and explicitly verified.
- Every model uses only D1 five-league data dated strictly before the fixture.
- Only officially verified prior UCL scores from a separate audited result file
  update UEFA-pot rating priors. No 20 Oct scores retroactively enter 20 Oct
  pre-existing forecast evaluations.
- No fabricated pan-European Elo/XGQ for 15 clubs outside the five leagues.
- No overwrite of any legacy published UCL forecasts.
"""
from __future__ import annotations
from collections import defaultdict,Counter
from datetime import datetime,date,timedelta,timezone
from itertools import groupby
from pathlib import Path
import csv
import hashlib
import json
import math

from .ucl_2026_27 import (fixtures,profiles,calc,TEAM_NAMES,TEAM_POT,TIER_ELO)
from engine.understat_d1 import D1

ROOT=Path(__file__).resolve().parent
SOURCE=ROOT/"ucl2026_27_verified_results.json"
EXISTING=ROOT/"reports/ucl2026_27/ucl_2026_27_matches.csv"
FIXTURE_TABLE="private_ucl_forward_forecasts_2026_27"
GRADE_TABLE="private_ucl_forward_grades_2026_27"
AUDIT_KEY="penniless_ucl_oct20_pregame_original_assessment"
MODEL_VERSION="ucl-pot-prior-domestic-xgq-dc-v1-20261021"
PICK_MODELS=("ucl_pot_dc_goals","ucl_pot_xgq_blend")
HORIZON=timedelta(days=8)
LEAD=timedelta(minutes=30)
OUTCOMES=("home","draw","away")

# Public UEFA matchday-3 start times verified Oct 21; Oct 21 Europe still UTC+2.
# Never guess clock times for other fixture days.
VERIFIED_KICKOFFS={
 ("2026-10-21","Como","Manchester United"):"2026-10-21T16:45:00+00:00",
 ("2026-10-21","Lille","Galatasaray"):"2026-10-21T16:45:00+00:00",
 **{("2026-10-21",h,a):"2026-10-21T19:00:00+00:00" for h,a in (
    ("Aston Villa","Viking"),("Club Brugge","Lens"),
    ("Bayern Munich","Arsenal"),("Inter","Shakhtar Donetsk"),
    ("Real Madrid","RB Leipzig"),("Real Betis","Feyenoord"),
    ("Sporting CP","LASK")
 )}
}

def _utc(now):
    if now.tzinfo is None: raise ValueError("Timezone-aware clock required")
    return now.astimezone(timezone.utc)

def verified_results(schedule):
    data=json.loads(SOURCE.read_text(encoding="utf-8"))
    index={(x["date"],x["home"],x["away"]):x for x in schedule}
    found={}
    for x in schedule:
        if x["actual"] is not None:
            found[(x["date"],x["home"],x["away"])]=tuple(x["actual"])
    for row in data["matches"]:
        if len(row)!=5: raise ValueError("Invalid official verified row")
        day,h,a,hg,ag=row
        date.fromisoformat(day)
        key=(day,h,a)
        if key not in index or key in found or any(type(z)!=int or not 0<=z<=30 for z in (hg,ag)):
            raise ValueError("Unmatched/duplicate/invalid UCL certified result "+str(key))
        found[key]=(hg,ag)
    return found

def rating_at(fixtures_list, verified, *, before):
    ratings={t:float(TIER_ELO[TEAM_POT[t]]) for t in TEAM_NAMES}
    for day,batch in groupby(sorted(fixtures_list,key=lambda x:(x["date"],x["id"])),lambda x:x["date"]):
        if day>=before:break
        changes=defaultdict(float)
        for match in batch:
            key=(match["date"],match["home"],match["away"])
            outcome=verified.get(key)
            if outcome is None:continue
            home,away=match["home"],match["away"]
            hg,ag=outcome
            expected=1/(1+10**(-((ratings[home]+58-ratings[away])/400)))
            actual=1. if hg>ag else .5 if hg==ag else 0.
            delta=18*(actual-expected)
            changes[home]+=delta
            changes[away]-=delta
        for team,delta in changes.items():ratings[team]+=delta
    return ratings

def kickoff_deadline(match):
    day,h,a=match["date"],match["home"],match["away"]
    official=VERIFIED_KICKOFFS.get((day,h,a))
    if official:
        kickoff=datetime.fromisoformat(official)
        if kickoff.date().isoformat()!=day: raise ValueError("Incorrect kickoff fixture day")
        return kickoff,True
    # Highly conservative when a verified kickoff clock is missing:
    # freeze the day BEFORE the match starts (midnight UTC).
    return datetime.fromisoformat(day+"T00:00:00+00:00"),False

def candidate_matches(schedule,*,now):
    now=_utc(now)
    result=[]
    for m in schedule:
        cutoff,has_clock=kickoff_deadline(m)
        if now+LEAD<cutoff<=now+HORIZON:
            result.append((m,cutoff,has_clock))
    return result

def forecasts_for(schedule,verified,history,*,now):
    now=_utc(now)
    output=[]
    excluded=Counter()
    candidates=candidate_matches(schedule,now=now)
    for match,deadline,has_clock in candidates:
        target=match["date"]
        if (target,match["home"],match["away"]) in verified:
            excluded["already_completed"]+=1;continue
        # Change historical training cutoff per fixture, no same-day score leakage.
        form,stats,n=profiles(history,cutoff=target)
        ratings=rating_at(schedule,verified,before=target)
        model=calc(match,ratings,form)
        goal=model["pure_goals"]
        blend=model["p"]
        choices={PICK_MODELS[0]:goal,PICK_MODELS[1]:blend}
        for name,prob in choices.items():
            if (set(prob)!=set(OUTCOMES) or
                not all(math.isfinite(z) and z>=0 for z in prob.values()) or
                abs(sum(prob.values())-1)>.00001):
                raise ValueError("Invalid pre-match forecast "+name)
        key=f"ucl.1|{target}|{match['home']}|{match['away']}"
        output.append(dict(id=key,matchday=match["round"],date=target,
            home=match["home"],away=match["away"],
            model_version=MODEL_VERSION,
            status="frozen_before_kickoff",
            deadline_utc=deadline.isoformat(),
            kickoff_clock_verified=has_clock,
            frozen_at_utc=now.isoformat(),
            strict_evidence_date_before=target,
            official_prior_ucl_games=sum(d<target for d,h,a in verified),
            domestic_prior_matches=n,
            model_names=list(PICK_MODELS),
            models=choices,
            picks={name:max(OUTCOMES,key=lambda z:prob[z]) for name,prob in choices.items()},
            unavailable_model_explanation="Five-league Stage1/Stage3/V2 not directly transferable: no validated same-provider continental shot records for all clubs.",
            source_fixture="UEFA official fixed UCL league-phase schedule",
            source_score="official results manually verified and dated separately",
            pre_match_clock_conservative=not has_clock))
    return output,dict(excluded)

def _make(db):
    db.query(f"CREATE TABLE IF NOT EXISTS {FIXTURE_TABLE} (id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
    db.query(f"CREATE TABLE IF NOT EXISTS {GRADE_TABLE} (id TEXT PRIMARY KEY, payload TEXT NOT NULL)")

def _get(db,table):
    if table not in (FIXTURE_TABLE,GRADE_TABLE):
        raise ValueError("Unexpected table")
    output=[]
    offset=0
    while True:
        page=db.query(f"SELECT id,payload FROM {table} ORDER BY id LIMIT ? OFFSET ?",(150,offset))
        output.extend(page)
        if len(output)>20000:raise ValueError("Ledger too large")
        if len(page)<150: return output
        offset+=len(page)

def freeze(db,*,now=None):
    now=_utc(now or datetime.now(timezone.utc))
    _make(db)
    scheduled=fixtures()
    done=verified_results(scheduled)
    known={x["id"] for x in _get(db,FIXTURE_TABLE)}
    # Build only missing records, never overwrite a prior UCL pick.
    candidates=[x for x in candidate_matches(scheduled,now=now)
                if f"ucl.1|{x[0]['date']}|{x[0]['home']}|{x[0]['away']}" not in known]
    if not candidates:
        return {"status":"no_new_pending","total_frozen":len(known),
                "upcoming":len(candidate_matches(scheduled,now=now))}
    history=db.history()
    rows,excluded=forecasts_for(scheduled,done,history,now=now)
    added=0
    for row in rows:
        if row["id"] in known:continue
        db.query(f"INSERT OR IGNORE INTO {FIXTURE_TABLE}(id,payload) VALUES (?,?)",
                 (row["id"],json.dumps(row,separators=(",",":"),ensure_ascii=False)))
        added+=1
    return {"status":"new_frozen","newly_frozen":added,
            "total_frozen":len(_get(db,FIXTURE_TABLE)),
            "upcoming":len(candidate_matches(scheduled,now=now)),
            "excluded":excluded}

def grade(db,*,now=None):
    now=_utc(now or datetime.now(timezone.utc))
    _make(db)
    saved=[json.loads(r["payload"]) for r in _get(db,FIXTURE_TABLE)]
    already={r["id"] for r in _get(db,GRADE_TABLE)}
    schedule=fixtures()
    valid=verified_results(schedule)
    all_uefa={(x["date"],x["home"],x["away"]) for x in schedule}
    scores_table="private_ucl_confirmed_finals_2026_27"
    db.query(f"CREATE TABLE IF NOT EXISTS {scores_table} (id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
    # The scheduled results collector independently certifies final status,
    # exact UEFA fixture identity and 365Scores competition 572.
    for offset in range(0,3000,150):
        page=db.query(f"SELECT payload FROM {scores_table} ORDER BY id LIMIT ? OFFSET ?",(150,offset))
        for item in page:
            got=json.loads(item["payload"])
            key=(got["date"],got["home"],got["away"])
            score=(got["hg"],got["ag"])
            if (key not in all_uefa or got.get("competition")!="uefa.cl"
                    or got.get("status")!="certified_final"
                    or any(type(x)!=int or not 0<=x<=30 for x in score)
                    or (key in valid and valid[key]!=score)):
                raise ValueError("Unverified or conflicting continental result in D1")
            valid[key]=score
        if len(page)<150:break
    added=0
    for row in saved:
        if row["id"] in already: continue
        key=(row["date"],row["home"],row["away"])
        score=valid.get(key)
        if score is None or row["date"]>=now.date().isoformat():continue
        cutoff=datetime.fromisoformat(row["deadline_utc"])
        if datetime.fromisoformat(row["frozen_at_utc"])>=cutoff:
            raise ValueError("Post-deadline UCL prediction")
        hg,ag=score
        outcome="home" if hg>ag else "away" if hg<ag else "draw"
        metrics={}
        for name,p in row["models"].items():
            metrics[name]={"pick":row["picks"][name],
                "correct":row["picks"][name]==outcome,
                "log_loss":-math.log(max(p[outcome],1e-12)),
                "brier":sum((p[k]-int(k==outcome))**2 for k in OUTCOMES)}
        record={"id":row["id"],"date":row["date"],"hg":hg,"ag":ag,
                "outcome":outcome,"models":metrics,
                "grade_source":("UEFA-verified historical static file" if key in verified_results(schedule)
                                else "365Scores verified final+explicit UEFA competition+fixture"),
                "graded_at_utc":now.isoformat()}
        db.query(f"INSERT OR IGNORE INTO {GRADE_TABLE}(id,payload) VALUES (?,?)",
                 (row["id"],json.dumps(record,separators=(",",":"),ensure_ascii=False)))
        added+=1
    return {"newly_graded":added,"total_graded":len(_get(db,GRADE_TABLE)),
            "awaiting_verified_result":len(saved)-len(_get(db,GRADE_TABLE))}

def assess_oct20(path=EXISTING):
    # A pre-existing, published-before-Oct20 forecast, not a fresh replay.
    raw=path.read_bytes()
    blob=hashlib.sha1(b"blob "+str(len(raw)).encode()+b"\x00"+raw).hexdigest()
    if blob!="6b53aef892c7b0b5ce2e5fd04fadf13b61bf6a36":
        raise ValueError("Previously published October 13 CSV changed; can't score")
    dataset=list(csv.DictReader(path.open(encoding="utf-8-sig",newline="")))
    actual=verified_results(fixtures())
    game=[x for x in dataset if x["date"]=="2026-10-20"]
    if len(game)!=9 or any(x["status"]!="PREDICTION" for x in game):
        raise ValueError("Missing genuinely old round 3 predictions")
    results=[]
    for row in game:
        key=(row["date"],row["home"],row["away"])
        goals=actual.get(key)
        if not goals:raise ValueError("Missing independently authenticated final")
        outcome="home" if goals[0]>goals[1] else "away" if goals[0]<goals[1] else "draw"
        probs={k:float(row[k+"_probability"]) for k in OUTCOMES}
        if abs(sum(probs.values())-1)>.00001:raise ValueError("Probability normalization error")
        results.append({"home":row["home"],"away":row["away"],
            "score":list(goals),"pick":row["pick"],
            "correct":row["pick"]==outcome,
            "log_loss":-math.log(max(1e-12,probs[outcome])),
            "brier":sum((probs[k]-int(k==outcome))**2 for k in OUTCOMES),
            "modal_exact_hit":row["modal_scoreline"]==f"{goals[0]}-{goals[1]}",
            "random_sample_exact_hit":row["scenario_scoreline"]==f"{goals[0]}-{goals[1]}",
            "p_draw":probs["draw"],"predicted_goals":
                 float(row["score_lambda_home"])+float(row["score_lambda_away"])})
    n=len(results)
    return {"status":"genuinely_prepublished_20261013_not_retrospective",
            "model":"ucl-pot-prior-domestic-xgq-dc-20261013",
            "original_commit":"dd30c640234223e36869eed3707ee95433cd15f2",
            "original_csv_blob_sha":blob,
            "source_results":"UEFA official",
            "date":"2026-10-20","matches":n,
            "correct":sum(x["correct"] for x in results),
            "accuracy_pct":round(100*sum(x["correct"] for x in results)/n,3),
            "actual_draws":sum(x["score"][0]==x["score"][1] for x in results),
            "draw_picks":sum(x["pick"]=="draw" for x in results),
            "correct_draw_picks":sum(x["pick"]=="draw" and x["score"][0]==x["score"][1] for x in results),
            "log_loss":round(sum(x["log_loss"] for x in results)/n,6),
            "brier":round(sum(x["brier"] for x in results)/n,6),
            "modal_exact_correct":sum(x["modal_exact_hit"] for x in results),
            "random_sample_exact_correct":sum(x["random_sample_exact_hit"] for x in results),
            "actual_total_goals":sum(sum(x["score"]) for x in results),
            "expected_total_goals":round(sum(x["predicted_goals"] for x in results),3),
            "games":results}

def main():
    import argparse
    p=argparse.ArgumentParser()
    p.add_argument("action",choices=("freeze","grade","oct20-audit"))
    a=p.parse_args()
    db=D1()
    if a.action=="freeze":result=freeze(db)
    elif a.action=="grade":result=grade(db)
    else:
        result=assess_oct20()
        db.query("INSERT OR REPLACE INTO metadata(k,v) VALUES(?,?)",
                 (AUDIT_KEY,json.dumps(result,separators=(",",":"),ensure_ascii=False)))
    # Never publish private D1 or provider-derived team-level form.
    if a.action=="oct20-audit":
        result={k:v for k,v in result.items() if k!="games"}
    print(json.dumps(result,ensure_ascii=False,sort_keys=True))
    return result

if __name__=="__main__":
    main()
