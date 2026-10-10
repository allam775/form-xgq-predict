"""Tests for a bounded public shot-history collection target."""
import unittest
from unittest.mock import patch
from engine.collect import planned_open_shot_import_quota, shot_archive


class ArchiveTargetTests(unittest.TestCase):
    def test_import_only_missing_public_rows(self):
        rows = [{'id': 's1', 'source': 'StatsBomb Open Data'},
                {'id': 's2', 'source': 'StatsBomb Open Data'},
                {'id': 'private', 'source': '365Scores (opt-in; rights required)'},
                {'id': 's1', 'source': 'StatsBomb Open Data'}]
        self.assertEqual(planned_open_shot_import_quota(225, 5, rows), 3)
        self.assertEqual(planned_open_shot_import_quota(1, 5, rows), 1)
        self.assertEqual(planned_open_shot_import_quota(225, 2, rows), 0)

    def test_unbounded_default_keeps_batch_limit(self):
        self.assertEqual(planned_open_shot_import_quota(80, None, []), 80)

    @patch('engine.collect.read_json')
    @patch('engine.collect.fetch_json', side_effect=AssertionError('Do not fetch'))
    def test_zero_quota_makes_no_web_requests(self, fetch, load):
        load.return_value = [{'id': 's1', 'source': 'StatsBomb Open Data'}]
        history, info = shot_archive(offline=False, max_matches=0)
        self.assertEqual(len(history), 1)
        self.assertEqual(info['imported_statsbomb'], 0)
        fetch.assert_not_called()


if __name__ == '__main__':
    unittest.main()
