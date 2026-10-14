"""Safe synthetic tests for explicitly bounded, private 365Scores collector."""
import importlib
import json
import unittest
from urllib.parse import urlparse,parse_qs

b=importlib.import_module("research.365_private_batch")

def game(mid="4732693",comp=17,name="Serie A",country=120,international=False):
    return {"game":{
      "id":int(mid),"statusText":"Ended",
      "startTimeUTC":"2026-10-09T20:00:00Z",
      "competitionId":comp,"competitionDisplayName":name,
      "homeCompetitor":{"id":111,"name":"AS Roma","score":1.0},
      "awayCompetitor":{"id":224,"name":"Inter Milan","score":2.0},
      "chartEvents":{"events":[
          {"type":0,"xg":"0.17","competitorNum":1},
          {"type":0,"xg":"0.21","competitorNum":1},
          {"type":0,"xg":"0.02","competitorNum":2},
          {"type":0,"xg":"0.51","competitorNum":2}]}
    },"competitions":[{"id":comp,"name":name,
                       "isInternational":international,"countryId":country}]}

class FakeD1:
    def __init__(self):
        self.records={}
        self.operations=[]
    def query(self,sql,params=()):
        self.operations.append((sql,params))
        if sql.startswith("CREATE TABLE"):return []
        if sql.startswith("INSERT OR REPLACE"):
            mid,payload=params
            self.records[mid]=json.loads(payload)
            return []
        if sql.startswith("SELECT COUNT"):return [{"n":len(self.records)}]
        raise AssertionError(sql)

class BatchTests(unittest.TestCase):
    def test_real_observed_events_remain_provisional(self):
        r=b.provisional_match(game(),"4732693","224")
        self.assertEqual(r["league"],"it.1")
        self.assertEqual(r["hg"],1)
        self.assertEqual(r["ag"],2)
        self.assertEqual(r["home_chart_shots"],2)
        self.assertEqual(r["away_chart_shots"],2)
        self.assertAlmostEqual(r["home_provisional_xgq"],(.17**2+.21**2)/2)
        self.assertEqual(r["completeness"],"NOT_VERIFIED_INDEPENDENT_TOTALS")
        self.assertFalse(r["eligible_for_forecast"])
        self.assertNotIn("chartEvents",json.dumps(r))
    def test_private_idempotent_no_events_stored(self):
        db=FakeD1()
        row=b.provisional_match(game(),"4732693","224")
        self.assertEqual(b.persist_private([row],db),1)
        self.assertEqual(b.persist_private([row],db),1)
        self.assertNotIn("chartEvents",str(db.records))
        self.assertEqual(len(db.records),1)
    def test_accept_UEFA_competition_572_with_catalog(self):
        payload=game(comp=572,name="UEFA Champions League",international=True)
        r=b.provisional_match(payload,"4732693","224")
        self.assertEqual(r["league"],"uefa.cl")
        self.assertTrue(r["catalog_verified"])
    def test_reject_wrong_competition_even_with_shots(self):
        with self.assertRaisesRegex(ValueError,"competition_"):
            b.provisional_match(game(comp=579,name="Europa League"),"4732693","224")
    def test_reject_bad_float_score(self):
        payload=game()
        payload["game"]["homeCompetitor"]["score"]=1.5
        with self.assertRaisesRegex(ValueError,"final score"):
            b.provisional_match(payload,"4732693","224")
    def test_reject_incomplete_individual_shot(self):
        payload=game()
        payload["game"]["chartEvents"]["events"][0]["xg"]="NaN"
        with self.assertRaisesRegex(ValueError,"shot_without_individual_xg"):
            b.provisional_match(payload,"4732693","224")
    def test_bounded_two_endpoints_reject_unlisted_clubs(self):
        db=FakeD1(); calls=[]
        def transport(url):
            u=urlparse(url);q=parse_qs(u.query);calls.append((u.path,q))
            if u.path.endswith("games/results/"):
                return {"games":[
                 {"gameId":"4732693","homeCompetitor":{"id":111},
                  "awayCompetitor":{"id":224}},
                 {"gameId":"4732694","homeCompetitor":{"id":880},
                  "awayCompetitor":{"id":999}}]}
            return game(q["gameId"][0])
        report=b.collect(transport=transport,db=db,team_ids=("224",),per_team=2,delay=0)
        self.assertEqual(report["requests"],2)
        self.assertEqual(report["provisional_candidates"],1)
        self.assertEqual(report["private_candidates_saved"],1)
        self.assertEqual(report["accepted_complete_xgq"],0)
        self.assertEqual(len(calls),2)
        self.assertNotIn("home",json.dumps(report))
        self.assertEqual(len(db.records),1)
    def test_no_team_id_guessing_or_excessive_requests(self):
        for ids,cap in ((("999",),1),(("224","1169","890","999"),1),
                        (("224",),15)):
            with self.assertRaises(ValueError):
                b.collect(transport=lambda _: {},db=FakeD1(),team_ids=ids,per_team=cap)
    def test_score_float_only_integral(self):
        from engine.provider365 import _score_number
        self.assertEqual(_score_number(2.0),2)
        self.assertIsNone(_score_number(2.5))
        self.assertIsNone(_score_number(float('nan')))
        self.assertIsNone(_score_number(True))

if __name__=="__main__":unittest.main()
