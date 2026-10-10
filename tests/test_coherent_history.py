"""Offline source selection checks; no upstream access or synthetic feed publishing."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest

from engine import collect


class SeasonCohortTests(unittest.TestCase):
    def test_auto_prioritizes_complete_season_and_oldest_matches_first(self):
        competitions = [
            {"competition_id": 2, "season_id": 27, "season_name": "2015/2016"},
            {"competition_id": 11, "season_id": 90, "season_name": "2020/2021"},
        ]
        def match(mid, dt):
            return {"match_id": mid, "match_date": dt, "home_score": 1, "away_score": 0}
        def fake_json(url, **kwargs):
            if url.endswith('/competitions.json'):
                return competitions
            if '/matches/2/27.json' in url:
                return [match(3, '2016-02-03'), match(2, '2015-10-02'), match(1, '2015-08-08')]
            if '/matches/11/90.json' in url:
                return [match(4, '2020-09-15')]
            if '/events/' in url:
                return []
            raise AssertionError(f'Unexpected fetch: {url}')

        with TemporaryDirectory() as directory, \
             patch.object(collect, 'DATA', Path(directory)), \
             patch.object(collect, 'fetch_json', side_effect=fake_json), \
             patch.object(collect, 'statsbomb_to_row') as convert:
            convert.side_effect = lambda m, events, league: {"id": str(m['match_id']),
                  "source_match_id": str(m['match_id']), "source": "StatsBomb Open Data", "date": m['match_date']}
            first, details = collect.shot_archive(max_matches=2)
            self.assertEqual([r['source_match_id'] for r in first], ['1', '2'])
            self.assertEqual(details['focus_open_cohort'], {"competition_id": 2, "season_id": 27})
            self.assertEqual(details['imported_statsbomb'], 2)
            # Next cloud run continues this same season, rather than randomly
            # switching to a later league with no eligible team form.
            import json
            (Path(directory) / 'shot_history.json').write_text(json.dumps(first))
            second, details = collect.shot_archive(max_matches=2)
            self.assertEqual([r['source_match_id'] for r in second][-1], '3')
            self.assertEqual(details['focus_open_cohort'], {"competition_id": 2, "season_id": 27})

    def test_explicit_seasons_are_not_overridden_by_priority(self):
        priority = [(2, 27), (7, 27)]
        pending = [(2, 27, [1]), (7, 27, [2])]
        focused, chosen = collect.prioritize_dense_cohort(priority, pending)
        self.assertEqual(chosen, (2, 27))
        self.assertEqual(focused, [(2, [1])])

    def test_no_priority_left_restores_balanced_mode(self):
        selection = [(2, 27), (7, 27), (11, 42)]
        pending = [(2, 27, []), (7, 27, []), (11, 42, [3])]
        remaining, chosen = collect.prioritize_dense_cohort(selection, pending)
        self.assertIsNone(chosen)
        self.assertEqual(remaining, [(2, []), (7, []), (11, [3])])

if __name__ == '__main__':
    unittest.main()
