"""Scorecard never scores a forecast after kickoff or without official grade."""
import unittest
from engine.recent_two_day_summary import summarize,MODELS

class RecentScorecard(unittest.TestCase):
 def test_valid_and_ungraded(self):
  p={"id":"a","date":"2026-10-19","status":"frozen",
     "frozen_at_utc":"2026-10-18T10:00:00+00:00",
     "kickoff_utc":"2026-10-19T17:00:00+00:00",
     "models":{"elo":{"home":.45,"draw":.25,"away":.30}},
     "picks":{"elo":"home"}}
  g={"id":"a","date":"2026-10-19","outcome":"home",
     "models":{"elo":{"pick":"home","correct":True,"log_loss":.5,"brier":.2}}}
  x=summarize([p],[g],[],[])
  self.assertEqual(x["2026-10-19"]["models"]["elo"]["correct"],1)
  self.assertEqual(x["2026-10-19"]["models"]["elo"]["n"],1)
  self.assertEqual(x["2026-10-19"]["models"]["xgq_production_formula"]["n"],0)
  self.assertEqual(x["2026-10-20"]["graded_officially"],0)
  self.assertEqual(x["2026-10-19"]["models"]["elo"]["accuracy_pct"],100)
 def test_no_forged_grades(self):
  p={"id":"a","date":"2026-10-20","status":"frozen",
     "frozen_at_utc":"2026-10-19T10:00:00+00:00",
     "kickoff_utc":"2026-10-20T20:00:00+00:00",
     "models":{"elo":{"home":.4,"draw":.2,"away":.4}},"picks":{"elo":"home"}}
  s=summarize([p],[],[],[])
  self.assertEqual(s["2026-10-20"]["pending"],1)
  self.assertIsNone(s["2026-10-20"]["models"]["elo"]["accuracy_pct"])
if __name__=="__main__":unittest.main()
