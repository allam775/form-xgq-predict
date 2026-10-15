"""Offline proof that independent player xG resolves formerly ambiguous deletions."""
import unittest
from engine.player_guided_repair365 import repair

def person(pid,shots,xg):
    return {"id":pid,"competitorId":None,
            "stats":[{"name":"Total Shots","value":str(shots)},
                     {"name":"Expected Goals","value":str(xg)}]}
def fixture(player_xg="0.450"):
    d={"game":{"id":4732693,"statusText":"Ended",
        "startTimeUTC":"2026-10-13T19:00:00Z",
        "competitionId":572,"competitionDisplayName":"UEFA Champions League",
        "homeCompetitor":{"id":21,"name":"Home","score":0,
                          "lineups":{"players":[person(201,2,player_xg)]}},
        "awayCompetitor":{"id":22,"name":"Away","score":0,
                          "lineups":{"players":[person(301,1,"0.20")]}},
        "chartEvents":{"events":[
            {"type":0,"competitorNum":1,"playerId":201,"xg":"0.10","outcome":"Missed"},
            {"type":0,"competitorNum":1,"playerId":201,"xg":"0.12","outcome":"Missed"},
            {"type":0,"competitorNum":1,"playerId":201,"xg":"0.33","outcome":"Missed"},
            {"type":0,"competitorNum":2,"playerId":301,"xg":"0.20","outcome":"Missed"}]}},
        "competitions":[{"id":572,"name":"UEFA Champions League",
                         "countryId":7,"isInternational":True}]}
    c={"catalog_verified":True,"eligible_for_forecast":False,
       "completeness":"NOT_VERIFIED_INDEPENDENT_TOTALS",
       "source_match_id":"4732693","league":"uefa.cl",
       "competition_id":"572","date":"2026-10-13",
       "home":"Home","away":"Away","hg":0,"ag":0,
       "home_chart_shots":3,"away_chart_shots":1,
       "home_chart_xg_sum":.55,"away_chart_xg_sum":.20}
    w={"home":{"shots":2,"xg":.44,"xg_display_decimals":2},
       "away":{"shots":1,"xg":.20,"xg_display_decimals":2}}
    diffs={"on_target":0,"off_target":-1,"blocked":0,"total":-1}
    blank={"on_target":0,"off_target":0,"blocked":0,"total":0}
    cat={"home":{"differences":diffs},"away":{"differences":blank}}
    return c,d,w,cat
class Tests(unittest.TestCase):
 def test_player_xg_isolates_one_of_two_originally_possible_shots(self):
    c,d,w,b=fixture()
    out=repair(c,d,w,b)
    self.assertTrue(out["ok"],out)
    self.assertEqual(out["private_row"]["home_shots"],2)
    self.assertAlmostEqual(out["private_row"]["home_xg"],.45)
    self.assertEqual(out["private_row"]["proof_tier"],"PLAYER_AND_TEAM_INDEPENDENT_UNIQUE_EXCLUSION")
    self.assertFalse(out["private_row"]["training_release"])
 def test_two_distinct_values_are_still_ambiguous_if_player_xg_not_decisive(self):
    c,d,w,b=fixture("0.440")
    out=repair(c,d,w,b)
    self.assertFalse(out["ok"])
    self.assertEqual(out["reason"],"distinct_shot_xg_removals_remain_ambiguous")
 def test_wrong_player_event_id_rejected(self):
    c,d,w,b=fixture()
    d["game"]["chartEvents"]["events"][0]["playerId"]=999999
    out=repair(c,d,w,b)
    self.assertFalse(out["ok"])
 def test_wrong_original_source_prevent_promotion(self):
    c,d,w,b=fixture()
    c["catalog_verified"]=False
    out=repair(c,d,w,b)
    self.assertFalse(out["ok"])
 def test_player_total_shots_must_agree_with_independent_teams(self):
    c,d,w,b=fixture()
    d["game"]["homeCompetitor"]["lineups"]["players"][0]["stats"][0]["value"]="1"
    out=repair(c,d,w,b)
    self.assertFalse(out["ok"])
if __name__=="__main__":unittest.main()
