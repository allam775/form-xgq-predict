"""Offline, deterministic tests for the 365Scores no-silent-omissions ledger."""
import json
import os
import tempfile
from pathlib import Path
from unittest import TestCase, mock
from urllib.parse import parse_qs, urlparse

from engine import coverage365


def listing(game_id, home, away, cid="572", status="Ended"):
    return {
        "gameId": game_id, "competitionId": cid,
        "homeCompetitor": {"id": home, "name": "Home"},
        "awayCompetitor": {"id": away, "name": "Away"},
        "statusText": status,
    }


def detailed(game_id, has_xg=True):
    data = listing(game_id, 1, 2)
    data.update({
        "startTimeUTC": "2025-10-21T20:00:00Z",
        "homeCompetitor": {"id": 1, "name": "Home", "score": 2},
        "awayCompetitor": {"id": 2, "name": "Away", "score": 1},
        "chartEvents": {"events": [
            {"xg": "0.3", "competitorNum": 1, "type": 0},
            {"xg": "0.1" if has_xg else None, "competitorNum": 2, "type": 0},
        ]}
    })
    return {"game": data}


class Coverage365Tests(TestCase):
    def ledger(self):
        return coverage365.new_ledger("572", "eu.cl", "2025-10-21", "2025-10-21")

    def test_all_calendar_games_without_120_match_truncation(self):
        ledger = self.ledger()
        matches = [listing(str(i + 10000), i, i + 1) for i in range(220)]
        matches += [listing("7777", 500, 600, cid="17")]
        def transport(url):
            qs = parse_qs(urlparse(url).query)
            self.assertEqual(qs["startDate"], ["21/10/2025"])
            self.assertEqual(qs["onlyMajorGames"], ["false"])
            self.assertEqual(qs["withTop"], ["false"])
            return {"games": matches}
        self.assertEqual(coverage365.scan_day(ledger, "2025-10-21", transport=transport), 220)
        self.assertEqual(len(ledger["matches"]), 220)
        self.assertTrue(coverage365.audit(ledger)["discovery_complete"])

    def test_missing_shot_xg_keeps_fixture_pending(self):
        ledger = self.ledger()
        def transport(url):
            return detailed("123456", False) if urlparse(url).path.endswith("/game/") else {
                "games": [listing("123456", 1, 2)]
            }
        coverage365.scan_day(ledger, "2025-10-21", transport=transport)
        self.assertEqual(coverage365.refresh_details(ledger, transport=transport), 1)
        self.assertEqual(ledger["matches"]["123456"]["xg_status"], "pending_verification")
        self.assertEqual(coverage365.audit(ledger)["matches_discovered"], 1)
        self.assertEqual(coverage365.audit(ledger)["xg_pending"], 1)

    def test_parsed_shots_are_not_falsely_marked_aggregate_verified(self):
        ledger = self.ledger()
        def transport(url):
            return detailed("123456") if urlparse(url).path.endswith("/game/") else {
                "games": [listing("123456", 1, 2)]
            }
        coverage365.scan_day(ledger, "2025-10-21", transport=transport)
        coverage365.refresh_details(ledger, transport=transport)
        self.assertEqual(ledger["matches"]["123456"]["xg_status"], "shot_arrays_parsed")
        self.assertEqual(ledger["matches"]["123456"]["xg_issue"],
                         "aggregate_shots_and_xg_not_yet_cross_checked")
        self.assertEqual(len(ledger["verified_rows"]), 1)

    def test_missing_game_id_kept_for_followup_and_expected_ids_detect_gap(self):
        ledger = self.ledger()
        coverage365.scan_day(ledger, "2025-10-21",
                            transport=lambda _: {"games": [listing(None, 1, 2)]})
        self.assertEqual(len(ledger["matches"]), 1)
        self.assertTrue(next(iter(ledger["matches"])).startswith("unresolved:"))
        status = coverage365.audit(ledger, ["998899"])
        self.assertEqual(status["expected_ids_missing"], ["998899"])
        self.assertFalse(status["discovery_complete"])

    def test_fail_closed_on_pagination_and_no_day_completion(self):
        ledger = self.ledger()
        with self.assertRaisesRegex(ValueError, "paginated"):
            coverage365.scan_day(ledger, "2025-10-21",
                    transport=lambda _: {"games": [listing("123456", 1, 2)],
                                         "hasMore": True})
        self.assertEqual(ledger["scanned_days"], [])

    def test_persist_and_resumption(self):
        ledger = self.ledger()
        coverage365.scan_day(ledger, "2025-10-21", transport=lambda _: {
            "games": [listing("123456", 1, 2)]})
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "private_365_catalog.json"
            coverage365._save_atomic(path, ledger)
            new = coverage365.load_or_create(path, "572", "eu.cl",
                                              "2025-10-21", "2025-10-21")
            self.assertEqual(new["matches"], ledger["matches"])
            self.assertEqual(coverage365.audit(new)["days_not_scanned"], 0)

    def test_requires_rights_and_private_storage(self):
        with mock.patch.dict(os.environ, {
            "XGQ_365_ACCESS_AUTHORIZED": "0",
            "XGQ_365_PRIVATE_ONLY": "1",
        }):
            with self.assertRaises(PermissionError):
                coverage365._require_authorization()
