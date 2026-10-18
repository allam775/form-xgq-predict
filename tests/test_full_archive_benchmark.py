"""No future game outcome leakage in complete archive and draw pick counting."""
import unittest
from datetime import date,timedelta
from engine.full_archive_benchmark import _evaluate,_season,benchmark,MODELS
from engine.xgq import strict_row
from engine.provider_understat import SOURCE

class TestFullArchive(unittest.TestCase):
    def test_exact_draw_pick_count_and_actual_draws(self):
        pred=lambda h,d,a:{"home":h,"draw":d,"away":a}
        rows=[
          {"actual":"draw","models":{"draw_v2":pred(.3,.4,.3)}},
          {"actual":"home","models":{"draw_v2":pred(.3,.4,.3)}},
          {"actual":"draw","models":{"draw_v2":pred(.5,.3,.2)}},
        ]
        x=_evaluate(rows,"draw_v2")
        self.assertEqual((x["n"],x["correct"],x["draw_predictions"],
                          x["correct_draw_predictions"],x["actual_draws"]),
                         (3,1,2,1,2))
    def test_season_labels(self):
        self.assertEqual(_season("2026-10-01"),"2026/27")
        self.assertEqual(_season("2026-05-01"),"2025/26")
    def test_no_future_outcomes(self):
        start=date(2025,7,1)
        games=[]
        for i in range(86):
            day=(start+timedelta(days=i)).isoformat()
            h,a=("Roma","Como") if i%2 else ("Como","Roma")
            games.append(strict_row({"date":day,"league":"it.1",
                "home_team":h,"away_team":a,"home_goals":i%3,"away_goals":(i+1)%3,
                "home_shots_xg":[.1,.2,.12,.05,.3],
                "away_shots_xg":[.08,.07,.14,.32,.13],
                "source":SOURCE,"source_match_id":str(400000+i)}))
        a=benchmark(games,through="2025-09-15")
        newer=strict_row({"date":"2025-09-16","league":"it.1",
            "home_team":"Roma","away_team":"Como","home_goals":10,"away_goals":0,
            "home_shots_xg":[.95],"away_shots_xg":[.03],
            "source":SOURCE,"source_match_id":"999900"})
        b=benchmark(games+[newer],through="2025-09-15")
        self.assertEqual(a["models"],b["models"])
        self.assertEqual(a["eligible_matched_matches"],b["eligible_matched_matches"])

if __name__=="__main__":
    unittest.main()
