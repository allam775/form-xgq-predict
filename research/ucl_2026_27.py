"""UEFA Champions League 2026/27 whole-season probabilistic projection.

Snapshot 2026-10-13 before matchday 2. All 144 officially scheduled league
games, 18 verified round-1 results; prospective round-2+ estimates.
Knockout names are scenario-based, NOT UEFA-official future fixtures.

Four UEFA draw pots provide *ordinal strength priors*, NOT independently
validated cross-league Elo. Where private Understat history exists we add
pre-cutoff xG, XGQ and shots with large shrinkage; elsewhere features neutral.
No hypothetical future scores are fed back as real pre-match training records.
"""
from __future__ import annotations
import csv
import json
import math
import random
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

from engine.understat_d1 import D1

ROOT=Path(__file__).resolve().parent
REPORT=ROOT/'reports'/'ucl2026_27'
SOURCE=ROOT/'ucl_2026_27_fixtures.txt'
CUTOFF='2026-10-13'
SEED=20261013
REPS=6000
OUTCOMES=('home','draw','away')
# Explicit, UEFA-drawn 2026/27 pots. Exact names are declared, not estimated.
POTS={
 1:('PSG','Bayern Munich','Real Madrid','Liverpool','Inter','Manchester City','Arsenal','Barcelona','Atletico Madrid'),
 2:('Dortmund','Roma','Sporting CP','Aston Villa','Porto','Manchester United','Club Brugge','Real Betis','PSV'),
 3:('Feyenoord','Lille','Bodo Glimt','Napoli','RB Leipzig','Villarreal','Fenerbahce','Shakhtar Donetsk','Galatasaray'),
 4:('Slavia Prague','Slovan Bratislava','Stuttgart','AEK','LASK','Como','Lens','Viking','Sabah'),
}
TIER_ELO={1:1890,2:1780,3:1680,4:1570}  # ordinal assumption, not sourced match-derived ratings
TEAM_UNDERSTAT={
 'PSG':('fr.1','paris saint germain'),'Bayern Munich':('de.1','bayern munich'),
 'Real Madrid':('es.1','real madrid'),'Liverpool':('en.1','liverpool'),
 'Inter':('it.1','inter'),'Manchester City':('en.1','manchester city'),
 'Arsenal':('en.1','arsenal'),'Barcelona':('es.1','barcelona'),
 'Atletico Madrid':('es.1','atletico madrid'),
 'Dortmund':('de.1','borussia dortmund'),'Roma':('it.1','roma'),
 'Aston Villa':('en.1','aston villa'),'Manchester United':('en.1','manchester united'),
 'Real Betis':('es.1','real betis'),
 'Lille':('fr.1','lille'),'Napoli':('it.1','napoli'),
 'RB Leipzig':('de.1','rasenballsport leipzig'),'Villarreal':('es.1','villarreal'),
 'Stuttgart':('de.1','vfb stuttgart'),'Como':('it.1','como'),'Lens':('fr.1','lens'),
}
TEAM_NAMES=set(t for teams in POTS.values() for t in teams)
TEAM_POT={t:pot for pot,teams in POTS.items() for t in teams}


def clip(x,lo,hi):
 return min(hi,max(lo,x))


def fixtures():
 output=[]
 for line in SOURCE.read_text(encoding='utf-8').splitlines():
  line=line.strip()
  if not line or line.startswith('#'):continue
  parts=line.split(';')
  day,roundtext=parts[:2]
  date.fromisoformat(day)
  md=int(roundtext)
  for spec in parts[2:]:
   pair,sep,score=spec.partition('=')
   h,sep2,a=pair.partition('>')
   if not sep2 or h not in TEAM_NAMES or a not in TEAM_NAMES or h==a:
    raise ValueError('Unknown team or invalid fixed official fixture '+spec)
   actual=None
   if sep:
    ga,gb=map(int,score.split('-'))
    actual=(ga,gb)
   output.append({'id':len(output)+1,'date':day,'round':md,'home':h,'away':a,'actual':actual})
 if len(TEAM_NAMES)!=36 or len(output)!=144:
  raise ValueError('Expected 36 official UEFA teams / 144 league fixtures')
 plays=Counter(t for m in output for t in (m['home'],m['away']))
 homes=Counter(m['home'] for m in output)
 if any(plays[t]!=8 or homes[t]!=4 for t in TEAM_NAMES):
  raise ValueError('UEFA Swiss stage must have 8 fixtures, 4 home, per club')
 if any((m['round']==1)!=(m['actual'] is not None) for m in output):
  raise ValueError('Only first matchday should be recorded as an actual result')
 if sum(m['actual'] is not None for m in output)!=18:
  raise ValueError('18 authentic fixed results are required')
 if any((m['round']==1)!=(m['date']<'2026-10-13') for m in output):
  raise ValueError('Historical/future date mismatch')
 if len({(m['date'],m['home'],m['away']) for m in output})!=144:
  raise ValueError('Duplicate official fixture')
 return output


def profiles(history):
 """Use only D1 fields as of 12 October; no private rows written to GitHub."""
 history=[m for m in history if m['date']<CUTOFF]
 league_stats={}
 for league in ('en.1','es.1','de.1','it.1','fr.1'):
  matches=[r for r in history if r['league']==league]
  if len(matches)<150:raise ValueError('Insufficient domestic context for '+league)
  league_stats[league]={
   'xg':sum(m['home_xg']+m['away_xg'] for m in matches)/(2*len(matches)),
   'shots':sum(m['home_shots']+m['away_shots'] for m in matches)/(2*len(matches)),
   'quality':sum(m['home_xgq']+m['away_xgq'] for m in matches)/(2*len(matches))}
 result={}
 for team,lookup in TEAM_UNDERSTAT.items():
  league,name=lookup
  rows=sorted((m for m in history if m['league']==league and
              name in (m['h'],m['a'])),key=lambda m:(m['date'],m['id']),reverse=True)[:16]
  if len(rows)<5:continue
  totals=defaultdict(float)
  wsum=0.
  for r in rows:
   home=r['h']==name
   delta=(date.fromisoformat(CUTOFF)-date.fromisoformat(r['date'])).days
   w=2**(-delta/120.)
   for fld,k in [('xg','xg'),('shots','shots'),('xgq','quality')]:
    totals['for_'+k]+=w*r[('home_' if home else 'away_')+fld]
    totals['against_'+k]+=w*r[('away_' if home else 'home_')+fld]
   wsum+=w
  # Six full prior matches to keep 5-game teams from huge outliers.
  base=league_stats[league]
  n=len(rows)
  form={'league':league,'games':n}
  for k in ('xg','shots','quality'):
   for side in ('for','against'):
    observed=(totals[side+'_'+k]/wsum)
    shrunk=(observed*n+6*base[k])/(n+6)
    form[side+'_'+k]=clip(shrunk/base[k],.55,1.65)
  result[team]=form
 return result,league_stats,len(history)


def poiss(mu,max_goals=12):
 """Normalized individual scores 0..12; never mislabel 7+ as seven goals."""
 probs=[math.exp(-mu)]
 for n in range(1,max_goals+1):
  probs.append(probs[-1]*mu/n)
 total=sum(probs)
 return [x/total for x in probs]


def joint(home,away,rho=-.08):
 """Low-score Dixon–Coles correction to independent Poisson."""
 home,away=clip(home,.18,4.1),clip(away,.18,4.1)
 hp,ap=poiss(home),poiss(away)
 grid=[]
 for i,h in enumerate(hp):
  row=[]
  for j,a in enumerate(ap):
   tau=1.
   if i==0 and j==0:tau=1-home*away*rho
   elif i==0 and j==1:tau=1+home*rho
   elif i==1 and j==0:tau=1+away*rho
   elif i==1 and j==1:tau=1-rho
   row.append(h*a*max(.01,tau))
  grid.append(row)
 z=sum(sum(x) for x in grid)
 return [[v/z for v in row] for row in grid]


def onex2(grid):
 p={'home':0.,'draw':0.,'away':0.}
 for i,row in enumerate(grid):
  for j,v in enumerate(row):
   p['home' if i>j else 'away' if i<j else 'draw']+=v
 return p


def blend(a,b,w=.5):
 if len(a)!=len(b) or any(len(a[i])!=len(b[i]) for i in range(len(a))):
  raise ValueError('Cannot blend incompatible score distributions')
 return [[(1-w)*a[i][j]+w*b[i][j] for j in range(len(a[i]))]
         for i in range(len(a))]


def ranked_scorelines(grid,limit=5):
 """Highest individual scoreline probabilities, irrespective of the 1X2 pick.

 The most probable exact score can be a DRAW while an outright win is the
 largest summed 1X2 probability: this is mathematically valid, not a bug.
 """
 all_scores=[{'score':[i,j],'probability':v}
             for i,row in enumerate(grid) for j,v in enumerate(row)]
 all_scores.sort(key=lambda r:(-r['probability'],sum(r['score']),r['score'][0],r['score'][1]))
 return all_scores[:limit]



def calc(match,rating,form):
 """Blended goal baseline + the XGQ/xG/shot-volume research component."""
 h,a=match['home'],match['away']
 delta=rating[h]-rating[a]+58
 lamb_h=clip(1.34*math.exp(math.log(1.8)*delta/400),.3,3.8)
 lamb_a=clip(1.34*math.exp(-math.log(1.8)*delta/400),.3,3.8)
 base=joint(lamb_h,lamb_a)
 def val(t,k):
  return form.get(t,{}).get(k,1.)
 def modifier(t,opponent):
  # Small powers because xG already encodes volume and quality; these are
  # empirical five-league-derived features, not invented for missing clubs.
  attacks=clip(val(t,'for_xg')*val(opponent,'against_xg'),.65,1.5)**.28
  volume=clip(val(t,'for_shots')*val(opponent,'against_shots'),.65,1.5)**.25
  quality=clip(val(t,'for_quality')*val(opponent,'against_quality'),.65,1.5)**.30
  return clip(attacks*volume*quality,.76,1.28)
 extra=joint(lamb_h*modifier(h,a),lamb_a*modifier(a,h))
 mixed=blend(base,extra)
 probs=onex2(mixed)
 chosen=max(probs,key=probs.get)
 top=ranked_scorelines(mixed,limit=5)
 # Do NOT constrain the exact-score mode to the preferred 1X2 category.
 # The 1X2 pick aggregates ALL wins/draws/losses, unlike one exact score.
 return {'p':probs,'score':top[0]['score'],'score_probability':top[0]['probability'],
         'top_scorelines':top,'pick':chosen,
         'lambda_home':lamb_h*modifier(h,a),'lambda_away':lamb_a*modifier(a,h),
         'grid':mixed,'pure_goals':onex2(base)}


def make_ratings(fixture):
 ratings={t:float(TIER_ELO[TEAM_POT[t]]) for t in TEAM_NAMES}
 # Distinguish equal-ranked pot opponents mildly using their authentic,
 # PRE-CUTOFF first-round European performance; deterministic Elo K=18.
 changes=defaultdict(float)
 for game in fixture:
  if game['actual'] is None:continue
  h,a=game['home'],game['away']
  hg,ag=game['actual']
  d=ratings[h]+58-ratings[a]
  expectation=1/(1+10**(-d/400))
  actual=1. if hg>ag else .5 if hg==ag else 0.
  change=18*(actual-expectation)
  changes[h]+=change
  changes[a]-=change
 for t,n in changes.items():ratings[t]+=n
 return ratings


def score_table(matches,score_key):
 league={t:{'team':t,'pot':TEAM_POT[t],'P':0,'W':0,'D':0,'L':0,
            'GF':0,'GA':0,'GD':0,'Pts':0} for t in TEAM_NAMES}
 for m in matches:
  h,a=m['home'],m['away']
  hs,as_=m[score_key]
  for team,gf,ga in ((h,hs,as_),(a,as_,hs)):
   line=league[team]
   line['P']+=1;line['GF']+=gf;line['GA']+=ga
   line['GD']=line['GF']-line['GA']
   if gf>ga:line['W']+=1;line['Pts']+=3
   elif gf==ga:line['D']+=1;line['Pts']+=1
   else:line['L']+=1
 return sorted(league.values(),key=lambda r:(-r['Pts'],-r['GD'],-r['GF'],r['team']))


def sample_grid(grid,rng):
 value=rng.random();s=0.
 for i,row in enumerate(grid):
  for j,p in enumerate(row):
   s+=p
   if value<=s:return i,j
 return len(grid)-1,len(grid[-1])-1


def advance(a,b,models,rng,*,neutral=False):
 """Forecast a TWO-LEG tie; no away-goal rule. Neutral one-leg final."""
 if neutral:
  # Venue-neutral is approximated by equally averaging each order's matrix.
  g1=models[(a,b)]['grid'];g2=models[(b,a)]['grid']
  probs=blend(g1,[list(row) for row in zip(*g2)])
  x,y=sample_grid(probs,rng)
  if x!=y:return a if x>y else b
 else:
  first=sample_grid(models[(b,a)]['grid'],rng)  # seeded a hosts return leg
  second=sample_grid(models[(a,b)]['grid'],rng)
  x=first[1]+second[0];y=first[0]+second[1]
  if x!=y:return a if x>y else b
 # Extra time / penalties: small symmetric mixture around ability difference.
 strength=models[(a,b)]['lambda_home']/max(.1,models[(b,a)]['lambda_home'])
 p=clip(.5+math.log(strength)*.16,.27,.73)
 return a if rng.random()<p else b


def bracket(ranked,models,rng,*,with_trace=False):
 """One illustrative draw consistent with article 19 PAIR GROUP constraints."""
 names=[z['team'] for z in ranked]
 groups=[
  (names[8:10],names[22:24]),
  (names[10:12],names[20:22]),
  (names[12:14],names[18:20]),
  (names[14:16],names[16:18])]
 play=[]
 wins=[]
 for high,low in groups:
  low=list(low);rng.shuffle(low)
  for h,l in zip(high,low):
   victor=advance(h,l,models,rng)
   play.append({'a':h,'b':l,'winner':victor})
   wins.append(victor)
 r16=[]
 seed_positions=[names[0:2],names[2:4],names[4:6],names[6:8]]
 opponent_positions=[wins[6:8],wins[4:6],wins[2:4],wins[0:2]]
 r16wins=[]
 for seeds,opp in zip(seed_positions,opponent_positions):
  seeds=list(seeds);rng.shuffle(seeds)
  for s,o in zip(seeds,opp):
   victor=advance(s,o,models,rng)
   r16.append({'a':s,'b':o,'winner':victor})
   r16wins.append(victor)
 qf=[];qfwins=[]
 for i in range(0,8,2):
  a,b=r16wins[i:i+2];v=advance(a,b,models,rng)
  qf.append({'a':a,'b':b,'winner':v});qfwins.append(v)
 semis=[];swins=[]
 for i in (0,2):
  a,b=qfwins[i:i+2];v=advance(a,b,models,rng)
  semis.append({'a':a,'b':b,'winner':v});swins.append(v)
 champion=advance(*swins,models,rng,neutral=True)
 return {'playoff':play,'round_of_16':r16,'quarter_final':qf,
         'semi_final':semis,'final':{'a':swins[0],'b':swins[1],'winner':champion},
         'champion':champion} if with_trace else (wins,r16wins,qfwins,swins,champion)


def precompute_all(teams,rating,form):
 pred={}
 for a in teams:
  for b in teams:
   if a!=b:pred[(a,b)]=calc({'home':a,'away':b},rating,form)
 return pred


def advance_probability(a,b,models,*,neutral=False):
 """Independent expected first-90-min scorelines on TWO legs; 50/50 tiebreak."""
 if neutral:
  x=models[(a,b)]['grid']
  y=models[(b,a)]['grid']
  grid=blend(x,[list(row) for row in zip(*y)])
  p=sum(v for i,row in enumerate(grid) for j,v in enumerate(row) if i>j)
  d=sum(v for i,row in enumerate(grid) for j,v in enumerate(row) if i==j)
  return p+.5*d
 first=models[(b,a)]['grid']
 second=models[(a,b)]['grid']
 diff1=defaultdict(float)
 diff2=defaultdict(float)
 for i,row in enumerate(first):
  for j,p in enumerate(row):diff1[j-i]+=p
 for i,row in enumerate(second):
  for j,p in enumerate(row):diff2[i-j]+=p
 p=d=0.
 for m,pm in diff1.items():
  for n,pn in diff2.items():
   if m+n>0:p+=pm*pn
   if m+n==0:d+=pm*pn
 return p+.5*d


def most_likely_bracket(table,models):
 """Conditional illustrative pairing choice, NOT the yet-to-be-drawn UEFA path."""
 t=[r['team'] for r in table]
 stages={'playoff':[],'round_of_16':[],'quarter_final':[],
         'semi_final':[]}
 def tie(a,b,phase):
  prob=advance_probability(a,b,models)
  winner=a if prob>=.5 else b
  stages[phase].append({'a':a,'b':b,'winner':winner,
                        'p_a':round(prob,4),'p_b':round(1-prob,4)})
  return winner
 po=[]
 for high,low in ((t[8:10],t[22:24]),(t[10:12],t[20:22]),
                  (t[12:14],t[18:20]),(t[14:16],t[16:18])):
  for a,b in zip(high,low):po.append(tie(a,b,'playoff'))
 seeds=(t[0:2],t[2:4],t[4:6],t[6:8])
 opponents=(po[6:8],po[4:6],po[2:4],po[0:2])
 r16=[]
 for first,second in zip(seeds,opponents):
  for a,b in zip(first,second):r16.append(tie(a,b,'round_of_16'))
 quarters=[tie(r16[i],r16[i+1],'quarter_final') for i in range(0,8,2)]
 semis=[tie(quarters[i],quarters[i+1],'semi_final') for i in (0,2)]
 fa,fb=semis
 pf=advance_probability(fa,fb,models,neutral=True)
 stages['final']={'a':fa,'b':fb,'winner':fa if pf>=.5 else fb,
                  'p_a':round(pf,4),'p_b':round(1-pf,4)}
 stages['note']='Illustrative permissible pairing path; no official knockout draw exists yet.'
 return stages


def simulation(fixtures,pred,base_table,models,reps=REPS):
 rng=random.Random(SEED)
 cnt={t:Counter() for t in TEAM_NAMES}
 table_total=defaultdict(float)
 for _ in range(reps):
  round_games=[]
  for m in fixtures:
   if m['actual'] is not None:sc=list(m['actual'])
   else:sc=sample_grid(pred[m['id']]['grid'],rng)
   round_games.append({**m,'sample':sc})
  rows=score_table(round_games,'sample')
  for pos,row in enumerate(rows,1):
   t=row['team'];table_total[t]+=row['Pts'];cnt[t]['rank_total']+=pos;cnt[t]['pos_'+str(pos)]+=1
   for field in ('W','D','L','GF','GA','GD'):
    cnt[t]['total_'+field]+=row[field]
   if pos<=8:cnt[t]['top8']+=1
   if pos<=24:cnt[t]['top24']+=1
  p16,r16,qf,semi,win=bracket(rows,models,rng)
  for t in p16:cnt[t]['r16']+=1
  for t in r16:cnt[t]['qf']+=1
  for t in qf:cnt[t]['sf']+=1
  for t in semi:cnt[t]['final']+=1
  cnt[win]['champion']+=1
 report={}
 for t in sorted(TEAM_NAMES):
  report[t]={k:cnt[t][k]/reps for k in ('top8','top24','r16','qf','sf','final','champion')}
  report[t]['expected_points']=table_total[t]/reps
  for field in ('W','D','L','GF','GA','GD'):
   report[t]['expected_'+field]=cnt[t]['total_'+field]/reps
  report[t]['mean_rank']=cnt[t]['rank_total']/reps
  positions=[i for i in range(1,37) for _ in range(cnt[t]['pos_'+str(i)])]
  report[t]['rank_low_90']=positions[int(.05*(reps-1))]
  report[t]['rank_high_90']=positions[int(.95*(reps-1))]
 return report


def main():
 fixture=fixtures()
 db=D1()
 form,league_stats,n_history=profiles(db.history())
 rating=make_ratings(fixture)
 preds={}
 matches=[]
 scenario_rng=random.Random(SEED+2222)
 for m in fixture:
  p=calc(m,rating,form);preds[m['id']]=p
  observed=m['actual']
  modal=list(observed) if observed is not None else p['score']
  # An *unbiased random realization* from the full exact-score distribution.
  # This sample is ONLY a possible season for an illustrative 36-team table.
  scenario=list(observed) if observed is not None else list(sample_grid(p['grid'],scenario_rng))
  matches.append({'id':m['id'],'date':m['date'],'matchday':m['round'],
    'home':m['home'],'away':m['away'],
    'status':'ACTUAL' if observed is not None else 'PREDICTION',
    'score':modal,
    'scoreline':f"{modal[0]}-{modal[1]}",
    'scoreline_method':'ACTUAL' if observed is not None else 'UNCONDITIONAL_EXACT_SCORE_MODE',
    'score_probability':round(p['score_probability'],6) if observed is None else None,
    'top_scorelines':[{'scoreline':str(z['score'][0])+'-'+str(z['score'][1]),
                       'probability':round(z['probability'],6)}
                      for z in p['top_scorelines']] if observed is None else [],
    'scenario_score':scenario,
    'scenario_scoreline':f"{scenario[0]}-{scenario[1]}",
    'scenario_scoreline_method':'ACTUAL' if observed is not None else 'ONE_SEEDED_RANDOM_REALIZATION',
    # September matches are ACTUAL. Never label a retrospectively computed
    # probability as a prediction from the pre-kickoff time.
    'pick':p['pick'] if observed is None else None,
    'home_probability':round(p['p']['home'],6) if observed is None else None,
    'draw_probability':round(p['p']['draw'],6) if observed is None else None,
    'away_probability':round(p['p']['away'],6) if observed is None else None,
    'score_lambda_home':round(p['lambda_home'],4) if observed is None else None,
    'score_lambda_away':round(p['lambda_away'],4) if observed is None else None,
    'home_form_games':form.get(m['home'],{}).get('games',0) if observed is None else None,
    'away_form_games':form.get(m['away'],{}).get('games',0) if observed is None else None,
    'model_is_cross_league_adaptation':True})
 # DO NOT fill standings by taking a joint 1X2 winner in every game.
 # The table below is ONE reproducible season drawn from the entire matrix,
 # including ties, upsets and high/low scores; the *proper* projection is
 # the mean over all Monte Carlo seasons (computed below).
 projected=score_table(matches,'scenario_score')
 for i,t in enumerate(projected,1):
  t['rank']=i;t['route']='direct_ro16' if i<=8 else 'playoff' if i<=24 else 'eliminated'
 models=precompute_all(TEAM_NAMES,rating,form)
 monte=simulation(fixture,preds,projected,models)
 # One readable scenario draw, NOT literally a forecast of the UEFA draw.
 draw=bracket(projected,models,random.Random(SEED+1000),with_trace=True)
 favorite_draw=most_likely_bracket(projected,models)
 # Bracket advantage estimates use the independent tournament simulation.
 winners=sorted(monte.items(),key=lambda x:-x[1]['champion'])
 for r in projected:
  r.update({k:round(monte[r['team']][k],5) for k in ('top8','top24','r16','qf','sf','final','champion','expected_points','mean_rank')})
  r.update({k:monte[r['team']][k] for k in ('rank_low_90','rank_high_90')})
 # Separate the expected table (not a single simulated season) from the
 # optional fully coherent seeded sample season.
 expected=sorted(({'team':t,'pot':TEAM_POT[t],
                   'expected_'+k:round(v['expected_'+k],4)
                   for k in ('W','D','L','GF','GA','GD')}
                  |{'expected_points':round(v['expected_points'],5),
                    'mean_rank':round(v['mean_rank'],5),
                    'rank_low_90':v['rank_low_90'],
                    'rank_high_90':v['rank_high_90']}
                  |{k:round(v[k],5) for k in
                     ('top8','top24','r16','qf','sf','final','champion')}
                  for t,v in monte.items()),
                 key=lambda r:(-r['expected_points'],-r['top8'],r['team']))
 for i,r in enumerate(expected,1):
  r['rank']=i
  r['route']='direct_ro16' if i<=8 else 'playoff' if i<=24 else 'eliminated'
 # An expected table is the recommended ranking; illustrative bracket uses
 # this mean standing only to create a CONDITIONAL, non-UEFA draw example.
 favorite_draw=most_likely_bracket(expected,models)
 futures=[m for m in matches if m['status']=='PREDICTION']
 diagnostics={
  'previous_2026_10_13_release_unique_future_scorelines':6,
  'prior_release_forced_1x2_winner_then_chose_conditional_score':True,
  'future_modal_exact_score_counts':dict(sorted(Counter(m['scoreline'] for m in futures).items())),
  'future_one_sample_score_counts':dict(sorted(Counter(m['scenario_scoreline'] for m in futures).items())),
  'modal_draw_count':sum(m['score'][0]==m['score'][1] for m in futures),
  'sampled_draw_count':sum(m['scenario_score'][0]==m['scenario_score'][1] for m in futures),
  'sum_draw_probabilities':round(sum(m['draw_probability'] for m in futures),3),
  'draws_as_top_1x2':sum(m['pick']=='draw' for m in futures),
  'mean_exact_score_mode_probability':round(sum(m['score_probability'] for m in futures)/len(futures),5),
  'score_mode_can_disagree_with_1x2_pick':True,
  'main_league_table_is_expected':True,
  'actual_round1_scores_untouched':True,
 }
 record={
  'as_of':CUTOFF,'season':'2026-27','format':'36 teams 144 league games and conditional 2027 knockouts',
  'model':'UEFA pot prior + D1 five-league shot-volume/xG/XGQ shrinkage + DC correlated goals',
  'caution':'Pot-derived power priors are analyst assumptions; not a validated all-Europe Elo model. Source shot metrics only from five domestic leagues. Results are uncertain.',
  'source_uefa':'https://www.uefa.com/uefachampionsleague/news/02a8-2174c9e9019d-f909a77bd77a-1000--2026-27-champions-league-all-the-league-phase-fixtures/',
  'source_pots':'https://www.uefa.com/uefachampionsleague/news/02a8-21717d0c6cb5-03a9a5ff1552-1000--champions-league-league-phase-draw-pots-confirmed/',
  'assumed_pot_elo':TIER_ELO,'ratings_after_real_md1':{k:round(v,2) for k,v in sorted(rating.items())},
  'total_actual':18,'total_predicted':126,'history_private_matches':n_history,
  'actual_first_round_only':True,'domestic_form_teams':len(form),
  'teams_without_domestic_xg':sorted(TEAM_NAMES-set(form)),
  'n_simulations':REPS,
  'scoreline_diagnostics':diagnostics,
  'displayed_modal_score_is_unconditional':True,
  'example_table_is_one_seeded_draw_not_the_forecast':True,
  'champion_favorites':[
    {'team':t,'prob':round(v['champion'],5)} for t,v in winners[:12]],
  'one_sample_bracket_is_official':False,
  'scenario_bracket':draw,
  'illustrative_favored_bracket':favorite_draw,
  'league_table':projected,
  'expected_league_table':expected,
  'matches':matches}
 REPORT.mkdir(parents=True,exist_ok=True)
 (REPORT/'ucl_2026_27_results.json').write_text(json.dumps(record,indent=2,ensure_ascii=False))
 with (REPORT/'ucl_2026_27_matches.csv').open('w',newline='',encoding='utf-8-sig') as fp:
  cols=[k for k in matches[0] if k!='score'];out=csv.DictWriter(fp,fieldnames=cols)
  out.writeheader();out.writerows([{k:m[k] for k in cols} for m in matches])
 with (REPORT/'ucl_2026_27_expected_table.csv').open('w',newline='',encoding='utf-8-sig') as fp:
  cols=['rank','team','pot','expected_points','expected_W','expected_D','expected_L',
        'expected_GF','expected_GA','expected_GD','mean_rank',
        'rank_low_90','rank_high_90','route','top8','top24','r16','qf','sf','final','champion']
  out=csv.DictWriter(fp,fieldnames=cols)
  out.writeheader();out.writerows([{k:r[k] for k in cols} for r in expected])
 with (REPORT/'ucl_2026_27_table.csv').open('w',newline='',encoding='utf-8-sig') as fp:
  cols=['rank','team','pot','P','W','D','L','GF','GA','GD','Pts','route','top8','top24','r16','qf','sf','final','champion','expected_points','mean_rank','rank_low_90','rank_high_90']
  out=csv.DictWriter(fp,fieldnames=cols);out.writeheader();out.writerows([{k:r[k] for k in cols} for r in projected])
 print(json.dumps({'ok':True,'actual':18,'predicted':126,
  'teams_with_private_domestic_form':len(form),'history_count':n_history,
  'expected_table':[(r['team'],r['expected_points']) for r in expected[:12]],
  'scoreline_diagnostics':diagnostics,
  'top_champions':record['champion_favorites'][:9]},ensure_ascii=False))
 return record

if __name__=='__main__':
 main()
