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
const unavailable=await worker.fetch(new Request('https://example.com/api/health'),{ASSETS:env.ASSETS});
assert.equal(unavailable.status,503);
console.log('Worker API mock-smoke: 7 checks passed');
