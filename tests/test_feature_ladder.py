"""Phase 1 research regression; use only synthetic fixtures, no Understat access."""
import unittest
from datetime import date, timedelta
from test_understat_championship import sample_matches
from engine.feature_ladder import stage1_probs, _shot_volume, STAGE1_CANDIDATES, run_stage1
from engine.understat_championship import _dc_baseline


class FeatureLadderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows=sample_matches(260)

    def test_nonleaking_stage1_model(self):
        prior=self.rows[:160]
        game=self.rows[161]
        dc=_dc_baseline(prior,game)
        self.assertIsNotNone(dc)
        self.assertIsNotNone(_shot_volume(prior,game))
        for params in STAGE1_CANDIDATES:
            p=stage1_probs(prior,game,dc,params)
            self.assertAlmostEqual(sum(p.values()),1,places=8)
            self.assertTrue(all(0<=v<=1 for v in p.values()))

    def test_nonchronological_prior_rejected(self):
        target=self.rows[120]
        with self.assertRaises(ValueError):
            _shot_volume(self.rows[:121],target)

    def test_real_test_labels_cannot_change_prior_validation_selection(self):
        rows=self.rows
        first=run_stage1(rows,min_test=10)
        self.assertEqual(first['status'],'retrospective',first)
        day=first['cohorts']['en.1']['test_start']
        changed=[{**r,'hg':(r['hg']+1)%5,'ag':(r['ag']+2)%4} if r['date']>=day else r
                 for r in rows]
        second=run_stage1(changed,min_test=10)
        self.assertEqual(first['selected'],second['selected'])
        self.assertEqual(first['validation_selected'],second['validation_selected'])

    def test_duplicate_id_not_tolerated(self):
        with self.assertRaises(ValueError):
            run_stage1(self.rows+[self.rows[0]])


if __name__=='__main__':
    unittest.main()
