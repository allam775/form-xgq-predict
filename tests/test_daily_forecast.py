"""Offline regression tests for the automatic Understat five-league daily ledger."""
from datetime import datetime, timedelta, timezone
import json
import unittest

from engine.daily_forecast import (
    fixtures_from_index, fetch_upcoming, freeze, grade, _forecast, LEAD,
)
from engine.provider_understat import SOURCE
from engine.xgq import strict_row

NOW = datetime(2026, 10, 12, 6, tzinfo=timezone.utc)
KICKOFF = "2026-10-13 13:00:00"
FIXTURE_ID = "it.1|921001"


def source_index():
    return {"dates": [
        {"id": "921001", "isResult": False, "datetime": KICKOFF,
         "h": {"id": "123", "title": "Roma"}, "a": {"id": "456", "title": "Como"}},
        {"id": "921002", "isResult": True, "datetime": "2026-10-13 16:00:00",
         "h": {"id": "123", "title": "Roma"}, "a": {"id": "456", "title": "Como"}},
        {"id": "921003", "isResult": False, "datetime": "2026-10-12 06:10:00",
         "h": {"id": "123", "title": "Roma"}, "a": {"id": "456", "title": "Como"}},
    ]}


def synthetic():
    origin = datetime(2026, 7, 1, tzinfo=timezone.utc)
    rows = []
    for n in range(65):
        day = (origin + timedelta(days=n)).date().isoformat()
        rows.append(strict_row({
            "date": day, "league": "it.1",
            "home_team": "Roma" if n % 2 else "Como",
            "away_team": "Como" if n % 2 else "Roma",
            "home_goals": (n + 1) % 3, "away_goals": n % 3,
            "home_shots_xg": [0.05, 0.12, 0.3],
            "away_shots_xg": [0.07, 0.11, 0.22],
            "source": SOURCE, "source_match_id": str(500000 + n),
        }))
    return rows


class FakeD1:
    def __init__(self, history):
        self.hist = list(history)
        self.forecasts = {}
        self.grades = {}

    def get_setting(self):
        return {
            "enabled": True, "owner_confirmed_collection_and_retention": True,
            "leagues": ["it.1"], "backfill_target": 10000,
            "backfill_seasons": [2026, 2025],
        }

    def history(self):
        return list(self.hist)

    def query(self, sql, params=()):
        if sql.startswith("CREATE TABLE"):
            return []
        if sql.startswith("SELECT id FROM private_daily_forecasts"):
            return [{"id": k} for k in self.forecasts]
        if sql.startswith("SELECT id FROM private_daily_grades"):
            return [{"id": k} for k in self.grades]
        if sql.startswith("SELECT payload FROM private_daily_forecasts"):
            return [{"payload": x} for x in self.forecasts.values()]
        if sql.startswith("SELECT COUNT(*)"):
            return [{"n": len(self.forecasts if "forecasts" in sql else self.grades)}]
        if sql.startswith("INSERT OR IGNORE INTO private_daily_forecasts"):
            self.forecasts.setdefault(params[0], params[1])
            return []
        if sql.startswith("INSERT OR IGNORE INTO private_daily_grades"):
            self.grades.setdefault(params[0], params[1])
            return []
        raise AssertionError(sql)


class DailyForecastTests(unittest.TestCase):
    def test_only_future_fixtures_with_verified_clock_and_teams(self):
        fixtures = fixtures_from_index(source_index(), "it.1", now=NOW)
        self.assertEqual(len(fixtures), 1)
        self.assertEqual(fixtures[0]["id"], FIXTURE_ID)
        self.assertEqual(fixtures[0]["kickoff_utc"], "2026-10-13T13:00:00+00:00")

    def test_authorized_index_and_league_identity(self):
        self.assertEqual(len(fetch_upcoming(["it.1"], now=NOW,
            fetcher=lambda kind, selector: source_index())), 1)
        with self.assertRaises(ValueError):
            fixtures_from_index({"dates": []}, "fake-league", now=NOW)

    def test_predictions_frozen_and_cannot_change_after_source_updates(self):
        db = FakeD1(synthetic())
        fetcher = lambda kind, selector: source_index()
        result = freeze(db, now=NOW, fetcher=fetcher)
        self.assertEqual(result["newly_frozen"], 1)
        frozen = db.forecasts[FIXTURE_ID]
        payload = json.loads(frozen)
        self.assertEqual(payload["model"], "stage1_volume_xgq")
        self.assertEqual(set(payload["models"]["xgq_production_formula"]), {"home", "draw", "away"})
        self.assertAlmostEqual(sum(payload["models"]["xgq_production_formula"].values()), 1, places=6)
        self.assertIn("stage1_volume_xgq",payload["models"])
        self.assertEqual(payload["model_version"], "penniless-stage1-v2-20261017")
        self.assertTrue(payload["original_xgq_preserved_as_comparator"])
        self.assertFalse(payload["production_formula_unchanged"])
        self.assertAlmostEqual(sum(payload["models"]["stage1_volume_xgq"].values()),1,places=6)
        self.assertEqual(payload["model"],"xgq_production_formula")
        self.assertTrue(payload["experimental_models_not_promoted"])
        future = strict_row({
            "date": "2026-10-13", "league": "it.1",
            "home_team": "Roma", "away_team": "Como",
            "home_goals": 2, "away_goals": 1,
            "home_shots_xg": [0.2, 0.4], "away_shots_xg": [0.1, 0.15],
            "source": SOURCE, "source_match_id": "921001",
        })
        db.hist.append(future)
        self.assertEqual(freeze(db, now=NOW, fetcher=fetcher)["already_frozen"], 1)
        self.assertEqual(db.forecasts[FIXTURE_ID], frozen)
        # Never grade less than 115 minutes after kickoff.
        self.assertEqual(grade(db, now=datetime(2026, 10, 13, 13, 30, tzinfo=timezone.utc))["total_graded"], 0)
        r = grade(db, now=datetime(2026, 10, 13, 16, tzinfo=timezone.utc))
        self.assertEqual(r["newly_graded"], 1)
        self.assertEqual(grade(db, now=datetime(2026, 10, 14, tzinfo=timezone.utc))["newly_graded"], 0)

    def test_withhold_unknown_freshness_instead_of_fabricating(self):
        db = FakeD1([])
        result = freeze(db, now=NOW, fetcher=lambda kind, selector: source_index())
        self.assertEqual(result["withheld"], 1)
        self.assertEqual(result["total_frozen"], 0)

    def test_postkickoff_rows_never_created(self):
        late = datetime(2026, 10, 13, 13, tzinfo=timezone.utc)
        self.assertFalse(fixtures_from_index(source_index(), "it.1", now=late))


if __name__ == "__main__":
    unittest.main()
