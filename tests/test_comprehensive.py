"""Safety and consistency tests for Penniless Comprehensive."""
import unittest
from datetime import date,timedelta
from engine.comprehensive import compare,ensemble,PARAMETERS
from engine.xgq import strict_row
from engine.provider_understat import SOURCE


def sample():
    fixtures=[]
    start=date(2025,7,1)
    for i in range(445):
        day=(start+timedelta(days=i)).isoformat()
        home,away=("Roma","Como") if i%2 else ("Como","Roma")
        fixtures.append(strict_row({"date":day,"league":"it.1",
            "home_team":home,"away_team":away,
            "home_goals":i%4,"away_goals":(i+2)%4,
            "home_shots_xg":[.10,.05,.20,.35,.12],
            "away_shots_xg":[.02,.10,.14,.25,.11],
            "source":SOURCE,"source_match_id":str(200000+i)}))
    return fixtures

class ComprehensiveTests(unittest.TestCase):
    def test_probability_bounds_and_weights(self):
        base={m:{"home":.4,"draw":.25,"away":.35}
              for m in ("stage1","stage3","elo","dc")}
        for params in PARAMETERS:
            q=ensemble(base,params)
            self.assertAlmostEqual(sum(q.values()),1,places=8)
            self.assertTrue(all(0<=v<=1 for v in q.values()))
    def test_chronology_fixed_parameters_no_leakage(self):
        hist=sample()
        first=compare(hist,as_of="2026-09-17")
        self.assertEqual(first["status"],"retrospective_chronological")
        self.assertGreater(first["validation_games"],20)
        self.assertIn("comprehensive",first["historical_holdout"]["metrics"])
        future=strict_row({"date":"2026-09-18","league":"it.1",
            "home_team":"Roma","away_team":"Como",
            "home_goals":9,"away_goals":0,"home_shots_xg":[.95],
            "away_shots_xg":[.02],"source":SOURCE,"source_match_id":"999900"})
        second=compare(hist+[future],as_of="2026-09-17")
        for item in ("validation","historical_holdout","season_2026_27",
                      "validation_selected_params"):
            self.assertEqual(first[item],second[item])
    def test_invalid_parameters(self):
        with self.assertRaises(ValueError):
            compare(sample(),as_of="2026-09-17",params=(.99,.99,.99,1.0))

if __name__=="__main__":
    unittest.main()
