"""Offline regression for independently published 365Scores xG/shot totals."""
import importlib
import unittest
w=importlib.import_module("research.365_witness_check")

def row():
    return {
      "source_match_id":"123456789",
      "league":"uefa.cl","date":"2026-10-13",
      "home":"Inter Milan","away":"Club Brugge",
      "hg":3,"ag":4,"competition_id":"572","catalog_verified":True,
      "eligible_for_forecast":False,
      "completeness":"NOT_VERIFIED_INDEPENDENT_TOTALS",
      "home_chart_shots":29,"away_chart_shots":15,
      "home_chart_xg_sum":3.79,"away_chart_xg_sum":3.68,
      "home_provisional_xgq":.035,"away_provisional_xgq":.065
    }

class WitnessTest(unittest.TestCase):
 def test_full_verified_requirements(self):
    self.assertTrue(w.validate_witness(row()))
    r=w.compact_verified(row())
    self.assertEqual(r["league"],"uefa.cl")
    self.assertEqual(r["home_shots"],29)
    self.assertEqual(r["away_shots"],15)
    self.assertEqual(r["source_match_id"],"123456789")
    self.assertNotIn("chartEvents",str(r))
 def test_reject_missing_one_shot(self):
    v=row();v["away_chart_shots"]-=1
    with self.assertRaisesRegex(ValueError,"away_shot_count"):
        w.validate_witness(v)
 def test_reject_aggregate_mismatch_even_if_count_matches(self):
    v=row();v["home_chart_xg_sum"]=5.5
    with self.assertRaisesRegex(ValueError,"home_sum_xg"):
        w.validate_witness(v)
 def test_reject_wrong_date_or_competition(self):
    for key,value in [("date","2026-10-12"),("competition_id","98"),
                      ("hg",4),("catalog_verified",False),
                      ("away","Chelsea")]:
        v=row();v[key]=value
        with self.subTest(field=key):
            with self.assertRaises(ValueError):
                w.validate_witness(v)
 def test_reject_provisional_marked_verified_without_independent_match(self):
    v=row();v["eligible_for_forecast"]=True
    with self.assertRaises(ValueError):
        w.validate_witness(v)
if __name__=="__main__":unittest.main()
