// Standalone Cloudflare Worker + D1 API. No tokens/API keys exposed to the browser.
const json = (data, status=200) => new Response(JSON.stringify(data), {
  status, headers: {'content-type':'application/json; charset=utf-8',
   'cache-control':'public, max-age=60', 'x-content-type-options':'nosniff',
   'access-control-allow-origin':'*'}
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
