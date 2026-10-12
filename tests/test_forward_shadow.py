"""No hindsight, stable matched samples and conservative forward-model promotion."""
import unittest
from datetime import datetime, timedelta, timezone

from engine.forward_shadow import compare, GATE_PAIRS


def pair(index, league="en.1", base=None, *, strong=False):
    base = base or datetime(2026, 10, 13, tzinfo=timezone.utc)
    kickoff = base + timedelta(days=index)
    fid = f"{league}|{900000 + index}"
    same_day = kickoff.date().isoformat()
    forecast = {
        "id": fid, "date": same_day, "league": league,
        "source_match_id": str(900000 + index),
        "kickoff_utc": kickoff.isoformat(),
        "frozen_at_utc": (kickoff-timedelta(hours=6)).isoformat(),
        "status": "frozen",
        "picks": {"xgq_production_formula": "away",
                  "goal_fixed_rho": "home"},
    }
    grade = {
        "id": fid, "date": same_day,
        "verified_understat_match_id": str(900000 + index),
        "graded_at_utc": (kickoff+timedelta(hours=3)).isoformat(),
        "models": {
            "xgq_production_formula": {
                "pick": "away", "correct": False,
                "log_loss": 1.1 if strong else 0.9,
                "brier": 0.75 if strong else 0.5,
            },
            "goal_fixed_rho": {
                "pick": "home", "correct": True,
                "log_loss": 0.6 if strong else 1.05,
                "brier": 0.3 if strong else 0.8,
            },
        },
    }
    return forecast, grade


class ProspectiveShadowTests(unittest.TestCase):
    def test_empty_does_not_claim_win(self):
        r = compare([], [])
        self.assertEqual(r["paired_verified_matches"], 0)
        self.assertFalse(r["gate_met"])
        self.assertEqual(r["decision"], "KEEP_EXISTING_PRODUCTION_MODEL")
        self.assertIsNone(r["xgq"]["log_loss"])

    def test_non_matching_or_postkickoff_picks_are_refused(self):
        f, g = pair(0)
        f["frozen_at_utc"] = f["kickoff_utc"]
        with self.assertRaises(ValueError):
            compare([f], [g])
        f, g = pair(0)
        g["verified_understat_match_id"] = "123"
        with self.assertRaises(ValueError):
            compare([f], [g])
        f, g = pair(0)
        g["graded_at_utc"] = g["date"]+"T00:00:00+00:00"
        with self.assertRaises(ValueError):
            compare([f], [g])
        f, g = pair(0)
        g["models"]["goal_fixed_rho"]["pick"] = "draw"
        with self.assertRaises(ValueError):
            compare([f], [g])

    def test_challenger_is_not_promoted_from_one_good_day(self):
        f, g = zip(*(pair(i,strong=True) for i in range(24)))
        r = compare(list(f), list(g))
        self.assertEqual(r["paired_verified_matches"], 24)
        self.assertFalse(r["gate_met"])
        self.assertEqual(r["status"], "collecting_prospective_evidence")
        self.assertGreater(r["goal_over_xgq_log_loss_gain"], 0)
        self.assertFalse(r["requires_manual_approval_to_switch"] is False)

    def test_matched_coverage_excludes_missing_challenger(self):
        f, g = pair(0)
        del g["models"]["goal_fixed_rho"]
        r = compare([f], [g])
        self.assertEqual(r["paired_verified_matches"], 0)
        self.assertEqual(r["graded_without_paired_baseline"], 1)

    def test_five_league_prospective_gate_requires_confidence(self):
        codes=("en.1","de.1","es.1","it.1","fr.1")
        pairs=[pair(i,league=codes[i%len(codes)],strong=True) for i in range(GATE_PAIRS)]
        f, g=zip(*pairs)
        r=compare(list(f),list(g))
        self.assertEqual(r["paired_verified_matches"], GATE_PAIRS)
        self.assertEqual(r["paired_log_loss_ci95"]["reliably_better"], True)
        self.assertTrue(r["gate_met"])
        self.assertEqual(r["status"], "eligible_for_manual_review")
        self.assertEqual(r["decision"], "KEEP_EXISTING_PRODUCTION_MODEL")
        self.assertEqual(r["min_forward_pairs"], GATE_PAIRS)
        self.assertEqual(set(r["by_league_paired_counts"]),set(codes))

    def test_duplicates_and_orphan_grades_are_rejected(self):
        f, g = pair(0)
        with self.assertRaises(ValueError):
            compare([f,f], [g])
        with self.assertRaises(ValueError):
            compare([], [g])

    def test_historic_unscored_picks_never_inflate_denominator(self):
        f, g = pair(0)
        f2,_ = pair(1)
        r = compare([f,f2],[g])
        self.assertEqual(r["paired_verified_matches"], 1)
        self.assertEqual(r["all_frozen"],2)
        self.assertEqual(r["all_graded"],1)


if __name__ == "__main__":
    unittest.main()
