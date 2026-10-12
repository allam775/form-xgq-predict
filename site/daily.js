// Independent daily, forward-locked five-league model dashboard.
// Only display published, model-derived 1X2 and verified final outcomes.
// Raw provider shot histories never leave the private database.
const DAILY_LOGO_ROOT='https://raw.githubusercontent.com/JoseArroyave/football-logos/main/logos/';
const dailyNorm = name => String(name||'').normalize('NFKD')
 .replace(/[\u0300-\u036f]/g,'').toLowerCase().replace(/&/g,' and ')
 .replace(/[^a-z0-9]+/g,' ').trim().replace(/^(fc|afc)\s+|\s+(fc|afc)$/g,'').trim();
const cairoDate = () => {
 const parts=new Intl.DateTimeFormat('en-GB',{timeZone:'Africa/Cairo',day:'2-digit',month:'2-digit',year:'numeric'}).formatToParts(new Date());
 const item=kind=>parts.find(v=>v.type===kind)?.value||'';
 return item('year')+'-'+item('month')+'-'+item('day');
};
const cairoTime = value => {
 const d=new Date(value);
 return Number.isFinite(d.getTime())?d.toLocaleTimeString('en-GB',{
  timeZone:'Africa/Cairo',hour:'2-digit',minute:'2-digit',hour12:false})+' Cairo':'Time unverified';
};
const dailyPct = value => typeof value==='number'&&Number.isFinite(value)&&value>=0&&value<=1
 ?(value*100).toFixed(1)+'%':'—';
const dailyFloat = value => typeof value==='number'&&Number.isFinite(value)?value.toFixed(3):'—';
const dailyLabels={home:'Home win',draw:'Draw',away:'Away win'};
let dailyCrests={},dailyFixtures=[];
function clubCrest(league,name){
 const link=dailyCrests[league+'|'+dailyNorm(name)];
 return typeof link==='string'&&link.startsWith(DAILY_LOGO_ROOT)&&!/[<>"'\s]/.test(link)?link:null;
}
async function loadCrests(){
 try {
  const r=await fetch('/club-crests.json',{cache:'force-cache'});
  if(!r.ok)throw Error('No club crest mapping');
  const mapping=await r.json();
  dailyCrests=mapping&&typeof mapping==='object'&&!Array.isArray(mapping)?mapping:{};
  render();
  renderDaily();
 }catch{dailyCrests={}}
}
function dailyCard(item){
 const p=item.probabilities||{};
 const scores=['home','draw','away'].map(key=>Number(p[key]));
 if(scores.some(x=>!Number.isFinite(x)||x<0||x>1)||
    Math.abs(scores.reduce((a,b)=>a+b,0)-1)>.015)return '';
 const home=crest(item.home,clubCrest(item.league,item.home));
 const away=crest(item.away,clubCrest(item.league,item.away));
 const pick=dailyLabels[item.pick]||'No pick';
 let status='<span>Awaiting verified final result</span>';
 if(item.graded&&item.actual&&
    Number.isInteger(item.actual.home_goals)&&Number.isInteger(item.actual.away_goals)){
  const outcome=item.actual;
  status='<span class="'+(outcome.correct?'grade-good':'grade-bad')+'">'+
     (outcome.correct?'✓ Correct':'✕ Incorrect')+' · Final '+
     htmlEscape(outcome.home_goals)+'–'+htmlEscape(outcome.away_goals)+'</span>';
 }
 return '<article class="daily-match glass">'+
  '<div class="daily-match-meta"><span>'+htmlEscape(leagueName(item.league))+'</span>'+
  '<time datetime="'+htmlEscape(item.kickoff_utc)+'">'+htmlEscape(cairoTime(item.kickoff_utc))+'</time></div>'+
  '<div class="daily-versus">'+
   '<div class="daily-club">'+home+'<b>'+htmlEscape(item.home)+'</b></div>'+
   '<span class="daily-vs">VS</span>'+
   '<div class="daily-club">'+away+'<b>'+htmlEscape(item.away)+'</b></div>'+
  '</div>'+
  '<div class="daily-pickline"><strong>XGQ pre-match 1X2</strong><span class="daily-pick">'+htmlEscape(pick)+'</span></div>'+
  '<div class="daily-prob-bar">'+scores.map((v)=>'<span style="width:'+(v*100).toFixed(3)+'%"></span>').join('')+'</div>'+
  '<div class="daily-prob-label">'+scores.map((v,i)=>'<div>'+dailyPct(v)+
     '<small>'+['Home','Draw','Away'][i]+'</small></div>').join('')+'</div>'+
  '<div class="daily-status-row">'+status+'<span>Frozen '+htmlEscape(cairoTime(item.frozen_at_utc))+'</span></div>'+
 '</article>';
}
function renderDaily(){
 const node=$('daily-cards');
 if(!node)return;
 const cards=dailyFixtures.map(dailyCard).filter(Boolean);
 node.innerHTML=cards.length?cards.join(''):
 '<div class="daily-empty glass">No frozen 1X2 predictions are available for this date and competition. Matches are never invented or backfilled after kickoff.</div>';
 $('daily-count').textContent=cards.length+' frozen';
}
function renderChallenger(c){
 const node=$('daily-challenger-report');
 if(!node)return;
 if(!c){
  node.textContent='No forward-tested challenger audit is available yet. Production XGQ remains unchanged.';
  return;
 }
 const n=Number(c.paired_verified_matches)||0, target=Number(c.min_forward_pairs)||350;
 const x=c.xgq||{},g=c.goal_fixed_rho||{};
 const progress=Math.min(100,Math.max(0,100*n/target));
 const verdict=c.gate_met?'Statistical promotion gate reached — manual review required':
  n<target?'Accumulating genuine future results. Do not promote based on historical tuning.':
  'No statistically supported promotion. Keep production unchanged.';
 node.innerHTML=
  '<p><strong>'+htmlEscape(n)+' / '+htmlEscape(target)+'</strong> paired, verified matches · '+
  htmlEscape(verdict)+'</p>'+
  '<div class="shadow-progress"><span style="width:'+progress.toFixed(2)+'%"></span></div>'+
  '<div class="audit-scroll"><table class="audit-table"><thead><tr><th>Model</th><th>Hit rate</th><th>Log Loss ↓</th><th>Brier ↓</th></tr></thead><tbody>'+
  '<tr><th>Production XGQ</th><td>'+dailyPct(x.top_choice_accuracy)+'</td><td>'+
   dailyFloat(x.log_loss)+'</td><td>'+dailyFloat(x.brier)+'</td></tr>'+
  '<tr><th>Fixed-rho goal challenger</th><td>'+dailyPct(g.top_choice_accuracy)+'</td><td>'+
   dailyFloat(g.log_loss)+'</td><td>'+dailyFloat(g.brier)+'</td></tr>'+
  '</tbody></table></div>';
}

async function loadDaily(){
 const date=$('daily-date').value,league=$('daily-league').value,info=$('daily-update');
 if(!/^\d{4}-\d{2}-\d{2}$/.test(date)){info.textContent='Select a valid date.';return}
 info.textContent='Loading verified daily ledger…';
 try{
  const params=new URLSearchParams({date});
  if(league!=='all')params.set('league',league);
  const results=await Promise.all([
   fetch('/api/daily-forecasts?'+params.toString(),{cache:'no-store'}),
   fetch('/api/daily-performance',{cache:'no-store'})
  ]);
  if(results.some(r=>!r.ok))throw Error('Daily endpoint unavailable');
  const [todayRows,score]=await Promise.all(results.map(r=>r.json()));
  dailyFixtures=Array.isArray(todayRows.forecasts)?todayRows.forecasts:[];
  renderDaily();
  $('daily-frozen').textContent=(Number(score.total_frozen)||0).toLocaleString('en-GB');
  $('daily-graded').textContent=(Number(score.graded)||0).toLocaleString('en-GB');
  $('daily-accuracy').textContent=score.graded>0?dailyPct(score.accuracy):'—';
  $('daily-correct').textContent=score.graded>0?score.correct+' correct out of '+score.graded+' verified results':'Awaiting first verified result';
  $('daily-loss').textContent=score.graded>0?dailyFloat(score.log_loss)+' / '+dailyFloat(score.brier):'— / —';
  renderChallenger(score.comparison);
  const perLeague=Array.isArray(score.by_league)?score.by_league:[];
  $('daily-league-history').innerHTML=perLeague.length?perLeague.map(x=>
   '<div class="daily-history-chip"><span>'+htmlEscape(leagueName(x.league))+'</span>'+
   '<b>'+dailyPct(x.graded>0?x.correct/x.graded:NaN)+'</b>'+
   '<span>'+htmlEscape(x.correct)+'/'+htmlEscape(x.graded)+' correct</span></div>'
  ).join(''):'No eligible final results have been scored yet. This is not the historical hit rate.';
  info.textContent=dailyFixtures.length+' frozen forecasts · '+date+' · '+
   (league==='all'?'all five leagues':leagueName(league));
 }catch{
  dailyFixtures=[];renderDaily();
  info.textContent='Daily model temporarily unavailable — please retry.';
  $('daily-league-history').textContent='Could not verify daily accuracy.';
  ['daily-frozen','daily-graded','daily-accuracy'].forEach(id=>$(id).textContent='—');
  $('daily-correct').textContent='No confirmed result loaded';
  $('daily-loss').textContent='— / —';
  renderChallenger(null);
 }
}
$('daily-date').value=cairoDate();
$('daily-date').addEventListener('change',loadDaily);
$('daily-league').addEventListener('change',loadDaily);
$('daily-reload').addEventListener('click',loadDaily);
loadCrests();
loadDaily();
