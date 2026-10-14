"""Offline completeness tests with synthetic 365Scores statistics API objects."""
import unittest
from engine.stats365 import stats_witness,reconcile,verified_research_row

def candidate():
    return {"source_match_id":"4732693","league":"uefa.cl",
        "date":"2026-10-13","home":"Inter Milan","away":"Club Brugge",
        "hg":3,"ag":4,"catalog_verified":True,
        "competition_id":"572","eligible_for_forecast":False,
        "completeness":"NOT_VERIFIED_INDEPENDENT_TOTALS",
        "home_chart_shots":2,"away_chart_shots":2,
        "home_chart_xg_sum":0.40,"away_chart_xg_sum":0.50,
        "home_provisional_xgq":0.045,"away_provisional_xgq":0.080}

def statistics(override=None):
    by={"Total Shots":("2","2"),"Expected Goals":("0.40","0.50"),
        "Shots Blocked":("0","0")}
    if override: by.update(override)
    data=[]
    for name,(a,b) in by.items():
        for cid,value in ((224,a),(1169,b)):
            data.append({"name":name,"competitorId":cid,"categoryName":"Shots","value":value})
    return {"games":[{"id":4732693}],
      "competitors":[{"id":224,"name":"Inter Milan"},
                     {"id":1169,"name":"Club Brugge"}],
      "statistics":data}

class StatsTests(unittest.TestCase):
 def test_complete_independent_shot_and_xg(self):
    c=candidate()
    w=stats_witness(statistics(),c)
    self.assertEqual(w["home"]["shots"],2)
    self.assertEqual(w["away"]["xg"],.5)
    self.assertEqual(w["away"]["xg_display_decimals"],2)
    v=reconcile(c,w)
    self.assertTrue(v["ok"],v)
    record=verified_research_row(c)
    self.assertFalse(record["training_release"])
    self.assertNotIn("chartEvents",str(record))
 def test_missing_blocked_shot_causes_rejection_not_zero_fabrication(self):
    c=candidate()
    w=stats_witness(statistics({"Total Shots":("3","2"),
        "Shots Blocked":("1","0")}),c)
    v=reconcile(c,w)
    self.assertFalse(v["ok"])
    self.assertEqual(v["reason"],"shot_count_mismatch")
    self.assertTrue(v["blocked_shots_explain_gap"])
 def test_totals_disagree_but_chart_count_same(self):
    c=candidate()
    w=stats_witness(statistics({"Expected Goals":("0.91","0.50")}),c)
    self.assertEqual(reconcile(c,w)["reason"],"home_xg_mismatch")
 def test_source_mismatch_cannot_be_silently_used(self):
    c=candidate()
    x=statistics()
    x["competitors"][0]["name"]="AC Milan"
    with self.assertRaisesRegex(ValueError,"names_differ"):
       stats_witness(x,c)
 def test_wrong_returned_game_id_disallowed(self):
    x=statistics()
    x["games"][0]["id"]=99990000
    with self.assertRaisesRegex(ValueError,"wrong_match"):
       stats_witness(x,candidate())
 def test_duplicate_expected_goals_disallowed(self):
    x=statistics()
    x["statistics"].append(dict(x["statistics"][2]))
    with self.assertRaisesRegex(ValueError,"duplicate_expected_goals"):
       stats_witness(x,candidate())
 def test_ambiguous_decimal_and_percent_values_disallowed(self):
    for bad in ("3,79","29%","nan","-1","inf",None,""):
       x=statistics({"Expected Goals":(bad,"0.50")})
       with self.subTest(bad=bad), self.assertRaises(ValueError):
           stats_witness(x,candidate())
 def test_extra_totals_no_missing_shots_ever_assumed(self):
    w=stats_witness(statistics({"Total Shots":("9","13")}),candidate())
    v=reconcile(candidate(),w)
    self.assertFalse(v["ok"])
    self.assertNotIn("xgq",v)
 def test_reject_candidate_with_unverified_competition(self):
    c=candidate();c["catalog_verified"]=False
    with self.assertRaisesRegex(ValueError,"competition_catalog"):
       reconcile(c,stats_witness(statistics(),candidate()))
 def test_xg_rounding_tolerance_is_bounded(self):
    c=candidate()
    x=statistics({"Expected Goals":("0.409","0.500")})
    w=stats_witness(x,c)
    self.assertTrue(reconcile(c,w)["ok"]) # 2 * .005 + .0005
    x=statistics({"Expected Goals":("0.415","0.500")})
    w=stats_witness(x,c)
    self.assertFalse(reconcile(c,w)["ok"])
 def test_stats_shot_total_must_be_integral(self):
    x=statistics({"Total Shots":("2.0","2")})
    with self.assertRaisesRegex(ValueError,"noninteger"):
       stats_witness(x,candidate())
if __name__=="__main__":unittest.main()
