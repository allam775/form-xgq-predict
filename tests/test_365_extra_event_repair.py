"""Offline deterministic repair for an independently identified single extra shot."""
import unittest
from engine.repair365 import repair

def fixture(xs=(.82,.20,.30),outcomes=("Goal","Goal","Saved")):
    mid="4828479"
    ev=[
      {"type":0,"xg":"0.15","competitorNum":1,"outcome":{"name":"Blocked"}},
      {"type":0,"xg":"0.25","competitorNum":1,"outcome":{"name":"Missed"}},
    ]
    ev += [{"type":0,"xg":str(v),"competitorNum":2,
            "outcome":{"name":t}} for v,t in zip(xs,outcomes)]
    data={"game":{"id":mid,"statusText":"Ended","startTimeUTC":"2026-10-13T19:00:00Z",
      "competitionId":572,"competitionDisplayName":"Europe, UEFA Champions League",
      "homeCompetitor":{"id":224,"name":"Inter Milan","score":1},
      "awayCompetitor":{"id":1169,"name":"Club Brugge","score":1},
      "chartEvents":{"events":ev}},
      "competitions":[{"id":572,"name":"UEFA Champions League",
                        "countryId":19,"isInternational":True}]}
    c={"source_match_id":mid,"catalog_verified":True,
       "eligible_for_forecast":False,"completeness":"NOT_VERIFIED_INDEPENDENT_TOTALS",
       "competition_id":"572","league":"uefa.cl","date":"2026-10-13",
       "home":"Inter Milan","away":"Club Brugge","hg":1,"ag":1,
       "home_chart_shots":2,"away_chart_shots":len(xs),
       "home_chart_xg_sum":.4,"away_chart_xg_sum":round(sum(xs),6)}
    w={"home":{"shots":2,"xg":.4,"xg_display_decimals":2},
       "away":{"shots":len(xs)-1,"xg":.5,"xg_display_decimals":2}}
    b={"home":{"differences":{}},
       "away":{"differences":{"on_target":-1,"off_target":0,"blocked":0,"total":-1}}}
    return c,data,w,b

class Tests(unittest.TestCase):
 def test_unambiguous_real_observed_excess_goal_event(self):
    c,d,w,b=fixture()
    r=repair(c,d,w,b)
    self.assertTrue(r["ok"],r)
    x=r["private_row"]
    self.assertEqual(x["away_shots"],2)
    self.assertAlmostEqual(x["away_xg"],.5)
    self.assertAlmostEqual(x["away_xgq"],(.2**2+.3**2)/2)
    self.assertEqual(x["corrected_side"],"away")
    self.assertEqual(x["disallowed_event_outcome"],"goal")
    self.assertFalse(x["training_release"])
    self.assertNotIn("\u0027chartEvents\u0027:",str(x))
    self.assertNotIn("removed_event_xg_private_only",str(x))
 def test_ambiguous_multiple_distinct_exclusions_never_accepted(self):
    c,d,w,b=fixture(xs=(.8,.79,.21))
    w["away"]["xg"]=1.005
    w["away"]["xg_display_decimals"]=3
    r=repair(c,d,w,b)
    self.assertFalse(r["ok"],r)
    self.assertEqual(r["reason"],"multiple_distinct_shots_would_match")
 def test_cannot_discard_saved_event_when_goal_count_is_one_too_many(self):
    c,d,w,b=fixture(xs=(.21,.20,.82),outcomes=("Goal","Goal","Saved"))
    x=repair(c,d,w,b)
    self.assertFalse(x["ok"])
    self.assertEqual(x["reason"],"no_observed_shot_reconciles_to_independent_xg")
 def test_category_not_unique_does_not_guess(self):
    c,d,w,b=fixture()
    b["away"]["differences"]["off_target"]=-1
    self.assertFalse(repair(c,d,w,b)["ok"])
 def test_original_chart_changed_does_not_corrupt_repair(self):
    c,d,w,b=fixture()
    d["game"]["chartEvents"]["events"][2]["xg"]="0.79"
    self.assertEqual(repair(c,d,w,b)["reason"],"chart_xg_changed")
 def test_other_side_xg_requires_independent_match(self):
    c,d,w,b=fixture()
    w["home"]["xg"]=.10
    self.assertEqual(repair(c,d,w,b)["reason"],"other_team_not_reconciled")
 def test_match_scores_and_competition_not_guessed(self):
    c,d,w,b=fixture()
    d["game"]["awayCompetitor"]["score"]=3
    self.assertEqual(repair(c,d,w,b)["reason"],"score_or_team_disagrees")
    c,d,w,b=fixture()
    d["game"]["competitionId"]=98
    self.assertEqual(repair(c,d,w,b)["reason"],"competition_or_date_disagrees")
 def test_no_extra_shots_not_eligible_for_deletion(self):
    c,d,w,b=fixture()
    w["away"]["shots"]=3
    self.assertEqual(repair(c,d,w,b)["reason"],"not_exactly_one_extra_side")
if __name__=="__main__":unittest.main()
