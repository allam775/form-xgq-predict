"""Research tests are synthetic and never written to a production feed."""
from datetime import date, timedelta
import unittest

from engine.xgq import predict_xgq, strict_row
from engine.research import CANDIDATES, _replay, _split, benchmark


def synthetic_games(n=260):
    start = date(2025, 1, 1)
    teams = [f"Research Team {i}" for i in range(8)]
    result = []
    for i in range(n):
        home = teams[i % 8]
        away = teams[(i + 1 + (i//8) % 6) % 8]
        if home == away:
            away = teams[(i + 2) % 8]
        r = strict_row({
            "league": "test.1", "date": (start + timedelta(days=i)).isoformat(),
            "home_team": home, "away_team": away,
            "home_goals": i % 4, "away_goals": (i + i//3) % 4,
            "home_shots_xg": [.04, .08, .15, .35],
            "away_shots_xg": [.03, .09, .19],
            "source": "test-fixture-do-not-publish", "source_match_id": str(i + 1)})
        result.append(r)
    return result


class ResearchTests(unittest.TestCase):
    def test_default_parameters_produce_exact_same_output(self):
        history = synthetic_games(130)
        fixture = {"date": "2025-05-30", "league": "test.1",
                   "home_team": "Research Team 0", "away_team": "Research Team 2"}
        a, why1 = predict_xgq(fixture, history, fixture["date"])
        b, why2 = predict_xgq(fixture, history, fixture["date"],
                              lookback=16, half_life=90, prior_strength=1.0)
        self.assertEqual((a, why1), (b, why2))

    def test_future_matches_cannot_change_past_forecast(self):
        history = synthetic_games(160)
        fixture = {"date": "2025-05-01", "league": "test.1",
                   "home_team": "Research Team 0", "away_team": "Research Team 1"}
        pred, reason = predict_xgq(fixture, history, fixture["date"], half_life=60)
        self.assertIsNone(reason)
        poisoned = [dict(x) for x in history]
        for row in poisoned:
            if row["date"] >= fixture["date"]:
                row["home_xgq"] = 0.99
                row["away_xgq"] = 0.01
                row["hg"] = 25
        pred2, reason2 = predict_xgq(fixture, poisoned, fixture["date"], half_life=60)
        self.assertIsNone(reason2)
        self.assertEqual(pred["probabilities"], pred2["probabilities"])

    def test_splits_disjoint_and_date_level(self):
        games = synthetic_games(200)
        parts, meta = _split(games)
        sets = [set(x["id"] for x in v) for v in parts.values()]
        self.assertEqual(len(set.union(*sets)), len(games))
        self.assertEqual(sum(map(len, sets)), len(games))
        self.assertIn("test.1", meta)
        self.assertLess(max(g["date"] for g in parts["train"]),
                        min(g["date"] for g in parts["validation"]))
        self.assertLess(max(g["date"] for g in parts["validation"]),
                        min(g["date"] for g in parts["test"]))

    def test_reports_insufficient_instead_of_fabricating(self):
        result = benchmark(synthetic_games(40), min_validation=10, min_test=10)
        self.assertEqual(result["status"], "insufficient")
        self.assertNotIn("baseline_test", result)

    def test_reports_strict_out_of_sample_comparison(self):
        result = benchmark(synthetic_games(320), min_validation=15, min_test=15)
        self.assertEqual(result["status"], "retrospective", result)
        self.assertGreaterEqual(result["test_eligible"], 15)
        self.assertEqual(result["baseline_test"]["tested"], result["selected_test"]["tested"])
        self.assertIn(result["selected_parameters"]["half_life_days"], (60, 90, 180))
        self.assertTrue(result["production_model_unchanged"])

    def test_rejects_synthetic_and_duplicate_inputs(self):
        h = synthetic_games(80)
        self.assertRaises(ValueError, benchmark, h + h[:1])
        h[0]["source"] = "synthetic simulated"
        self.assertRaises(ValueError, benchmark, h)

    def test_bad_hyperparameters_rejected(self):
        fixture = {"date": "2025-05-01", "league": "test.1",
                   "home_team": "Research Team 0", "away_team": "Research Team 1"}
        h = synthetic_games(120)
        for cfg in ({"lookback": -1}, {"half_life": 0}, {"prior_strength": -1}):
            with self.subTest(cfg=cfg), self.assertRaises(ValueError):
                predict_xgq(fixture, h, fixture["date"], **cfg)


if __name__ == "__main__":
    unittest.main()
