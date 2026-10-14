"""Penniless multi-source sampling manifest: no guessed xG or unauthorized scraping.

Run automatically in GitHub Actions; provider 365 live mode is separately
opt-in and limited to a previously verified match ID. This manifest checks
free public datasets without publishing raw shot-event data.
"""
import json,urllib.request,urllib.error
from pathlib import Path
SOURCES={
 "statsbomb_competitions":"https://raw.githubusercontent.com/statsbomb/open-data/master/data/competitions.json",
 "openfootball_ucl":"https://raw.githubusercontent.com/openfootball/football.json/master/2025-26/en.1.json",
 "international_results":"https://raw.githubusercontent.com/martj42/international_results/master/results.csv",
}
def run():
 out={"cost_gbp":0,"provider365_live_requests":0,"data_sources":{},"xgq_usable_matches":0,
      "note":"Source reachability only; no event-level xG completeness claimed"}
 for name,url in SOURCES.items():
  result={"status":"unavailable"}
  try:
   req=urllib.request.Request(url,headers={"User-Agent":"PennilessXGQ-Research/1.0"})
   with urllib.request.urlopen(req,timeout=12) as response:
    sample=response.read(1024*1024+1)
    result={"status":"reachable","bytes_sampled":min(len(sample),1024*1024),
            "truncated":len(sample)>1024*1024,"http_status":response.status}
    if name=="statsbomb_competitions" and not result["truncated"]:
     competitions=json.loads(sample)
     result["competitions_records"]=len(competitions)
  except (urllib.error.URLError,TimeoutError,ValueError,OSError) as exc:
   result={"status":"unavailable","reason":type(exc).__name__}
  out["data_sources"][name]=result
 path=Path("research/reports/penniless_multisource_probe.json")
 path.parent.mkdir(parents=True,exist_ok=True)
 path.write_text(json.dumps(out,indent=2,ensure_ascii=False)+"\n")
 print(json.dumps(out,ensure_ascii=False))
if __name__=="__main__":run()
