"""Phase 2 evaluation refuses imaginary historical xA and key-pass evidence."""
import unittest
from test_understat_championship import sample_matches
from engine.stage2_research import run_stage2,creativity_probs
from engine.understat_championship import _dc_baseline


class Stage2ResearchTests(unittest.TestCase):
    def test_missing_real_creativity_cannot_make_historical_skill_claim(self):
        report=run_stage2(sample_matches(150),[],min_test=10)
        self.assertEqual(report["status"],"insufficient_coverage")
        self.assertEqual(report["creativity_enriched_matches"],0)
        self.assertEqual(report["test_paired"],0)
        self.assertNotIn("scores",report)
        self.assertTrue(report["actual_match_roster_xa_key_passes"])

    def test_cannot_make_up_xa_when_prior_missing(self):
        prior=sample_matches(70)
        game=prior[-1]
        dc=_dc_baseline(prior[:-1],game)
        self.assertIsNone(creativity_probs(prior[:-1],game,dc,(.1,.1,.05)))


if __name__=="__main__":
    unittest.main()
