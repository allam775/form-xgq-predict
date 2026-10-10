"""Owner-controlled Understat opt-in never trusts missing/failed D1 reads."""
import json
import tempfile
from pathlib import Path
import unittest
from engine.understat_config import authorized_config, write_github_env


class UnderstatConfigTests(unittest.TestCase):
    @staticmethod
    def payload(cfg):
        return [{'success': True, 'results': [{'v': json.dumps(cfg)}]}]

    def test_owner_authorized_teams_and_limit(self):
        cfg = {'enabled': True, 'owner_confirmed_collection_and_retention': True,
               'leagues': ['en.1', 'de.1', 'es.1', 'it.1', 'fr.1'], 'max_new': 24}
        x = authorized_config(self.payload(cfg))
        self.assertEqual(x, {'leagues': 'en.1,de.1,es.1,it.1,fr.1', 'max_new': 24})
        with tempfile.TemporaryDirectory() as d:
            out = Path(d)/'github-env'
            self.assertTrue(write_github_env(x, out))
            content = out.read_text()
            self.assertIn('XGQ_UNDERSTAT_STORAGE_AUTHORIZED=1', content)
            self.assertIn('XGQ_UNDERSTAT_LEAGUES=en.1,de.1,es.1,it.1,fr.1', content)

    def test_missing_disabled_leaves_github_env_untouched(self):
        self.assertIsNone(authorized_config([{'success': True, 'results': []}]))
        with tempfile.TemporaryDirectory() as d:
            f = Path(d)/'env'
            self.assertFalse(write_github_env(None, f))
            self.assertFalse(f.exists())
        self.assertIsNone(authorized_config(self.payload({'enabled': False})))

    def test_missing_consent_and_malicious_config_fail_closed(self):
        base = {'enabled': True, 'owner_confirmed_collection_and_retention': True,
                'leagues': ['en.1'], 'max_new': 24}
        for modified in ({'owner_confirmed_collection_and_retention': False},
                         {'leagues': ['xx.1']}, {'leagues': ['en.1\nEXFIL=1']},
                         {'max_new': 100}, {'max_new': '48'}, {'max_new': True}):
            with self.subTest(modified=modified), self.assertRaises((ValueError, PermissionError)):
                authorized_config(self.payload({**base, **modified}))
        for x in ([], [{'success': False, 'results': []}],
                  [{'success': True, 'results': [{}]}],
                  [{'success': True, 'results': [{'v':'{}'}, {'v':'{}'}]}]):
            with self.subTest(x=x), self.assertRaises(ValueError):
                authorized_config(x)


if __name__ == '__main__':
    unittest.main()
