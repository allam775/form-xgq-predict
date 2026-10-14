"""Synthetic offline tests for privacy-preserving 365Scores rejection diagnosis."""
import importlib
import json
import unittest

diag=importlib.import_module("research.365_rejected_diagnosis")

def game():
    return {"homeCompetitor":{"id":11},"awayCompetitor":{"id":22},
            "chartEvents":{"events":[
                {"type":0,"xg":"0.16","outcome":{"name":"On target"},"competitorNum":1},
                {"type":0,"xg":"0.12","outcome":{"name":"Off target"},"competitorNum":2},
                {"type":0,"xg":"0.18","outcome":{"name":"Off target"},"competitorNum":2},
            ]}}
class Tests(unittest.TestCase):
    def test_grouped_not_individual_shot_values(self):
        g=diag._shot_group(game())
        self.assertEqual(g["recognized_shots"],{"home":1,"away":2})
        self.assertEqual(g["groups"]["away"][0]["count"],2)
        self.assertAlmostEqual(g["groups"]["away"][0]["sum_xg"],0.3)
        self.assertNotIn("0.12",json.dumps(g))
        self.assertNotIn("0.18",json.dumps(g))
        self.assertIn("outcome",g["event_metadata_keys"])
    def test_reject_invalid_team_metadata(self):
        g=game()
        del g["chartEvents"]["events"][0]["competitorNum"]
        with self.assertRaises(ValueError):
            diag._shot_group(g)
    def test_does_not_synthesize_missing_shots(self):
        g=game()
        self.assertEqual(len(g["chartEvents"]["events"]),3)
        x=diag._shot_group(g)
        self.assertEqual(sum(x["recognized_shots"].values()),3)
        self.assertNotIn("expectedGoals",str(x))
if __name__=="__main__":unittest.main()
