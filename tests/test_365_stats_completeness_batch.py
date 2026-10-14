"""No-network tests for bounded private completeness verification batch."""
import importlib
import json
import unittest

mod=importlib.import_module("research.365_stats_completeness_batch")

def candidate(mid="4732693"):
    return {"source_match_id":mid,"league":"uefa.cl",
        "date":"2026-10-13","home":"Inter Milan","away":"Club Brugge",
        "hg":3,"ag":4,"catalog_verified":True,
        "eligible_for_forecast":False,
        "completeness":"NOT_VERIFIED_INDEPENDENT_TOTALS",
        "home_chart_shots":2,"away_chart_shots":2,
        "home_chart_xg_sum":0.40,"away_chart_xg_sum":0.50,
        "home_provisional_xgq":.045,"away_provisional_xgq":.080}

def stats(mid="4732693",full=True):
    d={"Total Shots":("2","2") if full else ("3","2"),
       "Shots Blocked":("0","0") if full else ("1","0"),
       "Expected Goals":("0.40","0.50")}
    return {"games":[{"id":int(mid)}],
        "competitors":[{"id":224,"name":"Inter Milan"},
                       {"id":1169,"name":"Club Brugge"}],
        "statistics":[{"name":name,"competitorId":cid,"categoryName":"Shots",
                       "value":pair[i]}
            for name,pair in d.items()
            for i,cid in enumerate((224,1169))]}

class DB:
    def __init__(self,rows=None):
        self.candidates={v["source_match_id"]:v for v in (rows or [])}
        self.audits={}
        self.verified={}
    def query(self,sql,params=()):
        if sql.startswith("CREATE TABLE"):
            return []
        if "SELECT payload FROM private_365_research_candidates" in sql:
            return [{"payload":json.dumps(v)} for v in self.candidates.values()]
        if "SELECT id,payload FROM private_365_stats_audit" in sql:
            return [{"id":k,"payload":json.dumps(v)} for k,v in self.audits.items()]
        if "INSERT OR REPLACE INTO private_365_stats_audit" in sql:
            self.audits[params[0]]=json.loads(params[1]);return []
        if "INSERT OR REPLACE INTO private_365_research_verified" in sql:
            self.verified[params[0]]=json.loads(params[1]);return []
        raise AssertionError(sql)

class BatchTests(unittest.TestCase):
    def test_accepts_and_stores_complete_match_privately(self):
        db=DB([candidate()])
        requests=[]
        r=mod.batch(db=db,get_stats=lambda mid:requests.append(mid) or stats(mid),
                    max_requests=1,delay=0)
        self.assertEqual(requests,["4732693"])
        self.assertEqual(r["new_verified_complete_xgq"],1)
        self.assertEqual(len(db.verified),1)
        self.assertEqual(db.verified[next(iter(db.verified))]["training_release"],False)
        self.assertEqual(r["raw_events_written"],0)
        self.assertNotIn("source_match_id",str(r))
    def test_missing_blocked_shots_does_not_become_xgq(self):
        db=DB([candidate()])
        r=mod.batch(db=db,get_stats=lambda mid:stats(mid,full=False),max_requests=1,delay=0)
        self.assertEqual(r["new_verified_complete_xgq"],0)
        self.assertEqual(r["new_incomplete"],1)
        self.assertEqual(r["total_count_shortfall_home"],1)
        self.assertEqual(r["cases_with_blocked_shots_explaining_both_gaps"],1)
        self.assertEqual(len(db.verified),0)
    def test_duplicate_audit_skips_repeated_downloads(self):
        db=DB([candidate()])
        mod.batch(db=db,get_stats=lambda mid:stats(mid,full=False),max_requests=1,delay=0)
        r=mod.batch(db=db,get_stats=lambda mid:(_ for _ in ()).throw(AssertionError("network used")),
                    max_requests=1,delay=0)
        self.assertEqual(r["stats_requests"],0)
        self.assertEqual(r["already_audited"],1)
    def test_unknown_competition_fail_closed(self):
        bad=candidate()
        bad["catalog_verified"]=False
        db=DB([bad])
        with self.assertRaisesRegex(ValueError,"unverified"):
            mod.batch(db=db,get_stats=lambda _:stats(),max_requests=1,delay=0)
    def test_hard_limit_and_no_id_enumeration(self):
        db=DB([candidate(mid=str(4732693+i)) for i in range(5)])
        hits=[]
        r=mod.batch(db=db,get_stats=lambda mid:hits.append(mid) or stats(mid),
                    max_requests=2,delay=0)
        self.assertEqual(len(hits),2)
        self.assertEqual(r["stats_requests"],2)
        self.assertEqual(r["status"],"request_budget_reached")
        with self.assertRaises(ValueError):
            mod.batch(db=db,get_stats=lambda _:stats(),max_requests=19,delay=0)
    def test_stats_schema_error_is_not_silently_approved(self):
        db=DB([candidate()])
        def invalid(mid):
            z=stats(mid)
            z["statistics"]=[]
            return z
        r=mod.batch(db=db,get_stats=invalid,max_requests=1,delay=0)
        self.assertEqual(r["new_verified_complete_xgq"],0)
        self.assertEqual(len(db.audits),0)
        self.assertGreaterEqual(len(r["errors"]),1)

if __name__=="__main__":unittest.main()
