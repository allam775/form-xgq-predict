"""WC26 national-team adaptation. Retrospective, not exact Understat squared-shot XGQ."""
import csv,io,json,math,urllib.request,itertools
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'reports'
OUT.mkdir(exist_ok=True)
URLS={
 'wc':'https://raw.githubusercontent.com/openfootball/worldcup.json/516d3825c3bd23fdc298c4014e84bde78f2d4965/2026/worldcup.json',
 'intl':'https://raw.githubusercontent.com/martj42/international_results/d5bd6de012c87e2f325de602ae77fe2f9ab61ef3/results.csv',
 'detail':'https://raw.githubusercontent.com/mominullptr/FIFA-World-Cup-2026-Dataset/2f61805ec8ac58e52882e8f0e2413a5cfa7f4d61/matches_detailed.csv',
 'stats':'https://raw.githubusercontent.com/mominullptr/FIFA-World-Cup-2026-Dataset/2f61805ec8ac58e52882e8f0e2413a5cfa7f4d61/match_team_stats.csv'},
 'meta':'https://raw.githubusercontent.com/mominullptr/FIFA-World-Cup-2026-Dataset/2f61805ec8ac58e52882e8f0e2413a5cfa7f4d61/matches.csv'
ALIASES={'USA':'United States','Czechia':'Czech Republic','Bosnia & Herzegovina':'Bosnia and Herzegovina','Türkiye':'Turkey','Côte d’Ivoire':'Ivory Coast',"Côte d'Ivoire":'Ivory Coast','Cabo Verde':'Cape Verde','Congo DR':'DR Congo','IR Iran':'Iran'}
def N(s):return ALIASES.get(s.strip(),s.strip())
def get(u):
 req=urllib.request.Request(u,headers={'User-Agent':'XGQ-WC26-Research/1.0'})
 with urllib.request.urlopen(req,timeout=60) as r:return r.read().decode('utf-8-sig')
def clip(v,a,b):return max(a,min(v,b))
def norm(p):
 z=sum(p.values());return {k:v/z for k,v in p.items()}
def dc(h,a,rho=-.08):
 h,a=clip(h,.2,4),clip(a,.2,4)
 def ps(v):
  out=[math.exp(-v)]
  for i in range(1,13):out.append(out[-1]*v/i)
  return out
 H,A=ps(h),ps(a);out={'home':0.,'draw':0.,'away':0.}
 for i,p in enumerate(H):
  for j,q in enumerate(A):
   tau=1.
   if i==j==0:tau=1-h*a*rho
   elif i==0 and j==1:tau=1+h*rho
   elif i==1 and j==0:tau=1+a*rho
   elif i==j==1:tau=1-rho
   out['home' if i>j else 'draw' if i==j else 'away']+=p*q*max(tau,0)
 return norm(out)
def result(h,a):return 'home' if h>a else 'away' if h<a else 'draw'
def load():
 raw={k:get(u) for k,u in URLS.items()}
 w=json.loads(raw['wc'])['matches']
 games=[]
 for x in w:
  ft=x['score']['ft']
  games.append(dict(date=x['date'],home=N(x['team1']),away=N(x['team2']),
    hg=ft[0],ag=ft[1],group=x.get('group'),round=x['round'],
    et=x['score'].get('et'),pen=x['score'].get('p')))
 if len(games)!=104 or len({(g['date'],g['home'],g['away']) for g in games})!=104:
  raise ValueError('Expected 104 unique official WC matches')
 secondary=list(csv.DictReader(io.StringIO(raw['detail'])))
 stats=list(csv.DictReader(io.StringIO(raw['stats'])))
 meta=list(csv.DictReader(io.StringIO(raw['meta'])))
 if len(secondary)!=104 or len(stats)!=208 or len(meta)!=104:
  raise ValueError('Incomplete 104/208 match-stat coverage')
 bymeta={r['match_id']:r for r in meta}
 # Source A uses stadium-local dates; Source B uses UTC dates.
 # Validate the same ordered teams with at most one-day clock rollover.
 bykey={(g['home'],g['away']):g for g in games}
 if len(bykey)!=104:raise ValueError('Repeated national pairing needs explicit disambiguation')
 bynum=defaultdict(list)
 for s in stats:bynum[s['match_id']].append(s)
 for s in secondary:
  key=(N(s['home_team_name']),N(s['away_team_name']))
  if key not in bykey:raise ValueError('Secondary team identity mismatch '+str(key))
  g=bykey[key]
  if abs((date.fromisoformat(g['date'])-date.fromisoformat(s['date'])).days)>1:
   raise ValueError('Fixture sources disagree by more than one calendar day')
  match_shots=bynum[s['match_id']]
  if len(match_shots)!=2:raise ValueError('Wrong shot event coverage')
  reference=bymeta.get(s['match_id'])
  if reference is None or [x['team_id'] for x in match_shots]!=[
      reference['home_team_id'],reference['away_team_id']]:
   raise ValueError('Team-shot row ordering does not match official home/away side')
  verified= g['et'] if g['et'] else [g['hg'],g['ag']]
  if verified!=[int(s['home_score']),int(s['away_score'])]:
   raise ValueError('Contradictory official final score for fixture '+s['match_id'])
  g.update(id=int(s['match_id']),stage=s['stage_name'],venue=s['country'],
    xh=float(s['home_xg']),xa=float(s['away_xg']),
    sh=int(match_shots[0]['total_shots']),sa=int(match_shots[1]['total_shots']))
 games.sort(key=lambda x:(x['date'],x['id']))
 history=[]
 for r in csv.DictReader(io.StringIO(raw['intl'])):
  if '2014-01-01'<=r['date']<'2026-06-11':
   history.append(dict(date=r['date'],home=N(r['home_team']),away=N(r['away_team']),
     hg=int(r['home_score']),ag=int(r['away_score']),
     neutral=r['neutral'].upper()=='TRUE',friendly=r['tournament']=='Friendly'))
 history.sort(key=lambda x:(x['date'],x['home'],x['away']))
 if len(history)<5000:raise ValueError('Historical national-team evidence too sparse')
 return games,history
def forecast(games,history):
 ratings=defaultdict(lambda:1500.)
 form=defaultdict(list)
 def advance(batch,worldcup=False):
  changes=defaultdict(float)
  for g in batch:
   h,a=g['home'],g['away'];H,A=ratings[h],ratings[a]
   bias=0 if g.get('neutral',True) else 55
   ph=1/(1+10**(-((H+bias-A)/400)))
   k=22 if worldcup else 13 if g.get('friendly') else 18
   v=k*((1 if g['hg']>g['ag'] else .5 if g['hg']==g['ag'] else 0)-ph)
   changes[h]+=v;changes[a]-=v
   for team,gf,ga,op,xf,xa,shots,allowed in [
     (h,g['hg'],g['ag'],A,g.get('xh'),g.get('xa'),g.get('sh'),g.get('sa')),
     (a,g['ag'],g['hg'],H,g.get('xa'),g.get('xh'),g.get('sa'),g.get('sh'))]:
    form[team].append(dict(date=g['date'],gf=gf,ga=ga,opp=op,
       wc=worldcup,xf=xf,xa=xa,sf=shots,sa=allowed))
  for team,v in changes.items():ratings[team]+=v
 for _,batch in itertools.groupby(history,key=lambda g:g['date']):advance(list(batch))
 result_rows=[]
 def nat(team,day):
  past=[z for z in form[team] if '2021-01-01'<=z['date']<day][-18:]
  if not past:return (1.,1.,0)
  dt=date.fromisoformat(day);w=G=A=0.
  for z in past:
   age=(dt-date.fromisoformat(z['date'])).days
   weight=2**(-age/420)
   adj=clip(10**((z['opp']-1500)/2000),.72,1.38)
   G+=weight*z['gf']*adj;A+=weight*z['ga']/adj;w+=weight
  n=len(past)
  return (clip(((G/w*n+6*1.3)/(n+6))/1.3,.48,1.95),
          clip(((A/w*n+6*1.3)/(n+6))/1.3,.48,1.95),n)
 def shot(team,day):
  past=[z for z in form[team] if z['wc'] and z['date']<day][-6:];n=len(past)
  # Never fabricate earlier shot records: 6 pseudo-observations are stated priors.
  xf=(sum(z['xf'] for z in past)+6*1.3)/(n+6)
  xa=(sum(z['xa'] for z in past)+6*1.3)/(n+6)
  sf=(sum(z['sf'] for z in past)+6*12)/(n+6)
  sa=(sum(z['sa'] for z in past)+6*12)/(n+6)
  return dict(n=n,xf=xf,xa=xa,sf=sf,sa=sa,quality=xf/sf)
 for day,group in itertools.groupby(games,key=lambda x:x['date']):
  today=list(group)
  for g in today:
   h,a=g['home'],g['away']
   host={'Mexico':'MEX','Canada':'CAN','United States':'USA'}
   hboost=70 if h in host and host[h]==g['venue'] else 0
   aboost=70 if a in host and host[a]==g['venue'] else 0
   difference=ratings[h]-ratings[a]+hboost-aboost
   pwin=1/(1+10**(-difference/400))
   draw=clip(.275*(1-.17*abs(difference)/400),.13,.36)
   elo={'home':(1-draw)*pwin,'draw':draw,'away':(1-draw)*(1-pwin)}
   nh,dh,nph=nat(h,day);na,da,npa=nat(a,day)
   gh=clip(1.31*nh*da*math.exp(clip(difference,-500,500)/2100),.25,3.50)
   ga=clip(1.31*na*dh*math.exp(-clip(difference,-500,500)/2100),.25,3.50)
   goal=dc(gh,ga)
   hybrid=norm({z:.65*goal[z]+.35*elo[z] for z in goal})
   H,A=shot(h,day),shot(a,day)
   def boost(s,o):
    xg=clip(s['xf']/1.3*o['xa']/1.3,.55,1.7)
    volume=clip(s['sf']/12*o['sa']/12,.58,1.65)
    quality=clip(s['quality']/(1.3/12),.7,1.35)
    return xg**.35*volume**.25*quality**.30
   model_shot=dc(gh*boost(H,A),ga*boost(A,H))
   stage1=norm({z:.5*goal[z]+.5*model_shot[z] for z in goal})
   models={'wc_stage1_adapted':stage1,'goal_dc':goal,'elo':elo,
     'goal_elo_hybrid':hybrid,'uniform':{'home':.365,'draw':.27,'away':.365}}
   actual=result(g['hg'],g['ag']);report={}
   for k,p in models.items():
    top=max(('home','draw','away'),key=lambda z:p[z])
    report[k]={'pick':top,'correct':int(top==actual),
      'log_loss':-math.log(max(p[actual],1e-12)),
      'brier':sum((p[z]-(z==actual))**2 for z in p),
      'probabilities':p}
   result_rows.append(dict(match_id=g['id'],date=day,stage=g['stage'],
      group=g['group'],home=h,away=a,score_90=f"{g['hg']}-{g['ag']}",
      score_after_extra='-'.join(map(str,g['et'])) if g['et'] else '',
      penalties='-'.join(map(str,g['pen'])) if g['pen'] else '',
      actual_90=actual,prediction=report['wc_stage1_adapted']['pick'],
      correct=report['wc_stage1_adapted']['correct'],
      probability_home=stage1['home'],probability_draw=stage1['draw'],
      probability_away=stage1['away'],goals_expected_home=gh,goals_expected_away=ga,
      prior_international_h=nph,prior_international_a=npa,
      prior_wc_shots_h=H['n'],prior_wc_shots_a=A['n'],
      host_advantage_h=hboost>0,host_advantage_a=aboost>0,
      pregame_elo_h=ratings[h],pregame_elo_a=ratings[a],
      postgame_xg_h=g['xh'],postgame_xg_a=g['xa'],
      postgame_shots_h=g['sh'],postgame_shots_a=g['sa'],models=report))
  advance([dict(**g,neutral=True) for g in today],worldcup=True)
 if len(result_rows)!=104:raise ValueError('Did not model all 104 World Cup fixtures')
 return result_rows
def metrics(rows,key):
 n=len(rows)
 if n==0:return {'n':0}
 a=[x['models'][key] for x in rows]
 return dict(n=n,correct=sum(y['correct'] for y in a),
    accuracy=sum(y['correct'] for y in a)/n,
    log_loss=sum(y['log_loss'] for y in a)/n,
    brier=sum(y['brier'] for y in a)/n,
    picks={z:sum(y['pick']==z for y in a) for z in ('home','draw','away')})
def main():
 games,history=load()
 rows=forecast(games,history)
 names=list(rows[0]['models'])
 summary={'status':'RETROSPECTIVE NATIONAL ADAPTATION; NOT UNDERSTAT XGQ',
  'historical_results_count':len(history),'match_count':len(rows),
  'training_end':'2026-06-10','exact_per_shot_xgq_available':False,
  'summary':{k:metrics(rows,k) for k in names},
  'groups':{g:{k:metrics([r for r in rows if r['group']==g],k) for k in names}
    for g in sorted(set(r['group'] for r in rows if r['group']))},
  'stages':{st:{k:metrics([r for r in rows if r['stage']==st],k) for k in names}
    for st in sorted(set(r['stage'] for r in rows))},
  'teams':{t:metrics([r for r in rows if t in (r['home'],r['away'])],'wc_stage1_adapted')
     for t in sorted(set(r['home'] for r in rows)|set(r['away'] for r in rows))},
  '90min_draws':sum(r['actual_90']=='draw' for r in rows),
  'extra_time_games':sum(bool(r['score_after_extra']) for r in rows),
  'matches_with_any_earlier_wc_xg':sum(r['prior_wc_shots_h']>0 or r['prior_wc_shots_a']>0 for r in rows),
  'methods':['International matches Elo (day lagged)','18-match opponent-adjusted goals, half-life 420d',
    'True hosts only, no arbitrary home bias','Prior World Cup match xG+shots; 6 pseudo-games prior',
    'Phase 1 transferred weights .50 goal / .50 shot; volume .25; xG/shot proxy .30',
    '90-minute results only, extra time and penalties reported separately',
    'No shot-level per-event XGQ, no genuine pre-2026 xG'],
  'sources':URLS}
 (OUT/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
 (OUT/'matches.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2))
 cols=[z for z in rows[0] if z!='models']
 with (OUT/'matches.csv').open('w',newline='',encoding='utf-8-sig') as fp:
  w=csv.DictWriter(fp,fieldnames=cols);w.writeheader()
  w.writerows([{k:r[k] for k in cols} for r in rows])
 print(json.dumps({'match_count':len(rows),'results':summary['summary'],
  'draws':summary['90min_draws'],'stage1_shot_coverage':
     summary['matches_with_any_earlier_wc_xg']},ensure_ascii=False))
if __name__=='__main__':main()
