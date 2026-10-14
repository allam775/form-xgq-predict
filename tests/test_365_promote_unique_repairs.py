"""Offline safeguards for private promotion of rigorously corrected shots."""
import importlib
import unittest
p=importlib.import_module("research.365_promote_unique_repairs")

def fixtures():
 c={"source_match_id":"4828479","league":"uefa.cl","date":"2026-10-13",
    "home":"Inter Milan","away":"Club Brugge","hg":3,"ag":4,
    "home_chart_shots":2,"away_chart_shots":3,
    "home_chart_xg_sum":.40,"away_chart_xg_sum":1.32,
    "catalog_verified":True,"eligible_for_forecast":False,
    "completeness":"NOT_VERIFIED_INDEPENDENT_TOTALS"}
 a={"complete":False,"status":"shot_count_mismatch"}
 w={"home":{"shots":2,"xg":.4,"xg_display_decimals":2},
    "away":{"shots":2,"xg":.5,"xg_display_decimals":2}}
 b={"home":{"differences":{"on_target":0,"off_target":0,"blocked":0,"total":0}},
    "away":{"differences":{"on_target":-1,"off_target":0,"blocked":0,"total":-1}}}
 proposal={
    "correction_proof":"one_unique_observed_overcounted_outcome_with_independent_stats",
    "corrected_side":"away","corrected_outcome_class":"on_target",
    "disallowed_event_outcome":"goal",
    "training_release":False,"source_match_id":"4828479",
    "league":"uefa.cl","date":"2026-10-13",
    "home":"Inter Milan","away":"Club Brugge","hg":3,"ag":4,
    "home_shots":2,"away_shots":2,
    "home_xg":.4,"away_xg":.5,"home_xgq":.035,"away_xgq":.065}
 return c,a,w,b,proposal

class Tests(unittest.TestCase):
 def test_exactly_one_reconciled_extra_shot(self):
    self.assertTrue(p.proof(*fixtures()))
 def test_inconsistent_other_side_rejected(self):
    c,a,w,b,s=fixtures()
    s["home_xg"]=.78
    with self.assertRaisesRegex(ValueError,"independent_xg"):
        p.proof(c,a,w,b,s)
 def test_original_audit_must_stay_rejected(self):
    c,a,w,b,s=fixtures()
    a["complete"]=True
    with self.assertRaisesRegex(ValueError,"not_original_extra"):
        p.proof(c,a,w,b,s)
 def test_outcome_class_must_be_shot_category(self):
    c,a,w,b,s=fixtures()
    s["disallowed_event_outcome"]="saved_fake"
    with self.assertRaisesRegex(ValueError,"ambiguous_outcome"):
        p.proof(c,a,w,b,s)
 def test_count_must_have_exact_one_excess_event(self):
    c,a,w,b,s=fixtures()
    c["away_chart_shots"]=4
    with self.assertRaisesRegex(ValueError,"exactly_one_extra"):
        p.proof(c,a,w,b,s)
 def test_never_release_training_early(self):
    c,a,w,b,s=fixtures()
    s["training_release"]=True
    with self.assertRaisesRegex(ValueError,"independently_proved"):
        p.proof(c,a,w,b,s)
if __name__=="__main__":unittest.main()
