"""Archive quality tests use only local minimal fixtures, never demo forecasts."""
import unittest
from datetime import date
from engine.archive_quality import audit_public_history, season_start_day


class QualityAuditTests(unittest.TestCase):
    def match(self, mid, day, league='en.1', home='Alpha', away='Beta', source='StatsBomb Open Data'):
        return {'id': str(mid), 'source_match_id': str(mid), 'date': day, 'league': league,
                'h': home, 'a': away, 'source': source, 'home_xgq': .02, 'away_xgq': .03}

    def test_season_boundaries(self):
        self.assertEqual(season_start_day('2016-06-30'), 2015)
        self.assertEqual(season_start_day('2016-07-01'), 2016)
        self.assertEqual(season_start_day('2015-08-08'), 2015)

    def test_league_distribution_and_staleness(self):
        a = self.match(1, '2015-08-08')
        b = self.match(2, '2016-05-17')
        c = self.match(3, '2026-10-09', 'fr.1')
        x = audit_public_history([b, c, a], as_of=date(2026, 10, 10))
        self.assertEqual(x['matches'], 3)
        self.assertEqual(x['published_2015_16_coverage']['en.1']['verified'], 2)
        self.assertEqual(x['published_2015_16_coverage']['en.1']['published_index_matches'], 380)
        self.assertEqual(x['leagues']['en.1']['season_coverage']['2015/16'], 2)
        self.assertEqual(x['matches_within_120_days'], 1)
        self.assertFalse(x['historical_only_not_live_form'])

    def test_public_audit_refuses_private_data(self):
        with self.assertRaisesRegex(ValueError, 'private'):
            audit_public_history([self.match(1, '2015-08-01', source='365Scores')],
                                 as_of=date(2026, 10, 10))

    def test_duplicate_and_future_data_fail_closed(self):
        a = self.match(1, '2015-08-01')
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            audit_public_history([a, dict(a)], as_of=date(2026, 10, 10))
        with self.assertRaisesRegex(ValueError, 'future'):
            audit_public_history([self.match(3,'2026-10-11')], as_of=date(2026,10,10))

    def test_missing_real_evidence_fails(self):
        a = self.match(1, '2015-08-01')
        del a['home_xgq']
        with self.assertRaisesRegex(ValueError, 'Invalid'):
            audit_public_history([a], as_of=date(2026,10,10))

    def test_empty_archive_is_explicit(self):
        a=audit_public_history([], as_of=date(2026,10,10))
        self.assertEqual(a['league_count'], 0)
        self.assertTrue(a['historical_only_not_live_form'])


if __name__ == '__main__':
    unittest.main()
