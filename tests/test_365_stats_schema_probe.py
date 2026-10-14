"""Zero-network privacy regressions for 365Scores documented statistics schema."""
import importlib
import unittest

probe=importlib.import_module("research.365_stats_schema_probe")

class Tests(unittest.TestCase):
 def test_statistic_names_not_values(self):
  resp={"statistics":[{"name":"Total Shots","categoryName":"Attack",
                       "competitorId":224,"value":29},
                      {"name":"Expected Goals","categoryName":"Attack",
                       "competitorId":1169,"value":"3.79"}],
        "competitors":[{"id":224,"name":"Inter Milan"}],
        "actualGameStatistics":{"fullTime":[]},
        "secret_token":"should-not-be-read"}
  out=probe.inspect_statistics(resp)
  self.assertEqual(out["statistics_names"],["Expected Goals","Total Shots"])
  self.assertIn("competitorId",out["statistics_row_keys"])
  self.assertNotIn("29",str(out))
  self.assertNotIn("3.79",str(out))
  self.assertNotIn("Inter Milan",str(out))
  self.assertNotIn("should-not-be-read",str(out))
 def test_invalid_payload(self):
  self.assertFalse(probe.inspect_statistics([])["valid_json"])
 def test_private_select_only_exact_match(self):
  class Fake:
   def query(self,query):
    self_outer=self
    return [{"payload":__import__("json").dumps(v)} for v in (
      {"league":"uefa.cl","date":"2026-10-13","home":"Wrong Team",
       "away":"Club Brugge","catalog_verified":True,"source_match_id":"12345"},
      {"league":"uefa.cl","date":"2026-10-13","home":"Inter Milan",
       "away":"Club Brugge","catalog_verified":True,"source_match_id":"4732693"})]
  out=probe._private_known_match(Fake())
  self.assertEqual(out["source_match_id"],"4732693")
 def test_no_eligible_without_official_totals(self):
  # Explicitly no code path or field labeling a match as complete XGQ.
  import inspect
  code=inspect.getsource(probe)
  self.assertNotIn("eligible_for_forecast",code)
  self.assertNotIn("private_365_research_verified",code)
if __name__=="__main__":unittest.main()
