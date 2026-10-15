"""Offline checks for alternate PLAYER-INDEPENDENT witness with team xG conflict."""
import importlib,copy,unittest
a=importlib.import_module("research.365_player_independent_release")

def candidate():
    return {"source_match_id":"12345","league":"uefa.cl","date":"2026-10-13",
      "home":"Home","away":"Away","hg":2,"ag":0,
      "catalog_verified":True,"eligible_for_forecast":False,
      "completeness":"NOT_VERIFIED_INDEPENDENT_TOTALS",
      "home_chart_shots":2,"away_chart_shots":1,
      "home_chart_xg_sum":0.4,"away_chart_xg_sum":0.2,
      "home_provisional_xgq":0.04,"away_provisional_xgq":0.04}
def player():
    def data(n,xg):
        return {"chart_shots_total":n,"stat_shots_total":n,"independent_team_shots":n,
          "players_all_shots_match":True,"players_all_xg_match":True,
          "player_count_mismatch":0,"player_xg_mismatch":0,"player_xg_missing":0,
          "members":{"player1":{"chart_count":n,"stats_count":n,
           "chart_sum_xg":xg,"stats_sum_xg":xg,
           "stats_xg_precision":2}}}
    return {"player_evidence_complete":True,
            "aggregate":{"unmapped_shots":0,"players_missing_xg":0},
            "by_side":{"home":data(2,.4),"away":data(1,.2)}}
def official():
    return {"home":{"shots":2,"xg":.8,"xg_display_decimals":2},
            "away":{"shots":1,"xg":.2,"xg_display_decimals":2}}

class Tests(unittest.TestCase):
 def test_alternative_independent_player_witness(self):
    self.assertTrue(a.proof(candidate(),{"complete":False,"status":"home_xg_mismatch"},official(),player()))
 def test_reject_when_player_xg_does_not_match_chart(self):
    p=player();p["by_side"]["home"]["members"]["player1"]["stats_sum_xg"]=.8
    with self.assertRaisesRegex(ValueError,"player_xg_total_mismatch"):
        a.proof(candidate(),{"complete":False,"status":"home_xg_mismatch"},official(),p)
 def test_reject_when_player_shots_do_not_match(self):
    p=player();p["by_side"]["home"]["members"]["player1"]["chart_count"]=1
    with self.assertRaises(ValueError):
        a.proof(candidate(),{"complete":False,"status":"home_xg_mismatch"},official(),p)
 def test_cannot_convert_shot_count_mismatch_to_player_witness(self):
    with self.assertRaisesRegex(ValueError,"not_original_same_shot_count_xg_conflict"):
        a.proof(candidate(),{"complete":False,"status":"shot_count_mismatch"},official(),player())
 def test_bad_team_competition_source_rejected(self):
    c=candidate();c["catalog_verified"]=False
    with self.assertRaisesRegex(ValueError,"invalid_original"):
        a.proof(c,{"complete":False,"status":"home_xg_mismatch"},official(),player())
 def test_unknown_player_xg_no_fabricated_probability(self):
    p=player();p["by_side"]["home"]["members"]["player1"]["stats_sum_xg"]=None
    with self.assertRaises(ValueError):
        a.proof(candidate(),{"complete":False,"status":"home_xg_mismatch"},official(),p)
if __name__=="__main__":unittest.main()
