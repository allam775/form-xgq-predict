"""Offline alternative per-shot xG proof with player and official team totals."""
import unittest
from engine.alternate_player_shot_xg365 import repair,repair_two_players

def fixture():
    g={"homeCompetitor":{"id":2,"name":"Home",
         "lineups":{"players":[{"id":201,"competitorId":None,"stats":[
           {"name":"Total Shots","value":"2"},
           {"name":"Expected Goals","value":"0.70"}]}]}},
       "awayCompetitor":{"id":3,"name":"Away",
         "lineups":{"players":[{"id":301,"competitorId":None,"stats":[
           {"name":"Total Shots","value":"1"},
           {"name":"Expected Goals","value":"0.20"}]}]}},
       "chartEvents":{"events":[
           {"competitorNum":1,"playerId":201,"xg":"0.20","outcome":"Missed"},
           {"competitorNum":1,"playerId":201,"xg":"0.30",
            "expected_goals":"0.50","outcome":"Saved"},
           {"competitorNum":2,"playerId":301,"xg":"0.20","outcome":"Missed"}]}}
    c={"source_match_id":"1234","catalog_verified":True,
       "league":"uefa.cl","date":"2026-10-13",
       "home":"Home","away":"Away","hg":1,"ag":0,
       "home_chart_xg_sum":.50,"away_chart_xg_sum":.20}
    stats={"home":{"shots":2,"xg":.70,"xg_display_decimals":2},
           "away":{"shots":1,"xg":.20,"xg_display_decimals":2}}
    prior={"complete":False,"status":"home_xg_mismatch"}
    return c,g,stats,prior
class Tests(unittest.TestCase):
 def test_corroborated_explicit_other_shot_xg(self):
    c,g,s,p=fixture()
    o=repair(c,g,s,p)
    self.assertTrue(o["ok"],o)
    self.assertAlmostEqual(o["private_row"]["home_xgq"],(.2**2+.5**2)/2)
    self.assertEqual(o["private_row"]["alternate_provider_field"],"event.expected_goals")
    self.assertFalse(o["private_row"]["training_release"])
 def test_no_other_observed_field_cannot_derive_unknown_xg(self):
    c,g,s,p=fixture()
    del g["chartEvents"]["events"][1]["expected_goals"]
    o=repair(c,g,s,p)
    self.assertFalse(o["ok"])
    self.assertEqual(o["reason"],"no_alternate_observed_shot_xg_reconciles_player_and_team")
 def test_wrong_official_team_xg_prevents_fix(self):
    c,g,s,p=fixture()
    s["home"]["xg"]=0.95
    self.assertFalse(repair(c,g,s,p)["ok"])
 def test_original_unverified_outcome_prevents_fix(self):
    c,g,s,p=fixture()
    p["status"]="shot_count_mismatch"
    self.assertEqual(repair(c,g,s,p)["reason"],"not_an_original_xg_only_rejection")
 def test_original_snapshot_changes_do_not_get_rewritten(self):
    c,g,s,p=fixture();c["home_chart_xg_sum"]=.7
    self.assertEqual(repair(c,g,s,p)["reason"],"original_chart_xg_changed_since_capture")
def two_players():
    game={"homeCompetitor":{"id":2,"lineups":{"players":[{
        "id":21,"competitorId":None,
        "stats":[{"name":"Total Shots","value":"1"},
                 {"name":"Expected Goals","value":"0.20"}]}]}},
        "awayCompetitor":{"id":3,"lineups":{"players":[{
        "id":31,"competitorId":None,
        "stats":[{"name":"Total Shots","value":"1"},
                 {"name":"Expected Goals","value":"0.40"}]}]}},
        "chartEvents":{"events":[
            {"playerId":21,"competitorNum":1,"xg":"0.10","expected_goals":"0.20"},
            {"playerId":31,"competitorNum":2,"xg":"0.30","expected_goals":"0.40"}]}}
    original={"catalog_verified":True,"league":"uefa.cl","date":"2026-10-13",
              "home":"Home","away":"Away","hg":0,"ag":0,
              "source_match_id":"12345",
              "home_chart_xg_sum":.10,"away_chart_xg_sum":.30}
    stats={"home":{"shots":1,"xg":.20,"xg_display_decimals":2},
           "away":{"shots":1,"xg":.40,"xg_display_decimals":2}}
    audit={"complete":False,"status":"home_xg_mismatch"}
    return original,game,stats,audit

class TwoPlayerTests(unittest.TestCase):
 def test_two_explicit_player_shot_sources_can_resolve_joint_mismatch(self):
    c,g,s,a=two_players()
    v=repair_two_players(c,g,s,a)
    self.assertTrue(v["ok"],v)
    self.assertAlmostEqual(v["private_row"]["home_xgq"],.04)
    self.assertAlmostEqual(v["private_row"]["away_xgq"],.16)
    self.assertFalse(v["private_row"]["training_release"])
 def test_missing_real_alternate_xg_keeps_case_rejected(self):
    c,g,s,a=two_players()
    del g["chartEvents"]["events"][0]["expected_goals"]
    v=repair_two_players(c,g,s,a)
    self.assertFalse(v["ok"])
    self.assertEqual(v["reason"],"one_or_both_players_have_no_valid_observed_alternative_xg")
 def test_shot_count_mismatch_not_masked_as_xg_conflict(self):
    c,g,s,a=two_players()
    s["home"]["shots"]=2
    v=repair_two_players(c,g,s,a)
    self.assertFalse(v["ok"])

if __name__=="__main__":unittest.main()
