"""Offline contract tests: no calls to 365Scores or third-party hosts."""
import json
import tempfile
from pathlib import Path
import unittest
from urllib.parse import parse_qs, urlparse

from engine import provider365


def game(mid='123456789', status='Finished'):
    return {"game": {
        "id": mid, "statusText": status, "startTimeUTC": "2026-10-09T20:00:00Z",
        "competition": {"id": 999, "name": "Premier League", "countryName": "England"},
        "homeCompetitor": {"id": 11, "name": "Arsenal", "score": 2},
        "awayCompetitor": {"id": 22, "name": "Chelsea", "score": 1},
        "chartEvents": {"events": [
            {"eventType": "Shot", "teamId": 11, "expectedGoals": 0.2},
            {"eventType": "Shot", "teamId": 11, "expectedGoals": 0.4},
            {"eventType": "Shot", "teamId": 22, "xg": 0.1},
            {"eventType": "Shot", "teamId": 22, "xg": 0.3},
            {"eventType": "Foul", "teamId": 22},
        ]},
    }}

class Provider365Tests(unittest.TestCase):
    def test_parse_game_true_per_shot_xg(self):
        row=provider365.parse_game(game(), 'en.1')
        self.assertEqual(row['source_match_id'], '123456789')
        self.assertAlmostEqual(row['home_xgq'], (0.2**2+0.4**2)/2)
        self.assertEqual(row['home_shots'],2)
        self.assertEqual(row['away_shots'],2)
        self.assertEqual(row['source'], '365Scores (opt-in; rights required)')

    def test_365_real_chart_format_string_xg_and_numeric_event_type(self):
        # Reproduces the confirmed Roma vs Inter *structure*, not its raw data:
        # 34 chart events, xg as numeric strings, competitorNum 1 or 2, type 0.
        g=game(mid='4732693', status='Ended')
        g['game']['competition']={'id': 998,'name':'Serie A','countryName':'Italy'}
        g['game']['homeCompetitor']={'id': 111, 'name':'AS Roma', 'score':1}
        g['game']['awayCompetitor']={'id': 224, 'name':'Inter Milan', 'score':2}
        g['game']['chartEvents']={'events': [
            {'xg':'0.17', 'competitorNum':1, 'type':0} for _ in range(18)
        ] + [
            {'xg':'0.02', 'competitorNum':2, 'type':0} for _ in range(16)
        ]}
        r=provider365.parse_game(g,'it.1','4732693')
        self.assertEqual((r['home_shots'],r['away_shots']), (18,16))
        self.assertAlmostEqual(r['home_xg'],18*0.17)
        self.assertAlmostEqual(r['away_xg'],16*0.02)
        self.assertAlmostEqual(r['home_xgq'],0.17**2)
        self.assertAlmostEqual(r['away_xgq'],0.02**2)

    def test_string_xg_zeros_whitespace_and_rejected_invalid_values(self):
        self.assertEqual(provider365._xg({'xg':'0'}),0.0)
        self.assertEqual(provider365._xg({'xg':' 0.17 '}),0.17)
        self.assertEqual(provider365._xg({'xg':'1.000'}),1.0)
        for bad in ('NaN','inf','-0.1','1.1','0,15','12%', '', 'hello', True):
            self.assertIsNone(provider365._xg({'xg':bad}),bad)
            self.assertTrue(provider365._is_shot({'xg':bad}),bad)

    def test_malformed_string_xg_is_not_silently_skipped(self):
        for malformed in ('', 'NaN', 'n/a', '1.5', None):
            g=game()
            g['game']['chartEvents']['events'][0]={'xg':malformed,'competitorNum':1,'type':0}
            with self.subTest(malformed=malformed):
                with self.assertRaisesRegex(ValueError,'individual xG'):
                    provider365.parse_game(g,'en.1')

    def test_aliases_and_zero_score(self):
        g=game();g['game']['homeCompetitor']['score']={'score':0,'current':3}
        r=provider365.parse_game(g,'en.1',aliases={'Arsenal':'Arsenal FC'})
        self.assertEqual(r['home'],'Arsenal FC')
        self.assertEqual(r['hg'],0)

    def test_no_final_no_scores_or_aggregate(self):
        g=game(status='Scheduled')
        with self.assertRaisesRegex(ValueError,'not confirmed final'):
            provider365.parse_game(g, 'en.1')
        g=game(); del g['game']['homeCompetitor']['score']
        with self.assertRaisesRegex(ValueError,'final score'):
            provider365.parse_game(g,'en.1')
        g=game(); g['game']['chartEvents']={'events':[]};g['game']['expectedGoals']=1.5
        with self.assertRaisesRegex(ValueError,'shot-level'):
            provider365.parse_game(g,'en.1')

    def test_no_missing_xg_or_unattributable_shot(self):
        g=game();g['game']['chartEvents']['events'][0].pop('expectedGoals')
        with self.assertRaisesRegex(ValueError,'individual xG'):
            provider365.parse_game(g,'en.1')
        g=game();g['game']['chartEvents']['events'][0].pop('teamId')
        with self.assertRaisesRegex(ValueError,'attribute'):
            provider365.parse_game(g,'en.1')

    def test_auth_gates_explicit(self):
        self.assertFalse(provider365.enabled({}))
        self.assertTrue(provider365.enabled({'XGQ_365_ACCESS_AUTHORIZED':'true'}))
        self.assertFalse(provider365.publication_allowed({}))
        self.assertFalse(provider365.private_only({}))
        self.assertTrue(provider365.private_only({'XGQ_365_PRIVATE_ONLY': 'true'}))

    def test_bounded_team_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'teams.json'
            p.write_text(json.dumps([{'team_id':'11','league':'en.1'}]))
            self.assertEqual(provider365.read_teams(p), [('11','en.1',())])
            p.write_text(json.dumps([{'team_id':'bogus','league':'en.1'}]))
            with self.assertRaises(ValueError): provider365.read_teams(p)

    def test_automatic_results_then_game(self):
        calls=[]
        def fake(url):
            u=urlparse(url);calls.append(u.path)
            if u.path.endswith('/games/results/'):
                self.assertEqual(parse_qs(u.query)['competitors'], ['11'])
                return {'games':[{'gameId':'123456789','homeCompetitor':{'id':11},'awayCompetitor':{'id':22}}]}
            if u.path.endswith('/game/'):
                return game()
            raise AssertionError(url)
        results,health=provider365.collect([], [('11','en.1',())], transport=fake)
        self.assertEqual(health['added'],1)
        self.assertEqual(health['fetched'],2)
        self.assertEqual(len(results),1)
        self.assertEqual(len(calls),2)
        _,later=provider365.collect(results, [('11','en.1',())], transport=fake)
        self.assertEqual(later['added'],0)

    def test_no_unbounded_requests(self):
        with self.assertRaises(ValueError):
            provider365.collect([], [('1','en.1')], transport=lambda _: {}, max_new=999)

if __name__=='__main__':unittest.main()
