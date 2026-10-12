// Standalone Cloudflare Worker + D1 API. No tokens/API keys exposed to the browser.
const json = (data, status=200) => new Response(JSON.stringify(data), {
  status, headers: {'content-type':'application/json; charset=utf-8',
   'cache-control':'public, max-age=60', 'x-content-type-options':'nosniff',
   'access-control-allow-origin':'*'}
});
// Derived Understat team-form data is private; never make it public-cacheable.
const privateJson = (data, status=200) => new Response(JSON.stringify(data), {
  status, headers: {'content-type':'application/json; charset=utf-8',
    'cache-control':'private, no-store', 'x-content-type-options':'nosniff'}
});
const decodeMeta = (rows) => {
  const result={};
  for(const r of rows) {
    if(['coverage','evaluation','collection','source_warnings'].includes(r.k)) {
      try {result[r.k]=JSON.parse(r.v)} catch {result[r.k]=r.v}
    } else result[r.k]=r.v;
  }
  return result;
};
export default {
  async fetch(request, env) {
    const url=new URL(request.url);
    if(!url.pathname.startsWith('/api/')) return env.ASSETS.fetch(request);
    if(request.method!=='GET') return json({error:'Method not allowed'},405);
    if(!env.DB) return json({error:'D1 binding missing',code:'NOT_CONFIGURED'},503);
    try {
      if(url.pathname==='/api/health' || url.pathname==='/api/coverage') {
        const {results}=await env.DB.prepare("SELECT k,v FROM release_metadata WHERE generation=(SELECT v FROM metadata WHERE k='published_generation')").all();
        return json({status:results.length?'ready':'not_initialized',...decodeMeta(results)});
      }
      if(url.pathname==='/api/forecasts') {
        const date=url.searchParams.get('date');
        if(date && !/^\d{4}-\d{2}-\d{2}$/.test(date)) return json({error:'Bad date'},400);
        const league=url.searchParams.get('league');
        if(league && !/^[a-z0-9.]{2,20}$/.test(league)) return json({error:'Bad league'},400);
        const limit=Math.min(200,Math.max(1,Number(url.searchParams.get('limit')||100)||100));
        const conditions=[]; const values=[];
        if(date) {conditions.push('fixture_date=?');values.push(date)}
        if(league) {conditions.push('league=?');values.push(league)}
        const sql="SELECT payload FROM forecasts WHERE generation=(SELECT v FROM metadata WHERE k='published_generation')"+(conditions.length?' AND '+conditions.join(' AND '):'')+' ORDER BY fixture_date ASC,league ASC LIMIT ?';
        const {results}=await env.DB.prepare(sql).bind(...values,limit).all();
        return json({forecasts:results.map(r=>JSON.parse(r.payload))});
      }
      // Expose ONLY the model's own frozen 1X2 summary and verified score.
      // Never return private shot history, form samples or provider credentials.
      if(url.pathname==='/api/daily-forecasts') {
        const date=url.searchParams.get('date');
        const league=url.searchParams.get('league');
        if(!date || !/^\d{4}-\d{2}-\d{2}$/.test(date) || !Number.isFinite(Date.parse(date+'T00:00:00Z')))
          return privateJson({error:'Valid date required'},400);
        if(league && !/^(en|de|es|it|fr)\.1$/.test(league))
          return privateJson({error:'Bad league'},400);
        const sql="SELECT f.payload AS forecast,g.payload AS grade FROM private_daily_forecasts f "+
          "LEFT JOIN private_daily_grades g ON g.id=f.id "+
          "WHERE json_extract(f.payload,'$.date')=?"+
          (league?" AND json_extract(f.payload,'$.league')=?":"")+
          " ORDER BY json_extract(f.payload,'$.kickoff_utc') ASC LIMIT 120";
        const {results}=await env.DB.prepare(sql).bind(...(league?[date,league]:[date])).all();
        const items=results.map(r=>{
          const f=JSON.parse(r.forecast),g=r.grade?JSON.parse(r.grade):null;
          const p=f.models?.xgq_production_formula;
          if(f.status!=='frozen'||!p||!['home','draw','away'].every(k=>typeof p[k]==='number'))
            return null;
          return {id:f.id,date:f.date,league:f.league,home:f.home,away:f.away,
            kickoff_utc:f.kickoff_utc,frozen_at_utc:f.frozen_at_utc,
            probabilities:{home:p.home,draw:p.draw,away:p.away},
            pick:f.picks?.xgq_production_formula,
            graded:!!g,actual:g?{home_goals:g.hg,away_goals:g.ag,
              outcome:g.outcome,correct:g.models?.xgq_production_formula?.correct===true}:null};
        }).filter(Boolean);
        return privateJson({date,league:league||'all',forecasts:items});
      }
      if(url.pathname==='/api/daily-performance') {
        const total=await env.DB.prepare("SELECT COUNT(*) AS n FROM private_daily_forecasts").first();
        const scored=await env.DB.prepare(
          "SELECT COUNT(*) AS n, "+
          "SUM(CASE WHEN json_extract(payload,'$.models.xgq_production_formula.correct')=1 THEN 1 ELSE 0 END) AS correct, "+
          "AVG(json_extract(payload,'$.models.xgq_production_formula.log_loss')) AS log_loss, "+
          "AVG(json_extract(payload,'$.models.xgq_production_formula.brier')) AS brier "+
          "FROM private_daily_grades").first();
        const {results}=await env.DB.prepare(
          "SELECT json_extract(f.payload,'$.league') AS league,COUNT(*) AS n,"+
          "SUM(CASE WHEN json_extract(g.payload,'$.models.xgq_production_formula.correct')=1 THEN 1 ELSE 0 END) AS correct "+
          "FROM private_daily_grades g JOIN private_daily_forecasts f ON f.id=g.id "+
          "GROUP BY json_extract(f.payload,'$.league') ORDER BY league").all();
        const count=Number(scored?.n)||0;
        // Owner-computed aggregated forward-only shadow report; never include D1 rows.
        const shadowRow=await env.DB.prepare(
          "SELECT v FROM metadata WHERE k='understat_forward_shadow_championship' LIMIT 1"
        ).first();
        const shadow=shadowRow&&typeof shadowRow.v==='string'?JSON.parse(shadowRow.v):null;
        const comparison=shadow?{
          status:shadow.status,primary:shadow.primary,challenger:shadow.challenger,
          paired_verified_matches:shadow.paired_verified_matches,
          min_forward_pairs:shadow.min_forward_pairs,gate_met:shadow.gate_met===true,
          requires_manual_approval_to_switch:true,
          xgq:shadow.xgq,goal_fixed_rho:shadow.goal_fixed_rho,
          goal_over_xgq_log_loss_gain:shadow.goal_over_xgq_log_loss_gain,
          paired_log_loss_ci95:shadow.paired_log_loss_ci95,
          by_league_paired_counts:shadow.by_league_paired_counts
        }:null;
        return privateJson({status:count?'scored':'awaiting_verified_results',comparison,
          model:'xgq_production_formula',total_frozen:Number(total?.n)||0,
          graded:count,pending:Math.max(0,(Number(total?.n)||0)-count),
          correct:Number(scored?.correct)||0,
          accuracy:count?(Number(scored.correct)||0)/count:null,
          log_loss:count?Number(scored.log_loss):null,
          brier:count?Number(scored.brier):null,
          by_league:results.map(r=>({league:r.league,graded:Number(r.n)||0,correct:Number(r.correct)||0}))});
      }
      // Summary metrics only; Cloudflare Access protects the site and this endpoint.
      // The historical match rows and model input samples never leave private D1.
      if(url.pathname==='/api/research-weekly') {
        const result=await env.DB.prepare("SELECT v FROM metadata WHERE k='understat_championship_report'").first();
        if(!result || typeof result.v!=='string') return privateJson({status:'not_run'});
        const payload=JSON.parse(result.v);
        return privateJson({report:payload});
      }
      if(url.pathname==='/api/team-form-teams') {
        const league=url.searchParams.get('league');
        if(league && !/^(en|de|es|it|fr)\.1$/.test(league)) return privateJson({error:'Bad league'},400);
        const {results}=await env.DB.prepare('SELECT id FROM private_understat_form'+
          (league?' WHERE id LIKE ?':'')+' ORDER BY id LIMIT 250')
          .bind(...(league?[league+'|%']:[])).all();
        return privateJson({teams:results.map(r=>r.id)});
      }
      if(url.pathname==='/api/team-form') {
        const league=url.searchParams.get('league'), team=url.searchParams.get('team');
        if(!/^(en|de|es|it|fr)\.1$/.test(league||'') ||
           !team || !/^[a-z0-9][a-z0-9 .'-]{1,90}$/.test(team) || team!==team.toLowerCase())
           return privateJson({error:'Invalid team or league'},400);
        const id=league+'|'+team;
        const row=await env.DB.prepare('SELECT payload FROM private_understat_form WHERE id=?').bind(id).first();
        return privateJson({form:row?JSON.parse(row.payload):null});
      }
      if(url.pathname==='/api/unavailable') {
        const {results}=await env.DB.prepare("SELECT fixture_date AS date,league,home,away,reason FROM unavailable WHERE generation=(SELECT v FROM metadata WHERE k='published_generation') ORDER BY fixture_date LIMIT 100").all();
        return json({unavailable:results});
      }
      return json({error:'Unknown API route'},404);
    } catch(e) {
      // Do not leak queries, secrets, or stack traces to callers.
      return json({error:'Database is temporarily unavailable',code:'DATABASE_ERROR'},503);
    }
  }
};
