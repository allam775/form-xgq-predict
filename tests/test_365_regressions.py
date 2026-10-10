"""Regression tests for 365Scores connection shapes; entirely offline."""
import unittest
from urllib.parse import urlparse, parse_qs
from engine import provider365


def fake_game(mid="4732693", *, league="it.1", country="Italy", competition="Serie A"):
    return {"game": {
        "id": mid, "statusText": "Ended", "startTimeUTC": "2026-10-09T20:00:00Z",
        "competition": {"id": 500, "name": competition, "countryName": country},
        "homeCompetitor": {"id": 111, "name": "AS Roma", "score": None},
        "awayCompetitor": {"id": 224, "name": "Inter Milan", "currentScore": {"current": "2"}},
        "homeScore": {"current": "1"},
        "chartEvents": {"events": (
            [{"type": 0, "xg": "0.17", "competitorNum": 1} for _ in range(18)] +
            [{"type": 0, "xg": "0.02", "competitorNum": 2} for _ in range(16)]
        )},
    }}


class Scores365Regression(unittest.TestCase):
    def test_null_team_score_falls_back_to_game_score(self):
        r = provider365.parse_game(fake_game(), "it.1", expected_team_id="224")
        self.assertEqual((r["hg"], r["ag"]), (1, 2))
        self.assertEqual((r["home_shots"], r["away_shots"]), (18, 16))

    def test_results_field_can_hold_score(self):
        g=fake_game();g["game"].pop("homeScore")
        g["game"]["homeCompetitor"]["results"]=[{"value":"1"}]
        self.assertEqual(provider365.parse_game(g,"it.1")["hg"], 1)

    def test_reject_unverified_cup_and_same_name_other_country(self):
        for comp,country in (("Coppa Italia", "Italy"),("Serie A","Brazil"),("Friendly", "")):
            g=fake_game(competition=comp, country=country)
            with self.subTest(competition=comp,country=country):
                with self.assertRaisesRegex(ValueError, "competition"):
                    provider365.parse_game(g, "it.1")

    def test_verified_competition_id_allows_explicit_match_only(self):
        g=fake_game(competition="Unknown name", country="")
        self.assertEqual(provider365.parse_game(g,"it.1",verified_competition_ids=("500",))["hg"],1)
        with self.assertRaisesRegex(ValueError,"competition"):
            provider365.parse_game(g,"it.1",verified_competition_ids=("501",))

    def test_team_must_be_one_of_game_competitors(self):
        with self.assertRaisesRegex(ValueError, "configured team"):
            provider365.parse_game(fake_game(), "it.1", expected_team_id="999")

    def test_ignore_unrelated_results_even_when_returned_by_team_search(self):
        calls=[]
        def transport(url):
            u=urlparse(url);calls.append(u.path)
            if u.path.endswith('/games/results/'):
                self.assertEqual(parse_qs(u.query)['competitors'],['224'])
                return {'games':[
                    {'gameId':'111111', 'homeCompetitor': {'id':999}, 'awayCompetitor':{'id':888}},
                    {'gameId':'4732693', 'homeCompetitor': {'id':111}, 'awayCompetitor':{'id':224}},
                ]}
            if u.path.endswith('/game/'):
                return fake_game()
            raise AssertionError(url)
        rows,health=provider365.collect([], [('224','it.1',())],transport=transport)
        self.assertEqual((len(rows),health['added'],health['fetched']), (1,1,2))

    def test_detailed_match_other_league_is_rejected(self):
        def transport(url):
            if urlparse(url).path.endswith('/games/results/'):
                return {'games': [{'id':'4732693','homeCompetitor':{'id':111},'awayCompetitor':{'id':224}}]}
            return fake_game(competition='Coppa Italia')
        rows,health=provider365.collect([], [('224','it.1',())],transport=transport)
        self.assertEqual(len(rows),0)
        self.assertEqual(health['rejected'],1)


if __name__=='__main__':unittest.main()
