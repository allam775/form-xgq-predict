"""Retrospective 2025/26 UCL benchmark: 189 fixtures, strict pre-date features.

This is the 2026/27 UCL stage-one xG/XGQ/shot-volume scoring *adaptation*
applied to 2025/26 with the ORIGINAL 2025 UEFA draw pots and no future
Understat records. Parameters were developed AFTER this season, so this is
research replay, NEVER a prospective or independent validation claim.
Compare 90-minute 1X2, log loss, Brier, and exact score against simpler models.
UEFA match results are public; authenticated domestic shot data remain private.
"""
from __future__ import annotations

import csv
import json
import math
import random
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

from engine.understat_d1 import D1
from research.ucl_2026_27 import joint, onex2, blend, ranked_scorelines, clip

ROOT=Path(__file__).resolve().parent
IN=ROOT/'ucl2025_26_fixtures.json'
OUT=ROOT/'reports'/'ucl2025_26'
POTS={
 1:('PSG','Real Madrid','Manchester City','Bayern Munich','Liverpool',
    'Inter','Chelsea','Dortmund','Barcelona'),
 2:('Arsenal','Leverkusen','Atletico Madrid','Benfica','Atalanta','Villarreal',
    'Juventus','Frankfurt','Club Brugge'),
 3:('Tottenham','PSV','Ajax','Napoli','Sporting CP','Olympiacos','Slavia Prague',
    'Bodo Glimt','Marseille'),
 4:('Copenhagen','Monaco','Galatasaray','Union Saint Gilloise','Qarabag',
    'Athletic Club','Newcastle United','Pafos','Kairat Almaty')
}
POT={t:p for p,clubs in POTS.items() for t in clubs}
POT_RATING={1:1890,2:1780,3:1680,4:1570}
# Exact pre-date Understat labels for five eligible European domestic leagues.
DOMESTIC={
 'PSG':('fr.1','paris saint germain'),
 'Real Madrid':('es.1','real madrid'),
 'Manchester City':('en.1','manchester city'),
 'Bayern Munich':('de.1','bayern munich'),
 'Liverpool':('en.1','liverpool'),
 'Inter':('it.1','inter'),
 'Chelsea':('en.1','chelsea'),
 'Dortmund':('de.1','borussia dortmund'),
 'Barcelona':('es.1','barcelona'),
 'Arsenal':('en.1','arsenal'),
 'Leverkusen':('de.1','bayer leverkusen'),
 'Atletico Madrid':('es.1','atletico madrid'),
 'Atalanta':('it.1','atalanta'),
 'Villarreal':('es.1','villarreal'),
 'Juventus':('it.1','juventus'),
 'Frankfurt':('de.1','eintracht frankfurt'),
 'Tottenham':('en.1','tottenham'),
 'Napoli':('it.1','napoli'),
 'Marseille':('fr.1','marseille'),
 'Monaco':('fr.1','monaco'),
 'Athletic Club':('es.1','athletic club'),
 'Newcastle United':('en.1','newcastle united'),
}
MODELS=('xgq_shots_stage1','pot_dc','pot_independent','elo_draw','frequency_baseline')
PICKS=('home','draw','away')
SEED=20261013


def fixtures():
 data=json.loads(IN.read_text(encoding='utf-8'))
 games=data['matches']
 if len(games)!=189 or len(POT)!=36:
  raise ValueError('Expected 189 observed European matches and 36 clubs')
 participants={t for g in games for t in (g['home'],g['away'])}
 if participants!=set(POT):raise ValueError('Participants do not match 2025 pots')
 league=[m for m in games if m['phase'].startswith('League')]
 if len(league)!=144 or any(
   sum(t in (m['home'],m['away']) for m in league)!=8 for t in participants):
  raise ValueError('Invalid 144-match league-stage membership')
 if len({(r['date'],r['home'],r['away']) for r in games})!=189:
  raise ValueError('Duplicate 2025 UCL results')
 if any(r['goals_90'][0]<0 or r['goals_90'][1]<0 for r in games):
  raise ValueError('Invalid goals')
 assert games[-1]['goals_90']==[1,1] and games[-1]['penalties']=='4-3'
 juve=next(r for r in games if r['home']=='Juventus' and r['away']=='Galatasaray')
 sporting=next(r for r in games if r['home']=='Sporting CP' and r['away']=='Bodo Glimt' and r['date'].startswith('2026'))
 assert juve['goals_90']==[3,0] and sporting['goals_90']==[3,0]
 return sorted(games,key=lambda r:(r['date'],r['id']))


def domestic_profiles(history, day):
 """Only authentic domestic matches finished STRICTLY BEFORE current calendar day."""
 prior=[r for r in history if r['date']<day]
 groups=defaultdict(list)
 for r in prior:groups[r['league']].append(r)
 league_bases={}
 for league,rows in groups.items():
  if len(rows)<40:continue
  n=2*len(rows)
  league_bases[league]={
   'xg':sum(r['home_xg']+r['away_xg'] for r in rows)/n,
   'shots':sum(r['home_shots']+r['away_shots'] for r in rows)/n,
   'quality':sum(r['home_xgq']+r['away_xgq'] for r in rows)/n}
 profiles={}
 for team,(league,source_name) in DOMESTIC.items():
  if league not in league_bases:continue
  rows=sorted((r for r in groups[league]
               if source_name in (r['h'],r['a'])),
              key=lambda r:(r['date'],r['id']),reverse=True)[:16]
  if len(rows)<5:continue
  wsum=0
  sums=defaultdict(float)
  dt=date.fromisoformat(day)
  for r in rows:
   if r['date']>=day:raise ValueError('Future shot profile would leak')
   home=r['h']==source_name
   age=(dt-date.fromisoformat(r['date'])).days
   w=2**(-age/120)
   wsum+=w
   for source,name in (('xg','xg'),('shots','shots'),('xgq','quality')):
    sums['for_'+name]+=w*r[('home_' if home else 'away_')+source]
    sums['against_'+name]+=w*r[('away_' if home else 'home_')+source]
  b=league_bases[league]
  n=len(rows)
  p={'games':n,'league':league}
  for field in ('xg','shots','quality'):
   for side in ('for','against'):
    raw=sums[side+'_'+field]/wsum
    average=(raw*n+6*b[field])/(n+6)
    p[side+'_'+field]=clip(average/b[field],.55,1.65)
  profiles[team]=p
 return profiles,len(prior)


def prediction(game,rating,form):
 h,a=game['home'],game['away']
 final=game['phase']=='Finals, Final'
 delta=rating[h]-rating[a]+(0 if final else 58)
 mu_h=clip(1.34*math.exp(math.log(1.8)*delta/400),.3,3.8)
 mu_a=clip(1.34*math.exp(-math.log(1.8)*delta/400),.3,3.8)
 base=joint(mu_h,mu_a)
 def stat(team,field):return form.get(team,{}).get(field,1.)
 def mod(team,opp):
  attack=clip(stat(team,'for_xg')*stat(opp,'against_xg'),.65,1.5)**.28
  volume=clip(stat(team,'for_shots')*stat(opp,'against_shots'),.65,1.5)**.25
  quality=clip(stat(team,'for_quality')*stat(opp,'against_quality'),.65,1.5)**.30
  return clip(attack*volume*quality,.76,1.28)
 improved=joint(mu_h*mod(h,a),mu_a*mod(a,h))
 mixed=blend(base,improved)
 d=abs(delta)
 p_draw=clip(.275*(1-.17*d/400),.13,.36)
 logistic=1/(1+10**(-delta/400))
 elo={'home':(1-p_draw)*logistic,
      'draw':p_draw,'away':(1-p_draw)*(1-logistic)}
 simple={'home':.425 if not final else .35,
         'draw':.26 if not final else .30,
         'away':.315 if not final else .35}
 matrices={'xgq_shots_stage1':mixed,
           'pot_dc':base,'pot_independent':joint(mu_h,mu_a,rho=0)}
 probs={model:onex2(grid) for model,grid in matrices.items()}
 probs.update({'elo_draw':elo,'frequency_baseline':simple})
 return {'probabilities':probs,'matrices':matrices,'lambdas':[mu_h,mu_a],
         'goals_expected_adjusted':[mu_h*mod(h,a),mu_a*mod(a,h)],
         'top5':ranked_scorelines(mixed,limit=5),
         'base_top5':ranked_scorelines(base,limit=1)}


def update_rating(rating,today):
 """One update PER DAY, after computing ALL same-day predictions."""
 delta=defaultdict(float)
 for r in today:
  h,a=r['home'],r['away']
  dh=rating[h]-rating[a]+(0 if r['phase']=='Finals, Final' else 58)
  home_chance=1/(1+10**(-dh/400))
  x,y=r['goals_90']
  actual=1 if x>y else .5 if x==y else 0
  d=18*(actual-home_chance)
  delta[h]+=d
  delta[a]-=d
 for name,change in delta.items():rating[name]+=change


def actual_class(x,y):return 'home' if x>y else 'draw' if x==y else 'away'


def evaluate(fixtures,history,*,include_match_rows=True):
 ratings={t:float(POT_RATING[POT[t]]) for t in POT}
 byday=defaultdict(list)
 for row in fixtures:byday[row['date']].append(row)
 daily=[]
 allrows=[]
 for day in sorted(byday):
  # Shots from public/private five domestic leagues must be earlier than day.
  form,prior_count=domestic_profiles(history,day)
  today=byday[day]
  record=[]
  for r in today:
   p=prediction(r,ratings,form)
   h,a=r['goals_90']
   actual=actual_class(h,a)
   scored={}
   for model in MODELS:
    q=p['probabilities'][model]
    pick=max(PICKS,key=lambda k:q[k])
    grid=p['matrices'].get(model)
    scoreline=ranked_scorelines(grid,limit=1)[0]['score'] if grid else None
    scoreprob=grid[h][a] if grid and h<len(grid) and a<len(grid[h]) else None
    scored[model]={
      'pick':pick,'correct':int(pick==actual),
      'log_loss':-math.log(max(q[actual],1e-12)),
      'brier':sum((q[z]-(z==actual))**2 for z in PICKS),
      'modal_scoreline':f'{scoreline[0]}-{scoreline[1]}' if scoreline else None,
      'modal_exact_correct':int(scoreline==[h,a]) if scoreline else None,
      'exact_score_probability':scoreprob,
      'exact_log_loss':-math.log(max(scoreprob,1e-12)) if scoreprob is not None else None,
      'probabilities':{k:round(q[k],7) for k in PICKS}
    }
   info={
    'id':r['id'],'date':day,'phase':r['phase'],'home':r['home'],'away':r['away'],
    'actual_score_90':f'{h}-{a}','actual':actual,'after_120':r['after_120'],
    'penalties':r['penalties'],
    'home_prior_xg_games':form.get(r['home'],{}).get('games',0),
    'away_prior_xg_games':form.get(r['away'],{}).get('games',0),
    'shot_history_before_day':prior_count,
    'rating_before_game':{
     'home':round(ratings[r['home']],2),'away':round(ratings[r['away']],2)},
    'expected_goal_rate': [round(x,5) for x in p['goals_expected_adjusted']],
    'models':scored,
    'best_5_scorelines':[{'score':f"{z['score'][0]}-{z['score'][1]}",
                          'probability':round(z['probability'],7)}
                         for z in p['top5']],
    'no_future_scouting_allowed':True,
   }
   allrows.append(info)
   record.append(info)
  # Strong test: all same-day matches see the same pre-day rating snapshot.
  daily.append({'day':day,'matches':len(record),'prior_domestic_games':prior_count})
  update_rating(ratings,today)
 return allrows,daily


def summary(rows,model):
 vals=[r['models'][model] for r in rows]
 n=len(vals)
 if not n:return {'matches':0}
 return {'matches':n,'correct':sum(r['correct'] for r in vals),
  'accuracy':sum(r['correct'] for r in vals)/n,
  'log_loss':sum(r['log_loss'] for r in vals)/n,
  'brier':sum(r['brier'] for r in vals)/n,
  'draw_pick_count':sum(r['pick']=='draw' for r in vals),
  'mean_draw_probability':sum(r['probabilities']['draw'] for r in vals)/n,
  'modal_score_exact_hits':sum(r['modal_exact_correct'] or 0 for r in vals),
  'mean_exact_log_loss':(sum(r['exact_log_loss'] for r in vals
                            if r['exact_log_loss'] is not None)/
                          sum(r['exact_log_loss'] is not None for r in vals)
                          if any(r['exact_log_loss'] is not None for r in vals)
                          else None)}


def ci_by_day(rows,challenger='xgq_shots_stage1',base='pot_dc',n=2000):
 rng=random.Random(SEED)
 grouped=defaultdict(list)
 for r in rows:grouped[r['date']].append(r)
 days=sorted(grouped)
 values=[]
 for _ in range(n):
  sumloss=count=0.
  for __ in days:
   block=grouped[days[rng.randrange(len(days))]]
   for r in block:
    sumloss+=r['models'][base]['log_loss']-r['models'][challenger]['log_loss']
    count+=1
  values.append(sumloss/count)
 values.sort()
 return {'mean_gain':sum((r['models'][base]['log_loss']-
                  r['models'][challenger]['log_loss']) for r in rows)/len(rows),
         'ci95':[values[int(n*.025)],values[int(n*.975)]]}


def main():
 fixtures_=fixtures()
 history=D1().history()
 allrows,daily=evaluate(fixtures_,history)
 byphase=defaultdict(list)
 byround=defaultdict(list)
 for r in allrows:
  group=('League' if r['phase'].startswith('League') else
         'Playoffs' if r['phase'].startswith('Playoffs') else r['phase'].replace('Finals, ',''))
  byphase[group].append(r)
  byround[r['phase']].append(r)
 covered=[r for r in allrows if r['home_prior_xg_games']>=5 and
                             r['away_prior_xg_games']>=5]
 uncovered=[r for r in allrows if r not in covered]
 actual_draw=sum(r['actual']=='draw' for r in allrows)
 src=IN.as_posix()
 report={
  'season':'2025-26','research_as_of':'2026-10-13',
  'status':'RETROSPECTIVE REPLAY, NOT HISTORICALLY FROZEN FORECASTS',
  'source':'https://github.com/openfootball/champions-league/blob/master/2025-26/cl.txt',
  'uefa_pots_date':'2025-08-28',
  'algorithm_parameter_warning':'2026/27 adaptation developed after this season; no claim of blind/out-of-sample validation',
  'goal_target':'90-minute 1X2, includes separate ET and penalty final outcome',
  'matches_total':len(allrows),'historical_domestic_rows':len(history),
  'no_future_understat_used':True,
  'shot_coverage_both_team_match_count':len(covered),
  'shot_coverage_missing_one_or_both':len(uncovered),
  'actual_outcome_counts':{k:sum(r['actual']==k for r in allrows) for k in PICKS},
  'scores':{model:summary(allrows,model) for model in MODELS},
  'paired_logloss_vs_pot_dc_ci95':ci_by_day(allrows),
  'per_stage':{phase:{model:summary(rows,model) for model in MODELS}
               for phase,rows in byphase.items()},
  'per_round':{phase:{model:summary(rows,model) for model in MODELS}
               for phase,rows in byround.items()},
  'both_teams_authentic_domestic_shots':{model:summary(covered,model) for model in MODELS},
  'missing_any_team_authentic_domestic_shots':{model:summary(uncovered,model) for model in MODELS},
  'final':next(r for r in allrows if r['phase']=='Finals, Final'),
  'days':daily,
  'matches':allrows,
  'source_evidence':{'fixtures':str(src),'pot': 'https://www.uefa.com/uefachampionsleague/news/029c-1e954c3512ef-8b9c6fa0f83b-1000--champions-league-league-phase-draw-pots-confirmed/'},
  'production_unchanged':True,
  'generated_at_utc':datetime.now(timezone.utc).isoformat(),
 }
 assert len(allrows)==189 and sum(len(v) for v in byphase.values())==189
 assert len([r for r in allrows if r['phase'].startswith('League')])==144
 assert report['final']['actual']=='draw' and report['final']['penalties']=='4-3'
 assert all(r['shot_history_before_day']>=0 for r in allrows)
 OUT.mkdir(parents=True,exist_ok=True)
 (OUT/'ucl_2025_26_backtest.json').write_text(json.dumps(report,indent=2,ensure_ascii=False))
 with (OUT/'ucl_2025_26_predictions.csv').open('w',newline='',encoding='utf-8-sig') as fh:
  cols=['id','date','phase','home','away','actual_score_90','actual','after_120',
        'penalties','home_prior_xg_games','away_prior_xg_games']
  for model in MODELS:
   cols.extend([f'{model}_{stat}' for stat in
      ('pick','correct','modal_scoreline','log_loss','brier','p_home','p_draw','p_away')])
  writer=csv.DictWriter(fh,fieldnames=cols);writer.writeheader()
  for r in allrows:
   z={k:r.get(k) for k in cols}
   for model in MODELS:
    score=r['models'][model]
    for field in ('pick','correct','modal_scoreline','log_loss','brier'):
     z[f'{model}_{field}']=score[field]
    for field in PICKS:
     z[f'{model}_p_{field}']=score['probabilities'][field]
   writer.writerow(z)
 print(json.dumps({'season':'2025-26','total':len(allrows),
  'both_shot_coverage':len(covered),
  'actual_outcomes':report['actual_outcome_counts'],
  'all_models':report['scores'],
  'paired_gain_ci':report['paired_logloss_vs_pot_dc_ci95'],
  'stage_counts':{k:len(v) for k,v in byphase.items()},
  'final_prediction':{'pick':report['final']['models']['xgq_shots_stage1']['pick'],
   '90min':report['final']['actual_score_90'],
   'actual_penalties':report['final']['penalties']}},sort_keys=True))
 return report


if __name__=='__main__':
 main()
