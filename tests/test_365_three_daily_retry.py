"""Regression tests for 365Scores three-pass discovery without silent omissions."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from engine import coverage365, coverage365_d1, provider365


class ZeroOmissionRetryTests(unittest.TestCase):
    def run_scan(self, path, *, max_days=2, transport=None):
        env = {"XGQ_365_ACCESS_AUTHORIZED": "1", "XGQ_365_PRIVATE_ONLY": "1"}
        args = ["--competition-id", "572", "--league", "uefa.cl",
                "--start", "2025-10-01", "--end", "2025-10-06",
                "--through", "2025-10-06", "--output", str(path),
                "--max-days", str(max_days), "--max-details", "0"]
        with mock.patch.dict(os.environ, env):
            return coverage365.run(args, transport=transport or (lambda _: {"games": []}))

    def test_unseen_dates_before_old_failures_and_fair_retry_rotation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ledger.json"
            ledger = coverage365.new_ledger("572", "uefa.cl", "2025-10-01", "2025-10-06")
            for n in range(1, 5):
                ledger["failed_days"][f"2025-10-{n:02d}"] = "temporary_failure"
            coverage365._save_atomic(path, ledger)
            queries = []
            from urllib.parse import urlparse, parse_qs
            def transport(url):
                q = parse_qs(urlparse(url).query)
                queries.append(q["startDate"][0])
                return {"games": []}

            first = self.run_scan(path, transport=transport)
            self.assertEqual(queries, ["05/10/2025", "06/10/2025"])
            self.assertEqual(first["days_not_scanned_through"], 4)
            second = self.run_scan(path, transport=transport)
            self.assertEqual(queries[-2:], ["01/10/2025", "02/10/2025"])
            self.assertEqual(second["failed_days"], {"2025-10-03": "temporary_failure",
                                                    "2025-10-04": "temporary_failure"})
            third = self.run_scan(path, transport=transport)
            self.assertEqual(queries[-2:], ["03/10/2025", "04/10/2025"])
            self.assertEqual(third["days_not_scanned_through"], 0)
            self.assertEqual(third["failed_days"], {})
            self.assertEqual(len(json.loads(path.read_text())["scanned_days"]), 6)

    def test_provider_denial_stops_without_retry_or_detail_queries(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ledger.json"
            def transport(_):
                raise provider365.AccessDenied("HTTP 403")
            status = self.run_scan(path, transport=transport)
            self.assertTrue(status["source_access_denied"])
            self.assertEqual(status["attempted_scan_days_this_batch"], 0)
            self.assertIn("2025-10-01", status["failed_days"])
            ledger = json.loads(path.read_text())
            self.assertEqual(ledger["failed_attempts"]["2025-10-01"]["count"], 1)

    def test_d1_retry_metadata_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            day = {"id": "572|2025-10-01", "competition_id": "572",
                   "scan_date": "2025-10-01", "scan_status": "failed",
                   "payload": json.dumps({"day": "2025-10-01", "error": "temporary_failure",
                                         "attempt_count": 4,
                                         "last_attempt_at": "2026-10-14T00:00:00+00:00"})}
            for name, rows in (("matches", []), ("days", [day]), ("verified", [])):
                (root / (name + ".json")).write_text(json.dumps([
                    {"success": True, "results": rows}
                ]))
            dest = root / "ledger.json"
            coverage365_d1.restore(
                root / "matches.json", root / "days.json", root / "verified.json", dest,
                competition_id="572", league="uefa.cl",
                start="2025-10-01", end="2025-10-06"
            )
            ledger = json.loads(dest.read_text())
            self.assertEqual(ledger["failed_attempts"]["2025-10-01"]["count"], 4)
            sql_path = root / "retry.sql"
            coverage365_d1.export_sql(dest, sql_path)
            sql = sql_path.read_text()
            self.assertIn('attempt_count', sql)
            self.assertIn('last_attempt_at', sql)
            self.assertIn("temporary_failure", sql)


if __name__ == "__main__":
    unittest.main()
