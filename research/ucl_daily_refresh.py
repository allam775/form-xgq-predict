"""Daily *post-matchday* roll-forward of the original 2026/27 UCL model.

Verified scores are immutable and added only for scheduled UEFA fixture IDs,
never guessed from team names, 365Score XG/shot availability or live events.
The old Oct 13 full-season forecast stays untouched. A new time-stamped
snapshot is generated only after ALL games on a scheduled day are certified.
No same-day/future result is allowed into the future projection.

Stats: match-level original prepublished 1X2 vs final scores, independent
rolling current European ratings, real current Swiss standings, simulated
top8/top24/knockout/title odds and expected points.
"""
from __future__ import annotations
from collections import Counter, defaultdict
from datetime import datetime, date, timezone, timedelta
from hashlib import sha256
from itertools import groupby
import csv, json, math, os, re, unicodedata

from engine.understat_d1 import D1
from engine.provider365 import fetch as provider_fetch, _side, _score, _final, _competition, _date
from engine.coverage365 import _games
from engine.competition365 import resolve as resolve_competition, canonical
from research.ucl_forward import (
    fixtures, verified_results, rating_at, assess_oct20, SOURCE, EXISTING
)
from research.ucl_2026_27 import (
    TEAM_NAMES, POTS, calc, profiles, precompute_all,
    simulation, score_table, SEED, REPS
)

TABLE="private_ucl_confirmed_finals_2026_27"
SNAPSHOTS="private_ucl_daily_snapshots_2026_27"
LATEST="penniless_ucl_rolling_latest"
MAX_DAYS=3
OUTCOMES=("home","draw","away")
CLUB_ALIASES={
 "aek athens":"AEK","aek":"AEK",
 "atletico de madrid":"Atletico Madrid","atletico madrid":"Atletico Madrid",
 "as roma":"Roma","roma":"Roma",
 "paris saint germain":"PSG","paris sg":"PSG","psg":"PSG",
 "borussia dortmund":"Dortmund","dortmund":"Dortmund",
 "bodoe glimt":"Bodo Glimt","bodo glimt":"Bodo Glimt",
 "bodo glimt fk":"Bodo Glimt",
 "fc barcelona":"Barcelona","barcelona":"Barcelona",
 "fc porto":"Porto","porto":"Porto",
 "psv eindhoven":"PSV","psv":"PSV",
 "fc bayern munich":"Bayern Munich","bayern munchen":"Bayern Munich",
 "bayern munich":"Bayern Munich",
 "liverpool fc":"Liverpool","liverpool":"Liverpool",
 "manchester city":"Manchester City","man city":"Manchester City",
 "manchester united":"Manchester United","man united":"Manchester United",
 "fc internazionale":"Inter","inter milano":"Inter","inter":"Inter",
 "real madrid cf":"Real Madrid","real madrid":"Real Madrid",
 "r b leipzig":"RB Leipzig","rb leipzig":"RB Leipzig",
 "rasenballsport leipzig":"RB Leipzig",
 "vfb stuttgart":"Stuttgart","stuttgart":"Stuttgart",
 "slovan bratislava":"Slovan Bratislava","sk slovan bratislava":"Slovan Bratislava",
 "slavia prague":"Slavia Prague","slavia praha":"Slavia Prague",
 "fenerbahce istanbul":"Fenerbahce","fenerbahce":"Fenerbahce",
 "sabah masazir":"Sabah","sabah fk":"Sabah","sabah":"Sabah",
 "galatasaray istanbul":"Galatasaray","galatasaray":"Galatasaray",
 "sporting cp":"Sporting CP","sporting lisbon":"Sporting CP",
 "lask linz":"LASK","lask":"LASK",
 "club brugge":"Club Brugge","club brugge kv":"Club Brugge",
 "aston villa":"Aston Villa","aston villa fc":"Aston Villa",
 "como 1907":"Como","como":"Como",
 "villarreal cf":"Villarreal","villarreal":"Villarreal",
 "ssc napoli":"Napoli","napoli":"Napoli",
 "lille osc":"Lille","lille":"Lille",
 "racing club de lens":"Lens","rc lens":"Lens","lens":"Lens",
 "shakhtar donetsk":"Shakhtar Donetsk","fc shakhtar donetsk":"Shakhtar Donetsk",
 "real betis":"Real Betis","real betis balompie":"Real Betis",
 "feyenoord rotterdam":"Feyenoord","feyenoord":"Feyenoord",
 "viking fk":"Viking","viking":"Viking",
}
CANON={canonical(t):t for t in TEAM_NAMES}
def club_name(text):
    k=canonical(text)
    return CLUB_ALIASES.get(k,CANON.get(k))

def _valid_date(s):
    return date.fromisoformat(s).isoformat()

def fetch_365_results(day, schedule, *, fetcher=provider_fetch):
    """One authorized, bounded, provider-date request. Fail closed on every mismatch."""
    _valid_date(day)
    wanted={(m["home"],m["away"]):m for m in schedule if m["date"]==day}
    if not wanted:return {},{"date":day,"wanted":0}
    iso=date.fromisoformat(day).strftime("%d/%m/%Y")
    raw=fetcher("games/allscores/",{"sports":"1","startDate":iso,"endDate":iso,
         "onlyMajorGames":"false","withTop":"false"})
    games=_games(raw) # detects pagination/truncation, bound all matches
    verified={}
    counts=Counter()
    counts["requested"]=len(wanted)
    for item in games:
        cid,_,_= _competition(item)
        if cid!="572":continue
        check=resolve_competition({**raw,"game":item} if isinstance(raw,dict) else item,
                                  expected_leagues={"uefa.cl"})
        if not check["ok"]:
            counts["unverified_competition"]+=1
            continue
        # Provider status parsers can otherwise mistake "not final" for "final".
        status_text=" ".join(str(v.get("name") or v.get("description") or "") if isinstance(v,dict) else str(v or "")
           for v in (item.get("status"),item.get("statusText"),item.get("statusName"),
                     item.get("gameStatus"),item.get("shortStatusText"))).casefold()
        if (any(term in status_text for term in ("not final","not finished","not ended",
                "scheduled","upcoming","postponed","in progress","live","half time"))
                or not _final(item)):
            counts["not_final"]+=1;continue
        try:
            seen_day=_date(item)
            h=_side(item,"home");a=_side(item,"away")
            home=club_name(h.get("name") or h.get("title") or h.get("displayName"))
            away=club_name(a.get("name") or a.get("title") or a.get("displayName"))
            if seen_day!=day or home is None or away is None or (home,away) not in wanted:
                counts["unmatched_identity"]+=1;continue
            hg=_score(item,"home",h);ag=_score(item,"away",a)
            if type(hg)!=int or type(ag)!=int or not 0<=hg<=30 or not 0<=ag<=30:
                counts["invalid_scores"]+=1;continue
            key=(day,home,away)
            if key in verified and verified[key]!=(hg,ag):
                raise ValueError("Conflicting final scores within same provider daily scan")
            verified[key]=(hg,ag)
        except (KeyError,ValueError,TypeError) as exc:
            counts["invalid_result"]+=1
    counts["verified"]=len(verified)
    return verified,dict(counts)

def ensure_tables(db):
    db.query(f"CREATE TABLE IF NOT EXISTS {TABLE} (id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
    db.query(f"CREATE TABLE IF NOT EXISTS {SNAPSHOTS} (id TEXT PRIMARY KEY, payload TEXT NOT NULL)")

def observed(db,schedule):
    known=verified_results(schedule)
    all_ids={(m["date"],m["home"],m["away"]):m for m in schedule}
    for page in range(40):
        batch=db.query(f"SELECT payload FROM {TABLE} ORDER BY id LIMIT 100 OFFSET ?",(page*100,))
        if not batch:break
        for x in batch:
            row=json.loads(x["payload"])
            key=(row["date"],row["home"],row["away"])
            if key not in all_ids or row.get("competition")!="uefa.cl" or row.get("status")!="certified_final":
                raise ValueError("Invalid stored UEFA outcome identity")
            val=(row["hg"],row["ag"])
            if (not all(type(v)==int and 0<=v<=30 for v in val)
                or (key in known and known[key]!=val)):
                raise ValueError("Conflicting historical UCL result")
            known[key]=val
        if len(batch)<100:break
    return known

def ingest(db,schedule, *, now=None,fetcher=provider_fetch):
    now=now or datetime.now(timezone.utc)
    if now.tzinfo is None:raise ValueError("Date must be timezone-aware")
    now=now.astimezone(timezone.utc)
    if os.getenv("XGQ_365_ACCESS_AUTHORIZED")!="1" or os.getenv("XGQ_365_PRIVATE_ONLY")!="1":
        return {"status":"source_disabled","added":0}
    known=observed(db,schedule)
    # Only ask for dates whose full event day is already over in UTC.
    groups=defaultdict(list)
    for m in schedule:
        key=(m["date"],m["home"],m["away"])
        if m["date"]<now.date().isoformat() and key not in known:
            groups[m["date"]].append(m)
    counts=Counter()
    audit=[]
    for day in sorted(groups,reverse=True)[:MAX_DAYS]:
        received,diag=fetch_365_results(day,schedule,fetcher=fetcher)
        audit.append(diag)
        for key,val in received.items():
            if key in known:
                if known[key]!=val:raise ValueError("365Scores final differs from previously certified UEFA score")
                continue
            record={"date":key[0],"home":key[1],"away":key[2],
                "hg":val[0],"ag":val[1],"competition":"uefa.cl",
                "status":"certified_final","source":"365Scores final+explicit competition id 572 + exact UEFA fixture",
                "recorded_at_utc":now.isoformat()}
            identity="|".join(key)
            db.query(f"INSERT OR IGNORE INTO {TABLE}(id,payload) VALUES (?,?)",
                     (identity,json.dumps(record,ensure_ascii=False,separators=(",",":"))))
            known[key]=val
            counts["added"]+=1
    return {"status":"scanned","added":counts["added"],"days":audit}

def completed_day(schedule,known,*,today):
    by_day=defaultdict(list)
    for m in schedule:by_day[m["date"]].append(m)
    eligible=[]
    for day,group in sorted(by_day.items()):
        if day>=today:break
        if all((m["date"],m["home"],m["away"]) in known for m in group):
            eligible.append(day)
        else:
            break # never project past a day with missing certified results
    return eligible[-1] if eligible else None

def historical_published_scores(known,*,asof):
    """No retro-replay: score the immutable Oct13 144-fixture prediction file."""
    original=assess_oct20.__globals__["EXISTING"]
    results=[]
    rows=list(csv.DictReader(original.open(encoding="utf-8-sig",newline="")))
    for row in rows:
        if row["status"]!="PREDICTION":continue # MD1 was observed, not predicted
        if row["date"]>asof:continue
        key=(row["date"],row["home"],row["away"])
        if key not in known:continue
        hg,ag=known[key]
        outcome="home" if hg>ag else "away" if hg<ag else "draw"
        p={k:float(row[k+"_probability"]) for k in OUTCOMES}
        if abs(sum(p.values())-1)>.00001:raise ValueError("Old odds corrupted")
        if row["pick"] != max(OUTCOMES,key=lambda k:p[k]):
            raise ValueError("Original 1X2 pick disagrees with original forecast")
        results.append({"date":row["date"],"model_pick":row["pick"],
            "correct":row["pick"]==outcome,"outcome":outcome,
            "logloss":-math.log(max(p[outcome],1e-12)),
            "brier":sum((p[k]-int(k==outcome))**2 for k in OUTCOMES)})
    def aggregate(v):
        n=len(v)
        if not n:return {"n":0}
        return {"n":n,"correct":sum(x["correct"] for x in v),
            "accuracy_pct":round(100*sum(x["correct"] for x in v)/n,3),
            "actual_draws":sum(x["outcome"]=="draw" for x in v),
            "draw_predictions":sum(x["model_pick"]=="draw" for x in v),
            "log_loss":round(sum(x["logloss"] for x in v)/n,6),
            "brier":round(sum(x["brier"] for x in v)/n,6)}
    return {"cumulative":aggregate(results),
            "by_day":{day:aggregate([x for x in results if x["date"]==day])
                     for day in sorted({x["date"] for x in results})}}

def projection(schedule,known,history,*,asof,reps=2400):
    """Replace finished fixtures with official scores; all remaining are simulated."""
    _valid_date(asof)
    cutoff=(date.fromisoformat(asof)+timedelta(days=1)).isoformat()
    if any(day>asof for day,h,a in known if day in {m["date"] for m in schedule}):
        # Caller must explicitly filter; future approved outcomes are never used.
        known={key:val for key,val in known.items() if key[0]<=asof}
    ratings=rating_at(schedule,known,before=cutoff)
    forms,base,historical_n=profiles(history,cutoff=cutoff)
    ready=[]
    forecast={}
    played=[]
    for match in schedule:
        m={**match}
        key=(m["date"],m["home"],m["away"])
        if key in known:
            m["actual"]=known[key]
            played.append({"home":m["home"],"away":m["away"],"actual":known[key]})
        else:
            m["actual"]=None
        ready.append(m)
        forecast[m["id"]]=calc(m,ratings,forms)
    if len(played)==len(ready):raise ValueError("Cannot update projection after entire 144 fixture season")
    candidates=precompute_all(TEAM_NAMES,ratings,forms)
    monte=simulation(ready,forecast,[],candidates,reps=reps)
    real_table=score_table([{"home":m["home"],"away":m["away"],"result":m["actual"]}
           for m in ready if m["actual"] is not None],"result")
    favorites=sorted(monte.items(),key=lambda x:-x[1]["champion"])
    expected=sorted(monte.items(),key=lambda x:-x[1]["expected_points"])
    scores=historical_published_scores(known,asof=asof)
    return {"asof_completed_date":asof,
        "model":"ucl-pot-prior-domestic-xgq-dc-rollforward-v1",
        "status":"snapshot_complete_verified_day_no_original_forecast_mutation",
        "results_verified":len(played),"fixtures_total":len(ready),
        "remaining_to_simulate":len(ready)-len(played),
        "model_inputs":{"domestic_understat_strictly_before":cutoff,
                        "official_ucl_scores_through":asof,
                        "historical_domestic_matches":historical_n,
                        "monte_carlo_repetitions":reps,
                        "uefa_pot_priors_assumptions_not_observed_elos":True,
                        "knockout_bracket_is_illustrative":True},
        "original_oct13_frozen_evaluation":scores,
        "real_league_table":real_table,
        "champion_probabilities":[
           {"team":t,"champion_pct":round(v["champion"]*100,2),
            "top8_pct":round(v["top8"]*100,2),
            "top24_pct":round(v["top24"]*100,2),
            "expected_points":round(v["expected_points"],2),
            "mean_rank":round(v["mean_rank"],2)}
            for t,v in favorites],
        "expected_standings":[
           {"team":t,"expected_points":round(v["expected_points"],2),
            "top8_pct":round(v["top8"]*100,2),"top24_pct":round(v["top24"]*100,2),
            "champion_pct":round(v["champion"]*100,2)}
           for t,v in expected],
    }

def refresh(db,*,now=None,reps=2400,ingest_scores=True,fetcher=provider_fetch):
    now=now or datetime.now(timezone.utc)
    now=now.astimezone(timezone.utc)
    ensure_tables(db)
    schedule=fixtures()
    pulls=ingest(db,schedule,now=now,fetcher=fetcher) if ingest_scores else {"status":"skipped"}
    known=observed(db,schedule)
    asof=completed_day(schedule,known,today=now.date().isoformat())
    if not asof:return {"status":"no_complete_matchday","ingestion":pulls}
    counted=[(k,v) for k,v in sorted(known.items()) if k[0]<=asof]
    digest=sha256(json.dumps(counted,sort_keys=True).encode()).hexdigest()[:16]
    key=f"{asof}|{digest}"
    old=db.query(f"SELECT id FROM {SNAPSHOTS} WHERE id=?",(key,))
    if old:
        # Avoid changing historical odds/standings on later unrelated days.
        return {"status":"already_snapshotted","asof":asof,"ingestion":pulls,
                "snapshot_id":key}
    result=projection(schedule,known,db.history(),asof=asof,reps=reps)
    result["snapshot_id"]=key
    result["created_at_utc"]=now.isoformat()
    db.query(f"INSERT OR IGNORE INTO {SNAPSHOTS}(id,payload) VALUES (?,?)",
             (key,json.dumps(result,ensure_ascii=False,separators=(",",":"))))
    db.query("INSERT OR REPLACE INTO metadata(k,v) VALUES (?,?)",
             (LATEST,json.dumps({"snapshot_id":key,"asof":asof,
                "n_results":result["results_verified"],
                "original_metrics":result["original_oct13_frozen_evaluation"]["cumulative"],
                "top_champion":result["champion_probabilities"][:12],
                "top_expected":result["expected_standings"][:12],
                "created_at_utc":now.isoformat()},ensure_ascii=False,separators=(",",":"))))
    return {"status":"new_snapshot","asof":asof,"snapshot_id":key,
            "results_verified":result["results_verified"],
            "remaining":result["remaining_to_simulate"],
            "original_metrics":result["original_oct13_frozen_evaluation"]["cumulative"],
            "top_champion":result["champion_probabilities"][:10],
            "top_expected_points":result["expected_standings"][:10],
            "ingestion":pulls}

def main():
    db=D1()
    out=refresh(db)
    # Aggregated, safe report only.
    print(json.dumps(out,ensure_ascii=False,sort_keys=True))
    return out

if __name__=="__main__":main()
