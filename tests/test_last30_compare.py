"""Synthetic regression tests for recent paired replay without match-day leakage."""
import unittest
from datetime import date,timedelta
from engine.last30_compare import compare
from engine.xgq import strict_row
from engine.provider_understat import SOURCE


def sample():
    rows=[]
    for i in range(90):
        day=(date(2026,7,21)+timedelta(days=i)).isoformat()
        home,away=("Monza","Cagliari") if i%2 else ("Cagliari","Monza")
        rows.append(strict_row({
            "date":day,"league":"it.1","home_team":home,"away_team":away,
            "home_goals":i%3,"away_goals":(i+1)%3,
            "home_shots_xg":[.02,.08,.14,.33,.49],
            "away_shots_xg":[.05,.09,.16,.29,.40],
            "source":SOURCE,"source_match_id":str(900000+i)}))
    return rows


class TestLastMonth(unittest.TestCase):
    def test_paired_and_no_future_date_contamination(self):
        games=sample()
        before=compare(games,start="2026-09-17",end="2026-10-16")
        self.assertEqual(before["status"],"retrospective_paired")
        self.assertEqual(before["paired_games"],30)
        self.assertEqual(before["models"]["stage1"]["n"],30)
        self.assertEqual(before["models"]["stage3"]["n"],30)
        # Tamper with future results outside the requested window. All metrics fixed.
        newer=games+[
            strict_row({"date":"2026-10-18","league":"it.1",
                "home_team":"Monza","away_team":"Cagliari",
                "home_goals":8,"away_goals":0,
                "home_shots_xg":[.9],"away_shots_xg":[.01],
                "source":SOURCE,"source_match_id":"999999"})]
        after=compare(newer,start="2026-09-17",end="2026-10-16")
        for key in ("models","head_to_head","per_league","per_date","paired_games"):
            self.assertEqual(before[key],after[key])
    def test_illegal_window(self):
        with self.assertRaises(ValueError):
            compare([],start="2026-10-16",end="2026-09-17")

if __name__=="__main__":
    unittest.main()
