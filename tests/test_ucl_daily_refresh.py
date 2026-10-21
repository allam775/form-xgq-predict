"""Regression: no simulated game treated as actual, immutable daily snapshots."""
from datetime import datetime,timezone
import unittest
from research.ucl_daily_refresh import (club_name, completed_day, historical_published_scores,
                                         projection, fetch_365_results)
from research.ucl_forward import fixtures, verified_results

class DailyProjectionTests(unittest.TestCase):
 def test_strict_team_resolution(self):
  self.assertEqual(club_name("Paris Saint-Germain"),"PSG")
  self.assertEqual(club_name("Borussia Dortmund"),"Dortmund")
  self.assertIsNone(club_name("Mystery FC"))
 def test_no_day_until_complete(self):
  schedule=fixtures()
  known=verified_results(schedule)
  self.assertEqual(completed_day(schedule,known,today="2026-10-21"),"2026-10-20")
  self.assertEqual(completed_day(schedule,known,today="2026-10-20"),"2026-10-14")
 def test_original_oct13_projection_stays_read_only(self):
  known=verified_results(fixtures())
  result=historical_published_scores(known,asof="2026-10-20")
  self.assertEqual(result["cumulative"]["n"],27)
  self.assertEqual(result["cumulative"]["correct"],18)
  self.assertEqual(result["cumulative"]["draw_predictions"],0)
  self.assertEqual(result["by_day"]["2026-10-20"]["correct"],6)
 def test_no_unverified_events(self):
  def feeder(kind,values):
   return {"games":[
     {"competitionId":572,"competitionDisplayName":"UEFA Champions League",
      "date":"2026-10-21","status":"not final",
      "homeCompetitor":{"name":"Como","score":2},
      "awayCompetitor":{"name":"Manchester United","score":1}}
   ]}
  found,diag=fetch_365_results("2026-10-21",fixtures(),fetcher=feeder)
  self.assertEqual(found,{})
  self.assertGreaterEqual(diag["not_final"],1)
if __name__=="__main__":unittest.main()
