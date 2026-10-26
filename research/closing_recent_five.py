"""Exact 23-25 Oct 2026 closing-odds archive coverage audit for Penniless.

The match list is already independently verified in the private project audit.
A market result is eligible only if date, league, home and away are unambiguous
AND the listed final score exactly matches the archived score.

Never replace unknown closing prices with opening prices or reconstruct them.
Only compare on matches that truly have a complete set of AvgCH/D/A.
"""
from __future__ import annotations
import json
from collections import defaultdict
from urllib.request import Request,urlopen
from engine.market_closing_benchmark import LEAGUES,market_csv,match_market,norm

FIXTURES="2026-10-23|de.1|VfB Stuttgart|Borussia M.Gladbach|2|3\n2026-10-23|en.1|Ipswich|Nottingham Forest|1|1\n2026-10-23|es.1|Alaves|Malaga|1|1\n2026-10-23|fr.1|Brest|Nice|1|2\n2026-10-23|it.1|Torino|Monza|3|2\n2026-10-24|de.1|Augsburg|Union Berlin|1|1\n2026-10-24|de.1|Borussia Dortmund|Eintracht Frankfurt|1|0\n2026-10-24|de.1|FC Cologne|Schalke 04|0|0\n2026-10-24|de.1|Mainz 05|Werder Bremen|2|3\n2026-10-24|de.1|Paderborn|Hamburger SV|1|0\n2026-10-24|de.1|RasenBallsport Leipzig|Elversberg|4|0\n2026-10-24|en.1|Aston Villa|Manchester City|2|1\n2026-10-24|en.1|Coventry|Fulham|0|1\n2026-10-24|en.1|Arsenal|Everton|2|0\n2026-10-24|en.1|Chelsea|Tottenham|0|2\n2026-10-24|es.1|Atletico Madrid|Deportivo La Coruna|1|0\n2026-10-24|es.1|Racing Santander|Espanyol|2|1\n2026-10-24|es.1|Rayo Vallecano|Elche|0|3\n2026-10-24|es.1|Valencia|Villarreal|1|2\n2026-10-24|fr.1|Lens|Paris FC|2|1\n2026-10-24|fr.1|Toulouse|Troyes|0|0\n2026-10-24|it.1|Cagliari|Bologna|0|2\n2026-10-24|it.1|Como|Sassuolo|2|0\n2026-10-24|it.1|Lazio|Parma Calcio 1913|2|1\n2026-10-24|it.1|Napoli|Roma|3|3\n2026-10-25|de.1|Freiburg|Bayern Munich|1|3\n2026-10-25|de.1|Hoffenheim|Bayer Leverkusen|3|0\n2026-10-25|en.1|Liverpool|Brighton|2|0\n2026-10-25|en.1|Manchester United|Bournemouth|0|3\n2026-10-25|en.1|Crystal Palace|Newcastle United|0|2\n2026-10-25|en.1|Hull|Brentford|1|1\n2026-10-25|en.1|Sunderland|Leeds|0|0\n2026-10-25|es.1|Athletic Club|Getafe|4|0\n2026-10-25|es.1|Celta Vigo|Real Betis|0|0\n2026-10-25|es.1|Barcelona|Real Madrid|1|2\n2026-10-25|es.1|Real Sociedad|Levante|2|1\n2026-10-25|fr.1|Angers|Lorient|0|0\n2026-10-25|fr.1|Auxerre|Le Mans|1|1\n2026-10-25|fr.1|Marseille|Le Havre|4|3\n2026-10-25|fr.1|Monaco|Lille|1|1\n2026-10-25|fr.1|Rennes|Strasbourg|3|0\n2026-10-25|it.1|Atalanta|Frosinone|4|4\n2026-10-25|it.1|Genoa|Venezia|1|0\n2026-10-25|it.1|Inter|Fiorentina|2|1\n2026-10-25|it.1|Lecce|Juventus|0|2\n2026-10-25|it.1|Udinese|AC Milan|0|2"
def main():
    fixed=[]
    for line in FIXTURES.splitlines():
        date,league,h,a,hg,ag=line.split("|")
        fixed.append({"date":date,"league":league,"home":h,"away":a,
                      "home_goals":int(hg),"away_goals":int(ag),
                      "actual":"home" if int(hg)>int(ag) else "away" if int(hg)<int(ag) else "draw",
                      "models":{}})
    assert len(fixed)==46
    market=[];down=[]
    for league,div in LEAGUES.items():
        url=f"https://www.football-data.co.uk/mmz4281/2627/{div}.csv"
        try:
            req=Request(url,headers={"User-Agent":"Mozilla/5.0 (compatible; research-closing-archive-audit/1.0)","Accept":"text/csv,*/*"})
            with urlopen(req,timeout=14) as response:
                text=response.read().decode("utf-8-sig",errors="replace")
            parsed=market_csv(text,league)
            market.extend(parsed)
            recent=[r for r in parsed if "2026-10-23"<=r["date"]<="2026-10-25"]
            down.append({"league":league,"total":len(parsed),"recent":len(recent),"closing_odds_rows":sum("closing_market_average" in r["probs"] for r in recent),"status":"fetched"})
        except Exception as err:
            down.append({"league":league,"status":"not_retrievable","reason":type(err).__name__+":"+str(err)[:120]})
    paired,join=match_market(fixed,market,{})
    eligible=[p for p in paired if "closing_market_average" in p["models"]]
    def aggregate(subset,m):
        n=len(subset);correct=0;draw=0;logloss=0.;brier=0.
        for r in subset:
            p=r["models"][m]
            pick=max(("home","draw","away"),key=lambda x:p[x])
            correct+=int(pick==r["actual"])
            draw+=int(pick=="draw")
            logloss+=-__import__("math").log(max(p[r["actual"]],1e-12))
            brier+=sum((p[k]-(k==r["actual"]))**2 for k in ("home","draw","away"))
        return {"n":n,"correct":correct,"accuracy_pct":round(100*correct/n,3) if n else None,"draw_picks":draw,
                "log_loss":round(logloss/n,5) if n else None,"brier":round(brier/n,5) if n else None}
    available={m:[r for r in paired if m in r["models"]] for m in ("closing_market_average","closing_bet365","opening_market_average")}
    result={"scope":"2026-10-23_to_2026-10-25","planned_matches":46,
            "download_coverage":down,"unambiguous_join":join,
            "market_results":{m:aggregate(v,m) for m,v in available.items()},
            "market_by_league":{lg:{m:aggregate([r for r in v if r["league"]==lg],m) for m,v in available.items()}
                 for lg in LEAGUES},
            "market_by_day":{day:{m:aggregate([r for r in v if r["date"]==day],m) for m,v in available.items()}
                 for day in ("2026-10-23","2026-10-24","2026-10-25")},
            "verified_46_sample":len(eligible)==46,
            "unmatched_closing":46-len(eligible),
            "closing_market_compared_with_DixonColes_all46_only_if_exact_sample":(
                 {"closing_pct":aggregate(eligible,"closing_market_average")["accuracy_pct"],
                  "dixon_coles_pct":47.83} if len(eligible)==46 else None)}
    print(json.dumps(result,ensure_ascii=False,sort_keys=True))
    return result
if __name__=="__main__":main()
