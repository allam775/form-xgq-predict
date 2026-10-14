"""Roundtrip the private 365Scores fixture ledger through Wrangler JSON and SQL."""
import json
from pathlib import Path
import tempfile
import unittest

from engine import coverage365_d1


class Coverage365D1Tests(unittest.TestCase):
    def test_restore_original_research_staging_and_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = {"id": "1234567", "competition_id": "572", "league": "uefa.cl",
                       "fixture_date": "2026-10-13",
                       "status": "research_verified_not_released",
                       "payload": json.dumps({"source_match_id": "1234567", "date": "2026-10-13",
                                              "home": "Arsenal", "away": "Lille", "hg": 2, "ag": 1})}
            day = {"id": "572|2026-10-13", "competition_id": "572", "scan_date": "2026-10-13",
                   "scan_status": "complete", "payload": json.dumps({
                       "day": "2026-10-13", "unassigned_games": {"88888": {
                           "observed_date": "2026-10-13", "reason": "missing_competition_id"}}})}
            verified = {"id": "1234567", "payload": json.dumps({
                "source_match_id": "1234567", "league": "uefa.cl",
                "source": "365Scores (opt-in; rights required)", "training_release": False})}
            for key, row in (("matches", fixture), ("days", day), ("verified", verified)):
                (root / f"{key}.json").write_text(json.dumps([{
                    "success": True, "results": [row]
                }]), encoding="utf8")
            out = root / "ledger.json"
            result = coverage365_d1.restore(
                root / "matches.json", root / "days.json", root / "verified.json",
                out, competition_id="572", league="uefa.cl",
                start="2026-07-01", end="2027-06-30")
            self.assertEqual(result["restored_matches"], 1)
            self.assertEqual(result["staged_verified"], 1)
            restored = json.loads(out.read_text(encoding="utf8"))
            self.assertEqual(restored["matches"]["1234567"]["xg_status"],
                             "research_verified_not_released")
            self.assertIn("88888", restored["unassigned_games"])
            sqlpath = root / "upserts.sql"
            counts = coverage365_d1.export_sql(out, sqlpath)
            self.assertEqual(counts["fixtures"], 1)
            self.assertEqual(counts["verified_staged_not_released"], 1)
            sql = sqlpath.read_text(encoding="utf8")
            self.assertIn("private_365_fixture_catalog", sql)
            self.assertIn("private_365_coverage_days", sql)
            self.assertIn("private_365_coverage_verified", sql)
            self.assertNotIn("private_shot_history", sql)
            self.assertIn("training_release", sql)

    def test_fail_on_malformed_d1_response(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text('[{"success":false,"results":[]}]')
            with self.assertRaisesRegex(ValueError, "successful read"):
                coverage365_d1.wrangler_rows(path)


if __name__ == "__main__":
    unittest.main()
