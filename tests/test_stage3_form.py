"""Phase-3 no-leakage historical regression."""
import unittest
from test_understat_championship import sample_matches
from engine.stage3_form import run_stage3, stage3_probs, _team_form
from engine.understat_championship import _dc_baseline


class Stage3FormTests(unittest.TestCase):
    def test_opponent_adjusted_form_excludes_same_day(self):
        rows=sample_matches(45)
        # All historical games annotated with pre-match rival Elo = 1500.
        hist=[{**r,"prior_opponent_elo_home":1500,
                   "prior_opponent_elo_away":1500} for r in rows]
        target=hist[-1]
        before=_team_form(hist[:-1],target["h"],target["date"],20)
        polluted=_team_form(hist,target["h"],target["date"],20)
        self.assertEqual(before,polluted)

    def test_stage3_probabilities_are_normalized(self):
        rows=sample_matches(160)
        prior=[{**r,"prior_opponent_elo_home":1500,
                   "prior_opponent_elo_away":1500} for r in rows[:-1]]
        game=rows[-1]
        dc=_dc_baseline(prior,game)
        result=stage3_probs(prior,game,dc,(.15,.15))
        self.assertIsNotNone(result)
        self.assertAlmostEqual(sum(result.values()),1,places=7)

    def test_retrospective_research_keeps_production_untouched(self):
        report=run_stage3(sample_matches(150),min_test=10)
        self.assertTrue(report["production_unchanged"])
        self.assertIn(report["status"],("retrospective","insufficient"))
        if report["status"]=="retrospective":
            self.assertEqual(report["scores"]["xgq"]["tested"],
                             report["scores"]["stage3"]["tested"])
            self.assertEqual(report["selected"]["chosen_on"],"validation_only")


if __name__=="__main__":unittest.main()
