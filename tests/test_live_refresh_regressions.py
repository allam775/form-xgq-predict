"""Offline regressions for source outages, private/public overlaps and recent refresh."""
from datetime import date, datetime, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from engine.daily_forecast import fetch_upcoming
from engine.provider_understat import SOURCE, SourceUnavailable, fetch
from engine.understat_pipeline import run
from engine.understat_backfill import backfill
from engine.xgq import strict_row


def fixture(source, mid, hg=1, ag=1):
    return strict_row({
        "league": "en.1", "date": "2026-10-02",
        "home_team": "Example Home", "away_team": "Example Away",
        "home_goals": hg, "away_goals": ag,
        "home_shots_xg": [0.1, 0.2], "away_shots_xg": [0.1, 0.2],
        "source": source, "source_match_id": str(mid)
    })


class DummyResponse:
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def read(self, n):
        return b"<html>Not JSON</html>"


class Tests(unittest.TestCase):
    def test_non_json_http_200_never_becomes_fixture(self):
        with patch("engine.provider_understat.urlopen", return_value=DummyResponse()):
            with self.assertRaises(SourceUnavailable):
                fetch("league", ("en.1", 2026))

    def test_one_bad_league_does_not_hide_good_other_league(self):
        def fetcher(kind, identifier):
            if identifier[0] == "en.1":
                raise SourceUnavailable("non-JSON")
            return {"dates": []}
        errors = []
        rows = fetch_upcoming(
            ["en.1", "de.1"],
            now=datetime(2026, 11, 20, tzinfo=timezone.utc),
            fetcher=fetcher, source_errors=errors
        )
        self.assertEqual(rows, [])
        self.assertEqual(errors, ["en.1"])

    def test_identical_public_and_private_fixture_never_overwrites_public(self):
        public = fixture("StatsBomb Open Data", "999")
        private = fixture(SOURCE, "123")
        self.assertEqual(public["id"], private["id"])
        env = {
            "XGQ_UNDERSTAT_LEAGUES": "en.1",
            "XGQ_UNDERSTAT_ACCESS_AUTHORIZED": "1",
            "XGQ_UNDERSTAT_STORAGE_AUTHORIZED": "1",
            "XGQ_UNDERSTAT_MAX_NEW": "0",
        }
        with TemporaryDirectory() as d:
            p = Path(d) / "private.json"
            p.write_text(json.dumps([private]), encoding="utf-8")
            with patch("engine.understat_pipeline.collect", return_value=([public], {"added": 0})):
                rows, report = run([public], env=env, asof=date(2026, 11, 20), private_path=p)
        self.assertEqual(rows, [public])
        self.assertEqual(report["shared_cross_provider_fixtures"], 1)

    def test_unavailable_source_keeps_verified_cache_and_explicit_stale_flag(self):
        public = fixture("StatsBomb Open Data", "998")
        private = fixture(SOURCE, "123")
        env = {
            "XGQ_UNDERSTAT_LEAGUES": "en.1",
            "XGQ_UNDERSTAT_ACCESS_AUTHORIZED": "1",
            "XGQ_UNDERSTAT_STORAGE_AUTHORIZED": "1",
            "XGQ_UNDERSTAT_MAX_NEW": "0",
        }
        with TemporaryDirectory() as d:
            p = Path(d) / "private.json"
            p.write_text(json.dumps([private]), encoding="utf-8")
            with patch("engine.understat_pipeline.collect",
                       side_effect=SourceUnavailable("upstream non-JSON")):
                rows, report = run(
                    [public], env=env, asof=date(2026, 11, 20), private_path=p
                )
        self.assertEqual(rows, [public])
        self.assertEqual(report["status"], "source_unavailable")
        self.assertFalse(report["source_fresh"])
        self.assertEqual(report["shared_cross_provider_fixtures"], 1)

    def test_conflicting_cross_provider_score_refuses_merge(self):
        public = fixture("StatsBomb Open Data", "999", hg=2)
        private = fixture(SOURCE, "123", hg=1)
        env = {
            "XGQ_UNDERSTAT_LEAGUES": "en.1",
            "XGQ_UNDERSTAT_ACCESS_AUTHORIZED": "1",
            "XGQ_UNDERSTAT_STORAGE_AUTHORIZED": "1",
        }
        with TemporaryDirectory() as d:
            p = Path(d) / "private.json"
            p.write_text(json.dumps([private]), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Conflicting final"):
                run([public], env=env, asof=date(2026, 11, 20), private_path=p)

    def test_recent_finals_continue_after_10k_style_target(self):
        class DB:
            def __init__(self):
                self.rows = {fixture(SOURCE, "100")["id"]: fixture(SOURCE, "100")}
                self.progress = None
            def get_setting(self):
                return {
                    "enabled": True,
                    "owner_confirmed_collection_and_retention": True,
                    "leagues": ["en.1"],
                    "backfill_target": 1,
                    "backfill_seasons": [2026]
                }
            def history(self):
                return list(self.rows.values())
            def upsert_history(self, new):
                for row in new:
                    self.rows[row["id"]] = row
            def upsert_forms(self, profiles):
                pass
            def set_progress(self, report):
                self.progress = report
        db = DB()
        def source(kind, identifier):
            if kind == "league":
                return {"dates": [{
                    "id": "101", "isResult": True,
                    "datetime": "2026-10-03 13:00:00",
                    "h": {"title": "New Home", "id": "10"},
                    "a": {"title": "New Away", "id": "11"},
                    "goals": {"h": 1, "a": 1}
                }]}
            return {"shots": {
                "h": [{"match_id": "101", "h_a": "h", "xG": "0.1", "result": "Goal"}],
                "a": [{"match_id": "101", "h_a": "a", "xG": "0.2", "result": "Goal"}]
            }}
        result = backfill(
            db, recent_only=True, max_new=1, min_interval=0.5,
            fetcher=source, today=date(2026, 10, 11),
            sleeper=lambda n: None, clock=lambda: 10
        )
        self.assertEqual(result["added"], 1)
        self.assertEqual(result["mode"], "recent_only")
        self.assertEqual(len(db.rows), 2)


if __name__ == "__main__":
    unittest.main()
