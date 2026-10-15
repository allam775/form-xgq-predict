"""Offline checks for one original-vs-current shot summary discrepancy."""
import importlib,unittest

m=importlib.import_module("research.365_player_current_version_check")

def fixture():
    g={"homeCompetitor":{"id":2,"name":"Inter Milan"},
       "awayCompetitor":{"id":3,"name":"Club Brugge"},
       "members":[
         {"id":201,"competitorId":2,"stats":[{"name":"Total Shots","value":"2"},
                                           {"name":"Expected Goals","value":"0.40"}]},
         {"id":301,"competitorId":3,"stats":[{"name":"Total Shots","value":"2"},
                                           {"name":"Expected Goals","value":"0.50"}]}],
       "chartEvents":{"events":[
         {"type":0,"playerId":201,"competitorNum":1,"xg":"0.20"},
         {"type":0,"playerId":201,"competitorNum":1,"xg":"0.20"},
         {"type":0,"playerId":301,"competitorNum":2,"xg":"0.30"},
         {"type":0,"playerId":301,"competitorNum":2,"xg":"0.20"}]}}
    c={"home_chart_shots":2,"away_chart_shots":2,
       "home_chart_xg_sum":0.41,"away_chart_xg_sum":0.50}
    stats={"home":{"shots":2,"xg":0.8},
           "away":{"shots":2,"xg":0.5}}
    return c,g,stats
class Tests(unittest.TestCase):
 def test_recompute_real_xgq_from_individual_shots_not_aggregates(self):
    c,g,s=fixture()
    values,changed=m.candidate_sides_recheck(c,g,s)
    self.assertEqual(changed,("home",))
    self.assertAlmostEqual(values["home"]["xg"],.4)
    self.assertAlmostEqual(values["home"]["xgq"],.04)
 def test_no_original_mismatch_cannot_be_mislabeled_as_provider_revision(self):
    c,g,s=fixture();c["home_chart_xg_sum"]=.4
    with self.assertRaisesRegex(ValueError,"no_original_chart"):
        m.candidate_sides_recheck(c,g,s)
 def test_reject_incomplete_per_player_xg(self):
    c,g,s=fixture()
    g["members"][0]["stats"].pop()
    with self.assertRaisesRegex(ValueError,"individual_player"):
        m.candidate_sides_recheck(c,g,s)
 def test_reject_rebased_shots_not_equal_team_total(self):
    c,g,s=fixture()
    c["home_chart_shots"]=3
    with self.assertRaisesRegex(ValueError,"shot_counts_changed"):
        m.candidate_sides_recheck(c,g,s)
if __name__=="__main__":unittest.main()
