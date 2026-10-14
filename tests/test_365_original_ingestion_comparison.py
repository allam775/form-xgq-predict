"""Offline regressions for comparison against original XGQ website source."""
import importlib,unittest

m=importlib.import_module("research.365_original_ingestion_comparison")

def g():
    return {"game":{
        "id":4732693,"statusText":"Ended",
        "startTimeUTC":"2026-10-13T19:00:00Z",
        "competitionId":572,"competitionDisplayName":"Europe, UEFA Champions League",
        "homeCompetitor":{"id":224,"name":"Inter Milan","score":3},
        "awayCompetitor":{"id":1169,"name":"Club Brugge","score":4},
        "chartEvents":{"events":[
            {"xg":"0.22","competitorNum":1,"outcome":{"name":"Missed"}},
            {"xg":"0.18","competitorNum":1,"outcome":{"name":"Saved"}},
            {"xg":"0.30","competitorNum":2,"outcome":{"name":"Missed"}},
            {"xg":"0.20","competitorNum":2,"outcome":{"name":"Goal"}},
        ]}},
        "competitions":[{"id":572,"name":"UEFA Champions League",
                         "isInternational":True,"countryId":19}]}

def candidate():
    return {"source_match_id":"4732693","league":"uefa.cl",
            "competition_id":"572","date":"2026-10-13",
            "home":"Inter Milan","away":"Club Brugge",
            "hg":3,"ag":4}
def witness():
    return {"home":{"shots":2,"xg":.40,"xg_display_decimals":2},
            "away":{"shots":2,"xg":.50,"xg_display_decimals":2}}

class Tests(unittest.TestCase):
    def test_original_xg_precedence_before_nested_shot_field(self):
        e={"xG":"0.2","shot":{"xg":"0.8"}}
        self.assertEqual(m.legacy_xg(e),.2)
    def test_original_expected_goals_underscore_supported_diagnostic_only(self):
        self.assertEqual(m.legacy_xg({"expected_goals":"0.17"}),.17)
    def test_no_invalid_xg_or_fabricated_missing_chances(self):
        for val in ("NaN","not available",1.5,-0.1):
            with self.subTest(v=val):
                self.assertIsNone(m.legacy_xg({"xg":val}))
    def test_two_sides_reconcile_exactly(self):
        a=m.compare_detail(g(),candidate(),witness())
        self.assertTrue(a["ok"],a)
        self.assertEqual(a["sides"]["home"]["shots"],2)
    def test_mismatched_total_never_accepted(self):
        x=witness();x["home"]["xg"]=.81
        self.assertFalse(m.compare_detail(g(),candidate(),x)["ok"])
    def test_mismatched_count_never_accepted(self):
        x=witness();x["home"]["shots"]=3
        self.assertFalse(m.compare_detail(g(),candidate(),x)["ok"])
    def test_bad_competition_fails_closed(self):
        x=g();x["game"]["competitionId"]=999
        with self.assertRaises(ValueError):
            m.compare_detail(x,candidate(),witness())
    def test_bad_score_fails_closed(self):
        x=g();x["game"]["homeCompetitor"]["score"]=2
        with self.assertRaises(ValueError):
            m.compare_detail(x,candidate(),witness())
    def test_matchup_id_does_not_change_identity(self):
        a=m.compare_detail(g(),candidate(),witness())
        self.assertTrue(a["ok"])
        x=g();x["game"]["id"]=4732600
        with self.assertRaisesRegex(ValueError,"requested_finished_game"):
            m.compare_detail(x,candidate(),witness())
    def test_true_completeness_does_not_publish_xgq(self):
        a=m.compare_detail(g(),candidate(),witness())
        self.assertNotIn("xgq",str(a))
        self.assertNotIn("raw",str(a))
if __name__=="__main__":unittest.main()
