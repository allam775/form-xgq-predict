import assert from 'node:assert/strict';
import worker from '../worker/index.js';

const forecast={
 id:'en.1|31239',date:'2026-10-12',league:'en.1',
 home:'Coventry',away:'Newcastle United',kickoff_utc:'2026-10-12T19:00:00+00:00',
 frozen_at_utc:'2026-10-12T13:20:40+00:00',status:'frozen',
 source:'Understat PRIVATE',source_match_id:'31239',
 prior_verified_matches:600,home_xgq:0.99,
 picks:{xgq_production_formula:'home'},
 models:{xgq_production_formula:{home:0.45,draw:0.29,away:0.26}}
};
const graded={
 id:'en.1|31239',outcome:'away',hg:0,ag:1,
 provider_shot_level_private_payload:'DO NOT LEAK',
 models:{xgq_production_formula:{correct:false,log_loss:1.3471,brier:0.8125}}
};
const sqlCalls=[];
const db={
 prepare(sql){
  sqlCalls.push(sql);
  return {
   bind(...args){
    return {all:async()=>({results:[{forecast:JSON.stringify(forecast),grade:JSON.stringify(graded)}],
     args})};
   },
   async first(){
    if(sql.includes('understat_forward_shadow_championship'))return {v:JSON.stringify({
      status:'collecting_prospective_evidence',primary:'xgq_production_formula',challenger:'goal_fixed_rho',
      paired_verified_matches:1,min_forward_pairs:350,gate_met:false,
      xgq:{tested:1,top_choice_accuracy:0,log_loss:1.3471,brier:0.8125},
      goal_fixed_rho:{tested:1,top_choice_accuracy:1,log_loss:0.6,brier:0.3},
      by_league_paired_counts:{'en.1':1},
      private_payload:'DO NOT LEAK',
    })};
    if(sql.includes('COUNT(*) AS n FROM private_daily_forecasts'))return {n:4};
    if(sql.includes('COUNT(*) AS n,')&&sql.includes('private_daily_grades'))
     return {n:1,correct:0,log_loss:1.3471,brier:0.8125};
    return null;
   },
   async all(){
    if(sql.includes('GROUP BY json_extract(f.payload'))return {results:[{league:'en.1',n:1,correct:0}]};
    return {results:[]};
   },
  };
 }
};
const env={DB:db,ASSETS:{fetch:async()=>new Response('site')}};
const get=path=>worker.fetch(new Request('https://xgq.example'+path),env);
const req=await get('/api/daily-forecasts?date=2026-10-12');
assert.equal(req.status,200);
assert.equal(req.headers.get('cache-control'),'private, no-store');
assert.equal(req.headers.get('access-control-allow-origin'),null);
const payload=await req.json();
assert.equal(payload.forecasts.length,1);
assert.equal(payload.forecasts[0].pick,'home');
assert.equal(payload.forecasts[0].probabilities.home,0.45);
assert.equal(payload.forecasts[0].graded,true);
assert.equal(payload.forecasts[0].actual.correct,false);
assert.equal(payload.forecasts[0].actual.home_goals,0);
assert.equal(payload.forecasts[0].source,undefined);
assert.equal(payload.forecasts[0].source_match_id,undefined);
assert.equal(payload.forecasts[0].home_xgq,undefined);
assert.ok(!JSON.stringify(payload).includes('DO NOT LEAK'));
assert.equal((await get('/api/daily-forecasts?date=2026-XX-12')).status,400);
assert.equal((await get('/api/daily-forecasts?date=2026-10-12&league=bad')).status,400);
const performanceRes=await get('/api/daily-performance');
assert.equal(performanceRes.status,200);
assert.equal(performanceRes.headers.get('cache-control'),'private, no-store');
const score=await performanceRes.json();
assert.equal(score.total_frozen,4);
assert.equal(score.graded,1);
assert.equal(score.pending,3);
assert.equal(score.accuracy,0);
assert.equal(score.log_loss,1.3471);
assert.equal(score.by_league[0].league,'en.1');
assert.equal(score.comparison.paired_verified_matches,1);
assert.equal(score.comparison.min_forward_pairs,350);
assert.equal(score.comparison.gate_met,false);
assert.equal(score.comparison.goal_fixed_rho.log_loss,0.6);
assert.ok(!JSON.stringify(score.comparison).includes('DO NOT LEAK'));

assert.ok(sqlCalls.some(sql=>sql.includes('LEFT JOIN private_daily_grades')));
assert.ok(sqlCalls.every(sql=>!sql.includes('private_understat_history')));
console.log('Daily D1 dashboard API contract: 20 checks passed');
