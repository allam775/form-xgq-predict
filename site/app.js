// XGQ Predict v0.2: browser is purely a read-only viewer of Cloudflare D1.
// Never generate synthetic probabilities or treat a scheduled match as a verified forecast.
const $ = id => document.getElementById(id);
const htmlEscape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const state = {forecasts:[], unavailable:[], meta:null, filter:'all'};
const isoLocal = dt => `${dt.getFullYear()}-${String(dt.getMonth()+1).padStart(2,'0')}-${String(dt.getDate()).padStart(2,'0')}`;
const today = () => isoLocal(new Date());
const plusDays = count => {const d = new Date();d.setDate(d.getDate()+count);return isoLocal(d)};
const probability = v => `${(Math.max(0, Math.min(1, Number(v) || 0))*100).toFixed(1)}%`;
const dateLabel = value => {try{return new Date(`${value}T12:00:00`).toLocaleDateString('en-GB',{weekday:'short',month:'short',day:'numeric'})}catch{return value}};
const initials = name => String(name||'?').split(/\s+/).filter(w=>w.length>1).slice(0,2).map(w=>w[0]).join('').toUpperCase() || String(name||'?').slice(0,2).toUpperCase();
function crest(name, url){
 const base=`<span class="crest-placeholder" aria-label="${htmlEscape(name)} badge unavailable">${htmlEscape(initials(name))}</span>`;
 if(typeof url==='string' && /^https:\/\/[^\s"'<>]+$/i.test(url))return `<span class="crest-wrap">${base}<img class="crest-logo" src="${htmlEscape(url)}" alt="${htmlEscape(name)} club crest" loading="lazy" referrerpolicy="no-referrer" onerror="this.remove()"/></span>`;
 return base;
}
const pendingReasons = {'insufficient_verified_shots':'Verified team shot history insufficient', 'stale_xgq':'Verified shot history is too old', 'small_league_sample':'League sample too small', 'invalid_league_xgq':'Invalid league shot quality', 'invalid_teams':'Fixture identity unverified', 'not_upcoming':'Fixture is not upcoming'};
const pendingReason = reason => pendingReasons[reason] || 'Shot-level coverage unavailable';
const leagueNames = {'en.1':'Premier League','de.1':'Bundesliga','es.1':'La Liga','it.1':'Serie A','fr.1':'Ligue 1'};
const leagueName = league => leagueNames[league] || league || 'Competition';
const matchAllowed = m => {
 const term=$('search').value.toLowerCase().trim();const league=$('league').value;
 return (state.filter==='all'||state.filter==='today'&&m.date===today()||state.filter==='week'&&m.date>=today()&&m.date<=plusDays(7)) && (league==='all'||league===m.league) && (!term||`${m.home} ${m.away}`.toLowerCase().includes(term));
};
function matchCard(m){
 const p=m.probabilities||{};
 const home=Math.max(0,100*(Number(p.home)||0));const draw=Math.max(0,100*(Number(p.draw)||0));const away=Math.max(0,100*(Number(p.away)||0));
 const sum=home+draw+away;
 if(Math.abs(sum-100)>1||[home,draw,away].some(x=>!Number.isFinite(x)))return '';
 const top=Array.isArray(p.scorelines)?p.scorelines.slice(0,3):[];
 return `<article class="match-card glass"><div class="match-meta"><span class="competition-label"><i></i> ${htmlEscape(m.league_name||leagueName(m.league))}</span><span>${htmlEscape(dateLabel(m.date))} ${m.same_day_unverified?'· Kickoff not confirmed':''}</span></div>
 <div class="team-layout"><div class="team">${crest(m.home,m.home_logo_url)}<strong>${htmlEscape(m.home)}</strong><small>HOME</small></div><div class="match-versus"><span>VS</span><small>${htmlEscape(m.time_source||'Time unverified')}</small></div><div class="team">${crest(m.away,m.away_logo_url)}<strong>${htmlEscape(m.away)}</strong><small>AWAY</small></div></div>
 <div class="verified-mark"><span>◉ VERIFIED XGQ MODEL</span><span>Shot-level evidence</span></div>
 <div class="probability-bar"><span style="width:${home}%"></span><span style="width:${draw}%"></span><span style="width:${away}%"></span></div>
 <div class="probability-labels"><div><strong>${probability(p.home)}</strong><small>HOME</small></div><div><strong>${probability(p.draw)}</strong><small>DRAW</small></div><div><strong>${probability(p.away)}</strong><small>AWAY</small></div></div>
 <div class="card-foot"><span>History: ${htmlEscape(m.history_home)} / ${htmlEscape(m.history_away)} games</span><span>${top.length?'Top score: '+htmlEscape(top[0].score):'Scoreline unavailable'}</span></div></article>`;
}
function fixtureCard(m){return `<div class="fixture-row"><div class="fixture-date">${htmlEscape(dateLabel(m.date))}<small>${htmlEscape(leagueName(m.league))}</small></div><div class="fixture-clubs"><span class="tiny-crest">${htmlEscape(initials(m.home))}</span><strong>${htmlEscape(m.home)}</strong><span class="fixture-vs">vs</span><strong>${htmlEscape(m.away)}</strong><span class="tiny-crest">${htmlEscape(initials(m.away))}</span></div><span class="fixture-reason" title="${htmlEscape(pendingReason(m.reason))}">◌ ${htmlEscape(pendingReason(m.reason))}</span></div>`}
function render(){
 const forecasts=state.forecasts.filter(matchAllowed);
 $('cards').innerHTML=forecasts.map(matchCard).join('');
 $('count-chip').textContent=`${forecasts.length} verified ${forecasts.length===1?'prediction':'predictions'}`;
 const node=$('load-indicator');node.style.display=forecasts.length?'none':'flex';
 if(!forecasts.length){
  const ready=state.meta?.status==='ready';
  node.classList.remove('error');
  node.innerHTML=`<span class="empty-orb">◎</span><h3>${ready?'No qualified XGQ forecasts yet':'Awaiting the first verified release'}</h3><p>${ready?'We track fixtures below, but recent shot-level evidence does not meet the threshold for probabilities.':'Your independent website is online. Run the cloud data pipeline to publish coverage without inventing predictions.'}</p>`;
 }
 const pending=state.unavailable.filter(matchAllowed).slice(0,60);
 $('unavailable-count').textContent=`${pending.length} shown`;
 $('unavailable-list').innerHTML=pending.length?pending.map(fixtureCard).join(''):`<div class="fixture-loading">${state.meta?.status==='ready'?'No tracked unqualified fixtures match these filters.':'No fixture snapshot published yet.'}</div>`;
}
async function load(){
 try{
  const result=await Promise.all(['/api/health','/api/forecasts?limit=200','/api/unavailable'].map(endpoint=>fetch(endpoint,{cache:'no-store'})));
  if(result.some(r=>!r.ok))throw Error('The Cloudflare API could not load the data.');
  const [health, forecasts, unavailable]=await Promise.all(result.map(r=>r.json()));
  state.meta=health;state.forecasts=Array.isArray(forecasts.forecasts)?forecasts.forecasts:[];state.unavailable=Array.isArray(unavailable.unavailable)?unavailable.unavailable:[];
  $('shot-count').textContent=(health.coverage?.verified_shot_matches??0).toLocaleString();
  $('prediction-count').textContent=(health.coverage?.xgq_forecasts??0).toLocaleString();
  $('asof-header').textContent=health.as_of?`DATA AS OF ${health.as_of}`:'NO PUBLISHED DATA';
  $('build-date').textContent=health.generated_at||'No dataset has been published';
  const days=health.as_of?Math.floor((Date.now()-Date.parse(`${health.as_of}T00:00:00Z`))/86400000):Infinity;
  const ready=health.status==='ready';
  // A fresh refresh job can still have years-old underlying shot evidence.
  const latestMatch=health.coverage?.latest_verified_match;
  const evidenceAge=latestMatch?Math.floor((Date.now()-Date.parse(`${latestMatch}T00:00:00Z`))/86400000):Infinity;
  const evidenceOld=evidenceAge>120;
  $('data-state').textContent=!ready?'Pending':days>2?'Stale':evidenceOld?'Historical':'Online';
  $('data-updated').textContent=!ready?'Awaiting first release':`Latest verified shot match: ${latestMatch||'unavailable'}`;
  $('side-status').textContent=!ready?'No data published':days>2?'Snapshot needs refresh':evidenceOld?'Historical shot evidence only':'Verified data online';
  $('side-dot').classList.toggle('live',ready&&days<=2);
  $('coverage-label').textContent=ready?`${state.forecasts.length} verified predictions`:'Awaiting published snapshot';
  const breakdown=health.coverage?.withheld_reasons||{};
  const shortfall=Object.entries(breakdown).sort((a,b)=>b[1]-a[1]).slice(0,2).map(([reason,count])=>`${count} ${pendingReason(reason).toLowerCase()}`).join('; ');
  $('coverage-text').textContent=ready?`${health.coverage?.withheld_no_verified_xgq||0} tracked fixtures withheld. ${shortfall||'Insufficient verified shot evidence'}. Latest verified match: ${latestMatch||'unknown'}.`:'The Worker is online. Link the GitHub scheduled pipeline to publish data and show coverage.';
  const e=health.evaluation||{};
  $('evidence-note').textContent=e.status==='retrospective'?`Historical walk-forward evaluation: ${e.tested} matches · log loss ${e.log_loss} · Brier ${e.brier} · first-choice accuracy ${probability(e.top_choice_accuracy)}. No guarantee of future accuracy.`:`Independent accuracy assessment unavailable (${e.tested||0} evaluated historical matches). We do not publish a performance claim without adequate tests.`;
  const currentLeague=$('league').value;
  $('league').innerHTML='<option value="all">All competitions</option>';
  for(const code of [...new Set([...state.forecasts,...state.unavailable].map(m=>m.league))].filter(Boolean).sort()){$('league').add(new Option(leagueName(code),code))}
  $('league').value=[...$('league').options].some(opt=>opt.value===currentLeague)?currentLeague:'all';
 }catch(error){
  $('side-status').textContent='Cloud API unavailable';
  $('data-state').textContent='Unavailable';
  $('coverage-label').textContent='Could not connect';
  $('coverage-text').textContent='Please retry later. No substitute estimates are displayed.';
  $('load-indicator').classList.add('error');
  $('load-indicator').innerHTML=`<span class="empty-orb">!</span><h3>Cannot reach Cloudflare data</h3><p>${htmlEscape(error.message)}</p>`;
  $('unavailable-list').innerHTML='<div class="fixture-loading">Unable to load fixtures.</div>';
 }
 render();
}
for(const button of document.querySelectorAll('[data-filter]'))button.addEventListener('click',()=>{state.filter=button.dataset.filter;document.querySelectorAll('[data-filter]').forEach(b=>b.classList.toggle('active',b===button));render()});
$('search').addEventListener('input',render);
$('league').addEventListener('change',render);
load();
// Understat profiles are computed server-side from private verified match summaries.
// Never derive xGQ from aggregate match xG in the browser.
async function loadFormTeamList(){
 const league=$('form-league').value, select=$('form-team');
 select.replaceChildren(new Option('Choose an available team',''));
 try {
  const response=await fetch('/api/team-form-teams?league='+encodeURIComponent(league),{cache:'no-store'});
  if(!response.ok)throw Error('Unavailable');
  const payload=await response.json();
  const teams=Array.isArray(payload.teams)?payload.teams:[];
  for(const identity of teams){const key=identity.split('|')[1];if(key)select.add(new Option(key.replace(/\b\w/g,c=>c.toUpperCase()),key))}
  if(!teams.length)$('form-output').textContent='No private Understat team history is available yet. The historical StatsBomb archive is separate.';
 }catch{$('form-output').textContent='Private team form is unavailable. Other site data is unaffected.'}
}
async function loadSelectedForm(){
 const league=$('form-league').value,team=$('form-team').value;
 if(!team){$('form-output').textContent='Choose a team with verified Understat history.';return}
 $('form-output').textContent='Loading verified team form…';
 try{
  const r=await fetch('/api/team-form?league='+encodeURIComponent(league)+'&team='+encodeURIComponent(team),{cache:'no-store'});
  if(!r.ok)throw Error('Form query unavailable');
  const payload=await r.json(), form=payload.form;
  if(!form){$('form-output').textContent='This team has no eligible verified Understat match history yet.';return}
  const blocks=['5','10','20'].map(key=>{const w=form.windows?.[key];
   if(!w)return '';
   return `<div class="form-window"><h3>Last ${key} games (${w.n})</h3><p>Attack XGQ <strong>${Number(w.xgq_for).toFixed(4)}</strong></p><p>Conceded XGQ <strong>${Number(w.xgq_against).toFixed(4)}</strong></p><p>xG / xGA <strong>${Number(w.xg_for).toFixed(2)} / ${Number(w.xg_against).toFixed(2)}</strong></p><p>W–D–L <strong>${w.wins}–${w.draws}–${w.losses}</strong></p></div>`;
  }).join('');
  $('form-output').innerHTML=`<p><strong>${htmlEscape(team)}</strong> · ${htmlEscape(leagueName(league))} · Latest verified match ${htmlEscape(form.last_seen)} · Understat-only calibrated series.</p><div class="form-windows">${blocks}</div>`;
 }catch{$('form-output').textContent='Could not load private team form; no substitute estimates were generated.'}
}
$('form-league').addEventListener('change',loadFormTeamList);
$('form-load').addEventListener('click',loadSelectedForm);
loadFormTeamList();
