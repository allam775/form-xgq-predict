import assert from 'node:assert/strict';
import worker from '../worker/index.js';

const prepare=(sql)=>({
  all: async()=>({results:sql.includes('release_metadata')?[{k:'as_of',v:'2026-10-10'},{k:'coverage',v:'{"xgq_forecasts":0}'}]:[]}),
  bind:(...values)=>({all:async()=>({results:[]})})
});
const env={DB:{prepare},ASSETS:{fetch:async()=>new Response('site')}};
const get=(path,options)=>worker.fetch(new Request(`https://example.workers.dev${path}`,options),env);
const health=await (await get('/api/health')).json();
assert.equal(health.status,'ready');
assert.equal(health.coverage.xgq_forecasts,0);
assert.deepEqual((await (await get('/api/forecasts?limit=12')).json()).forecasts,[]);
assert.deepEqual((await (await get('/api/unavailable')).json()).unavailable,[]);
assert.equal((await get('/api/forecasts?date=2026-XX-99')).status,400);
assert.equal((await get('/api/forecasts',{method:'POST'})).status,405);
assert.equal((await get('/unknown')).status,200);
// Private team-form responses are not cacheable and do not allow third-party CORS.
const privateDb={DB:{prepare:(sql)=>({bind:(id)=>({first:async()=>sql.includes('private_understat_form')?{payload:JSON.stringify({team:'liverpool',windows:{'5':{n:5}}})}:null,all:async()=>({results:[{id:'en.1|liverpool'}]})}),all:async()=>({results:[{id:'en.1|liverpool'}]})})},ASSETS:env.ASSETS};
const privateGet=(path)=>worker.fetch(new Request(`https://example.workers.dev${path}`),privateDb);
const formResponse=await privateGet('/api/team-form?league=en.1&team=liverpool');
assert.equal(formResponse.status,200);
assert.equal(formResponse.headers.get('cache-control'),'private, no-store');
assert.equal(formResponse.headers.get('access-control-allow-origin'),null);
assert.equal((await formResponse.json()).form.windows['5'].n,5);
assert.equal((await privateGet('/api/team-form?league=en.1&team=x%27%20OR%201%3D1')).status,400);
const listResponse=await privateGet('/api/team-form-teams?league=en.1');
assert.deepEqual((await listResponse.json()).teams,['en.1|liverpool']);
// Weekly metrics stay private and do not expose provider rows.
const auditDb={DB:{prepare:(sql)=>({first:async()=>sql.includes('understat_championship_report')?{v:JSON.stringify({status:'retrospective',historical_matches:803,test_eligible:70,test_scores:{xgq:{log_loss:1.04}}})}:null})},ASSETS:env.ASSETS};
const auditRes=await worker.fetch(new Request('https://example.workers.dev/api/research-weekly'),auditDb);
assert.equal(auditRes.headers.get('cache-control'),'private, no-store');
assert.equal(auditRes.headers.get('access-control-allow-origin'),null);
const auditData=await auditRes.json();
assert.equal(auditData.report.test_scores.xgq.log_loss,1.04);
const unavailable=await worker.fetch(new Request('https://example.com/api/health'),{ASSETS:env.ASSETS});
assert.equal(unavailable.status,503);
console.log('Worker API mock-smoke: 15 checks passed');
