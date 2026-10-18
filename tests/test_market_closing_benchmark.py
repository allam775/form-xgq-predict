"""Strict fixture identity and no-vig commercial market research tests."""
import unittest
from engine.market_closing_benchmark import (norm,same_team,parse_date,
 no_vig,market_csv,match_market,MARKETS)

class CommercialOddsTests(unittest.TestCase):
    def test_remove_overround_and_tie_argmax(self):
        p=no_vig({"AvgCH":"2.00","AvgCD":"3.40","AvgCA":"4.20"},
                 MARKETS["closing_market_average"])
        self.assertAlmostEqual(sum(p.values()),1,10)
        self.assertGreater(p["home"],p["draw"])
    def test_no_partial_or_invalid_price(self):
        self.assertIsNone(no_vig({"AvgCH":"2.5","AvgCD":"","AvgCA":"4"},MARKETS["closing_market_average"]))
    def test_csv_date(self):
        csv="Date,HomeTeam,AwayTeam,FTHG,FTAG,AvgCH,AvgCD,AvgCA\n17/10/2026,Liverpool,Everton,0,0,2.1,3.4,4\n"
        r=market_csv(csv,"en.1")
        self.assertEqual(len(r),1)
        self.assertEqual(r[0]["date"],"2026-10-17")
        self.assertAlmostEqual(sum(r[0]["probs"]["closing_market_average"].values()),1)
    def test_team_alias_and_strict_scores(self):
        self.assertTrue(same_team("RB Leipzig","RasenBallsport Leipzig"))
        self.assertTrue(same_team("Man United","Manchester United"))
        self.assertFalse(same_team("Liverpool","Everton"))
        base={"league":"en.1","date":"2026-10-17","home":"Man United",
           "away":"Everton","home_goals":0,"away_goals":0,
           "actual":"draw","models":{"stage1":{"home":.3,"draw":.4,"away":.3}}}
        exact={"league":"en.1","date":"2026-10-17","home":"Manchester United",
           "away":"Everton","hg":0,"ag":0,"probs":{}}
        rows,_=match_market([base],[exact],None)
        self.assertEqual(len(rows),1)
        rows,_=match_market([base],[{**exact,"hg":1}],None)
        self.assertEqual(len(rows),0)
        rows,_=match_market([base],[{**exact,"date":"2026-10-18"}],None)
        self.assertEqual(len(rows),0)
        rows,_=match_market([base],[exact,dict(exact)],None)
        self.assertEqual(len(rows),0)

if __name__=="__main__":
    unittest.main()
