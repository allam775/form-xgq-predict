"""Regressions for UCL 2026/27 scoreline aggregation and draw omission."""
import unittest
from collections import Counter
from random import Random

from research.ucl_2026_27 import (
    blend,calc,fixtures,joint,onex2,poiss,ranked_scorelines,
    sample_grid,score_table,TEAM_NAMES,TIER_ELO,TEAM_POT
)


class ScorelineIndependenceTests(unittest.TestCase):
    def test_poisson_normalized_not_label_7_plus_as_exact_seven(self):
        probs=poiss(4.0)
        self.assertEqual(len(probs),13)
        self.assertAlmostEqual(sum(probs),1,places=10)
        self.assertLess(probs[7],.08)
        self.assertTrue(all(v>=0 for v in probs))

    def test_the_most_likely_exact_score_can_be_a_draw_while_home_wins_1x2(self):
        # The original bug forcibly discarded all draw scorelines when
        # P(home win) exceeded P(draw), although 1-1 could be the mode.
        grid=joint(1.45,1.15)
        onetwox=onex2(grid)
        top=ranked_scorelines(grid)
        self.assertEqual(max(onetwox,key=onetwox.get),"home")
        self.assertEqual(top[0]["score"],[1,1])
        self.assertAlmostEqual(sum(sum(row) for row in grid),1,places=9)
        self.assertAlmostEqual(sum(onetwox.values()),1,places=9)
        self.assertGreater(top[0]["probability"],top[1]["probability"])

    def test_calc_reports_true_joint_mode_and_5_alternatives(self):
        names=("PSG","Roma")
        rating={t:TIER_ELO[TEAM_POT[t]] for t in TEAM_NAMES}
        for a,b in ((names[0],names[1]),("Roma","PSG"),("Barcelona","Real Madrid"),
                    ("Manchester City","PSG")):
            p=calc({"home":a,"away":b},rating,{})
            self.assertEqual(p["score"],p["top_scorelines"][0]["score"])
            self.assertAlmostEqual(p["score_probability"],
                p["grid"][p["score"][0]][p["score"][1]],places=10)
            self.assertAlmostEqual(sum(p["p"].values()),1,places=10)
            self.assertEqual(len(p["top_scorelines"]),5)

    def test_fixtures_stay_144_actual_first_round_only(self):
        f=fixtures()
        self.assertEqual(len(f),144)
        self.assertEqual(sum(x["actual"] is not None for x in f),18)
        self.assertEqual(sum(x["actual"] is None for x in f),126)

    def test_complete_season_sample_can_contain_draws_and_nonmodal_outcomes(self):
        grid=joint(1.48,1.21)
        rng=Random(20261013)
        samples=[sample_grid(grid,rng) for _ in range(600)]
        self.assertGreater(sum(a==b for a,b in samples),80)
        self.assertGreater(len(set(map(tuple,samples))),7)
        self.assertGreater(max(max(a,b) for a,b in samples),3)


if __name__=="__main__":
    unittest.main()
