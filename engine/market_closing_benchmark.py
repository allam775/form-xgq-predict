"""Retrospective football-data.co.uk closing-odds market versus Penniless.

Only verified score/league/date/home/away joins. Store aggregate metrics
privately in D1; never redistribute bookmaker rows or historical Understat
match-level model predictions. Research, not financial advice.
"""
from __future__ import annotations

import csv
from collections import Counter, defaultdict
from datetime import date,datetime,timezone
from difflib import SequenceMatcher
from io import StringIO
import json
import math
import re
import unicodedata
from urllib.request import Request, urlopen

from .comprehensive import _dated_replay,ensemble,APPROVED_PARAMS
from .draw_lab import apply_draw_calibration,feature_vector,FROZEN_DRAW_WEIGHTS
from .full_archive_benchmark import _evaluate,MODELS
from .understat_d1 import D1

LEAGUES={"en.1":"E0","de.1":"D1","it.1":"I1","es.1":"SP1","fr.1":"F1"}
SEASONS=("2223","2324","2425","2526","2627")
KEY="penniless_commercial_market_same_matches_20261018"
OUTCOMES=("home","draw","away")
MARKETS={
    "closing_market_average":("AvgCH","AvgCD","AvgCA"),
    "opening_market_average":("AvgH","AvgD","AvgA"),
    "closing_bet365":("B365CH","B365CD","B365CA"),
}
ALIAS={
    "man united":"manchester united","man utd":"manchester united",
    "man city":"manchester city","wolves":"wolverhampton wanderers",
    "newcastle":"newcastle united","west ham":"west ham united",
    "spurs":"tottenham hotspur","tottenham":"tottenham hotspur",
    "nott m forest":"nottingham forest","nottm forest":"nottingham forest",
    "brighton":"brighton and hove albion","bournemouth":"bournemouth",
    "afc bournemouth":"bournemouth","leicester":"leicester city",
    "sheffield united":"sheffield united","sheffield utd":"sheffield united",
    "ipswich":"ipswich town","hull":"hull city","leeds":"leeds united",
    "cardiff":"cardiff city","norwich":"norwich city",
    "stoke":"stoke city",
    "bayern munich":"bayern munich","bayern":"bayern munich",
    "dortmund":"borussia dortmund","rb leipzig":"rasenballsport leipzig",
    "leipzig":"rasenballsport leipzig",
    "m gladbach":"borussia monchengladbach","gladbach":"borussia monchengladbach",
    "ein frankfurt":"eintracht frankfurt","frankfurt":"eintracht frankfurt",
    "leverkusen":"bayer leverkusen","cologne":"koln",
    "fc koln":"koln","koln":"koln","hertha":"hertha berlin",
    "mainz":"mainz 05","mainz 05":"mainz 05",
    "hoffenheim":"tsg hoffenheim","augsburg":"augsburg",
    "st pauli":"st pauli","freiburg":"freiburg",
    "stuttgart":"vfb stuttgart","vfb stuttgart":"vfb stuttgart",
    "bochum":"vfl bochum","vfl bochum":"vfl bochum",
    "wolfsburg":"vfl wolfsburg","vfl wolfsburg":"vfl wolfsburg",
    "borussia m gladbach":"borussia monchengladbach",
    "borussia monchengladbach":"borussia monchengladbach",
    "hamburg":"hamburger sv","holstein kiel":"holstein kiel",
    "kiel":"holstein kiel",
    "ath madrid":"atletico madrid","atletico":"atletico madrid",
    "ath bilbao":"athletic club","athletic bilbao":"athletic club",
    "betis":"real betis","sociedad":"real sociedad",
    "celta":"celta vigo","vallecano":"rayo vallecano",
    "alaves":"deportivo alaves","valladolid":"real valladolid",
    "granada":"granada","osasuna":"osasuna",
    "ac milan":"milan","milan":"milan","inter milan":"inter",
    "as roma":"roma","roma":"roma",
    "verona":"hellas verona","parma":"parma calcio 1913",
    "paris sg":"paris saint germain","psg":"paris saint germain",
    "marseille":"olympique marseille","lyon":"olympique lyonnais",
    "st etienne":"saint etienne","monaco":"as monaco",
    "rennes":"stade rennais","reims":"stade de reims",
    "clermont":"clermont foot","lorient":"lorient",
    "strasbourg":"strasbourg","montpellier":"montpellier",
    "lens":"lens","brest":"brest","troyes":"troyes",
}
def norm(name):
    x=unicodedata.normalize("NFKD",str(name or "").casefold())
    x="".join(c for c in x if not unicodedata.combining(c))
    x=x.replace("&"," and ")
    x=re.sub(r"[^a-z0-9]+"," ",x).strip()
    x=re.sub(r"^(fc|afc)\s+|\s+(fc|afc)$","",x).strip()
    return ALIAS.get(x,x)

def same_team(a,b):
    x,y=norm(a),norm(b)
    if x==y:return True
    # Very narrow typo tolerance, ONLY within same league/date/final score.
    return len(x)>=5 and len(y)>=5 and SequenceMatcher(None,x,y).ratio()>=.90

def parse_date(value):
    s=(value or "").strip()
    for fmt in ("%d/%m/%Y","%d/%m/%y","%Y-%m-%d","%d-%m-%Y","%d-%m-%y"):
        try:return datetime.strptime(s,fmt).date().isoformat()
        except ValueError:pass
    return None

def no_vig(record,cols):
    vals=[]
    for col in cols:
        try:v=float(record.get(col) or "nan")
        except (TypeError,ValueError):return None
        if not math.isfinite(v) or v<=1.001 or v>1000:return None
        vals.append(1./v)
    s=sum(vals)
    if not 0.7<s<1.6:return None
    return dict(zip(OUTCOMES,[x/s for x in vals]))

def market_csv(text, league):
    reader=csv.DictReader(StringIO(text.lstrip("\ufeff").replace("\x00","")))
    output=[]
    for line in reader:
        day=parse_date(line.get("Date"))
        if not day or not line.get("HomeTeam") or not line.get("AwayTeam"):continue
        try:h,a=int(line["FTHG"]),int(line["FTAG"])
        except (ValueError,TypeError,KeyError):continue
        if not(0<=h<=20 and 0<=a<=20):continue
        probs={name:p for name,cols in MARKETS.items()
               if (p:=no_vig(line,cols)) is not None}
        output.append({"league":league,"date":day,"home":line["HomeTeam"],
            "away":line["AwayTeam"],"hg":h,"ag":a,"probs":probs})
    return output

def fetch_market(*, fetcher=None):
    if fetcher is None:
        def fetcher(url):
            req=Request(url,headers={"User-Agent":"Penniless/1.0 academic research historical football data",
                                     "Accept":"text/csv,text/plain,*/*"})
            with urlopen(req,timeout=23) as response:
                return response.read().decode("utf-8-sig",errors="replace")
    fixtures=[]
    coverage=[]
    for season in SEASONS:
        for league,division in LEAGUES.items():
            url=f"https://www.football-data.co.uk/mmz4281/{season}/{division}.csv"
            try:
                parsed=market_csv(fetcher(url),league)
                if not parsed:raise ValueError("empty_or_unparseable_csv")
                fixtures.extend(parsed)
                coverage.append({"season":season,"league":league,
                                 "downloaded":len(parsed),"status":"ok"})
            except Exception as exc:
                coverage.append({"season":season,"league":league,
                                 "status":"download_unavailable",
                                 "reason":type(exc).__name__})
    return fixtures,coverage

def match_market(evaluated,market,verified):
    """Join by exact date, league, home, away, and independent full-time score.

    No fuzzy 1-to-many links, no +/- day guessing, no score mismatches.
    """
    index=defaultdict(list)
    for row in market:
        key=(row["league"],row["date"],row["hg"],row["ag"])
        index[key].append(row)
    scores=Counter()
    matches=[]
    used_market_keys=set()
    for row in evaluated:
        key=(row["league"],row["date"],
             row["home_goals"],row["away_goals"])
        candidates=index.get(key,[])
        similar=[x for x in candidates
                 if same_team(row["home"],x["home"]) and
                    same_team(row["away"],x["away"])]
        if len(similar)!=1:
            scores["no_unambiguous_match"]+=1
            continue
        m=similar[0]
        ident=(m["league"],m["date"],norm(m["home"]),norm(m["away"]))
        if ident in used_market_keys:
            scores["market_duplicate"]+=1
            continue
        used_market_keys.add(ident)
        models=dict(row["models"])
        models.update(m["probs"])
        matches.append({"league":row["league"],"date":row["date"],
                        "actual":row["actual"],"models":models})
        scores["joined"]+=1
    return matches,dict(scores)

def report(historical,market,coverage,*,through=None):
    if not historical:raise ValueError("No verified archive")
    end=through or max(r["date"] for r in historical)
    raw=[r for r in historical if r["date"]<=end]
    start=min(r["date"] for r in raw)
    # Rebuild model features with strict previous-date boundaries.
    evaluated,withheld,_,n=_dated_replay(raw,end,eval_start=start)
    # Efficient lookup, not used in prediction feature construction.
    identities={(r["league"],r["date"],r["home"],r["away"]):r
                for r in raw}
    records=[]
    for r in evaluated:
        old=identities.get((r["league"],r["date"],r["home"],r["away"]))
        if old is None:raise ValueError("Missing Understat identity")
        comps=r["models"]
        v1=ensemble(comps,APPROVED_PARAMS)
        v2=apply_draw_calibration(v1,feature_vector(r),FROZEN_DRAW_WEIGHTS)
        models={k:comps[k] for k in
                 ("xgq","dc","elo","hybrid","stage1","stage3")}
        models.update({"comprehensive_v1":v1,"draw_v2":v2})
        records.append({"league":r["league"],"date":r["date"],
                        "home":r["home"],"away":r["away"],
                        "home_goals":old["hg"],"away_goals":old["ag"],
                        "actual":r["actual"],"models":models})
    paired,join=match_market(records,market,raw)
    result={"status":"retrospective_market_comparison",
        "source":"football-data.co.uk historical 1X2 prices",
        "archive_matches":n,"eligible_models":len(records),
        "market_download_fixtures":len(market),
        "matched_with_at_least_one_market":len(paired),
        "unmatched_eligible":len(records)-len(paired),
        "model_ineligible_reasons":withheld,"join_audit":join,
        "download_coverage":coverage,
        "comparisons":{},
        "by_league":{},
        "limitations":[
            "No match scores from Football-Data influence models; only retrospectively validate identity.",
            "Use identical games per specific commercial source. Opening and closing never mixed.",
            "Closing odds describe the pre-kickoff market, not a commercial AI model.",
            "Missing 2026/27 data and any unmatched games are excluded.",
            "Understat components and draw calibrator were developed retrospectively; never assert clean prospective success.",
            "No private fixture identities, scraped rows, or prices published in GitHub logs."],
        "generated_at_utc":datetime.now(timezone.utc).isoformat()}
    for market_name in MARKETS:
        subset=[r for r in paired if market_name in r["models"]]
        result["comparisons"][market_name]={
            "n":len(subset),
            "actual_draws":sum(r["actual"]=="draw" for r in subset),
            "models":{name:_evaluate(subset,name)
                     for name in (*MODELS,market_name)}}
        result["by_league"][market_name]={
            league:{"n":len(rows:= [r for r in subset if r["league"]==league]),
                    "models":{name:_evaluate(rows,name)
                              for name in ("stage1","stage3","draw_v2",market_name)}}
            for league in LEAGUES}
    return result

def main():
    db=D1()
    odds,coverage=fetch_market()
    j=report(db.history(),odds,coverage)
    db.query("INSERT OR REPLACE INTO metadata(k,v) VALUES(?,?)",
             (KEY,json.dumps(j,ensure_ascii=False,separators=(",",":"))))
    print(json.dumps({
        "status":j["status"],"eligible_models":j["eligible_models"],
        "archive_matches":j["archive_matches"],
        "market_download_fixtures":j["market_download_fixtures"],
        "matched":j["matched_with_at_least_one_market"],
        "source_coverage":j["download_coverage"],
        "comparisons":j["comparisons"]},sort_keys=True))
    return j

if __name__=="__main__":
    main()
