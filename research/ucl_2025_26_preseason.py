"""Pre-season 2025/26 UCL simulated from 15 September 2025 information only.

This is a 2026 research model rewound onto a 2025 evidence snapshot,
NOT genuine forecasts published in 2025. The 144 original league matchups
were already published before Sept 16. Future official knockout matchups are
NOT used: a stylized seeded UEFA-style knockout bracket is drawn after each
simulated 36-team league table. All trophy probabilities illustrative.
"""
from __future__ import annotations
import csv
import json
import random
from collections import Counter,defaultdict
from datetime import datetime,timezone
from pathlib import Path

from engine.understat_d1 import D1
from research.ucl_2025_26 import POT,POT_RATING,fixtures,domestic_profiles,prediction
from research.ucl_2026_27 import sample_grid,bracket

SNAPSHOT='2025-09-16'
N=3000
SEED=20250915
OUT=Path(__file__).resolve().parent/'reports'/'ucl2025_26'


def table(scores):
 results={team:{'team':team,'Pts':0,'GF':0,'GA':0,'GD':0} for team in POT}
 for game,goals in scores:
  a,b=goals
  h=results[game['home']];v=results[game['away']]
  h['GF']+=a;h['GA']+=b
  v['GF']+=b;v['GA']+=a
  if a>b:h['Pts']+=3
  elif a<b:v['Pts']+=3
  else:h['Pts']+=1;v['Pts']+=1
 for r in results.values():r['GD']=r['GF']-r['GA']
 return sorted(results.values(),key=lambda r:(-r['Pts'],-r['GD'],-r['GF'],r['team']))


def main():
 fixtures_=fixtures()
 # Fixed before the start of the tournament; future UCL scores NOT included.
 league=[g for g in fixtures_ if g['phase'].startswith('League')]
 if len(league)!=144 or any(g['date']<SNAPSHOT for g in league):
  raise ValueError('Invalid preseason draw')
 history=D1().history()
 form,count=domestic_profiles(history,SNAPSHOT)
 rating={t:float(POT_RATING[POT[t]]) for t in POT}
 grids={g['id']:prediction(g,rating,form)['matrices']['xgq_shots_stage1']
        for g in league}
 # All 36*35 hypothetical venues/teams are priced before seeing any
 # result of this season. Knockout matchups are CONDITIONAL from simulated
 # final Swiss-style league ranks, not the known historical bracket.
 models={}
 for h in POT:
  for a in POT:
   if h==a:continue
   pr=prediction({'home':h,'away':a,'phase':'League'},rating,form)
   models[(h,a)]={'grid':pr['matrices']['xgq_shots_stage1'],
                  'lambda_home':pr['goals_expected_adjusted'][0]}
 rng=random.Random(SEED)
 ranks={t:Counter() for t in POT}
 scoreTotals=defaultdict(float)
 champions=Counter()
 finalMade=Counter()
 seeds8=Counter()
 seeds24=Counter()
 for _ in range(N):
  simulated=[(g,sample_grid(grids[g['id']],rng)) for g in league]
  standings=table(simulated)
  for i,t in enumerate(standings,1):
   team=t['team'];ranks[team][i]+=1;scoreTotals[team]+=t['Pts']
   if i<=8:seeds8[team]+=1
   if i<=24:seeds24[team]+=1
  p16,r16,qf,semi,win=bracket(standings,models,rng)
  for finalist in semi:finalMade[finalist]+=1
  champions[win]+=1
 outcomes=[]
 for team in POT:
  dist=ranks[team]
  positions=[i for i in range(1,37) for _ in range(dist[i])]
  outcomes.append({
   'team':team,'pot':POT[team],
   'expected_points':round(scoreTotals[team]/N,4),
   'top8':round(seeds8[team]/N,5),'top24':round(seeds24[team]/N,5),
   'final':round(finalMade[team]/N,5),'champion':round(champions[team]/N,5),
   'rank_mean':round(sum(i*cnt for i,cnt in dist.items())/N,3),
   'rank_ci90':[positions[int(.05*(N-1))],positions[int(.95*(N-1))]]
  })
 outcomes.sort(key=lambda r:(-r['expected_points'],r['team']))
 topChamps=sorted(outcomes,key=lambda r:-r['champion'])
 report={
  'status':'PRESEASON_REWIND_USING_AFTER_SEASON_MODEL_COEFFICIENTS',
  'cutoff':SNAPSHOT,'model_parameters_from_later_research':True,
  'historical_fixtures_used_as_known_in_august_2025':144,
  'future_results_used':0,'future_knockout_opponents_used':0,
  'actual_season_title_winner':'PSG',
  'target':'league Swiss table and hypothetical playoff/title odds',
  'simulations':N,'domestic_matches_before_start':count,
  'teams_with_authentic_prestart_domestic_form':len(form),
  'clubs_without_5_prior_domestic_shot_games':sorted(set(POT)-set(form)),
  'champion_favorites':[{'team':z['team'],'prob':z['champion']}
                        for z in topChamps[:15]],
  'paris_title_chance':next(z['champion'] for z in outcomes if z['team']=='PSG'),
  'expected_league_table':outcomes,
  'source_of_real_results':'https://github.com/openfootball/champions-league/blob/master/2025-26/cl.txt',
  'generated_at_utc':datetime.now(timezone.utc).isoformat(),
 }
 assert abs(sum(z['champion'] for z in outcomes)-1)<.001
 assert len(outcomes)==36
 OUT.mkdir(parents=True,exist_ok=True)
 (OUT/'ucl_2025_26_preseason_sim.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
 with (OUT/'ucl_2025_26_preseason_table.csv').open('w',encoding='utf-8-sig',newline='') as fh:
  writer=csv.DictWriter(fh,fieldnames=('team','pot','expected_points','top8','top24','final','champion','rank_mean','rank_ci90'))
  writer.writeheader();writer.writerows(outcomes)
 print(json.dumps({'preseason_snapshot':SNAPSHOT,'simulations':N,'historical_prestart_shot_matches':count,
   'teams_with_domestic_form':len(form),'top_titles':report['champion_favorites'][:10],
   'actual_PSG_title_chance':report['paris_title_chance']},sort_keys=True))
 return report


if __name__=='__main__':
 main()
