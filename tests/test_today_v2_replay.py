"""Retrospective V2 replay does not use same-day outcomes for forecasts."""
import unittest
from datetime import datetime,timedelta,timezone
from engine.today_v2_replay import replay
from engine.provider_understat import SOURCE
from engine.xgq import strict_row

def history():
    origin=datetime(2026,6,1,tzinfo=timezone.utc)
    out=[]
    for i in range(125):
        day=(origin+timedelta(days=i)).date().isoformat()
        h,a=("Roma","Como") if i%2 else ("Como","Roma")
        out.append(strict_row({"league":"it.1","date":day,
            "home_team":h,"away_team":a,
            "home_goals":i%3,"away_goals":(i+1)%3,
            "home_shots_xg":[.04,.1,.23,.16,.07],
            "away_shots_xg":[.03,.15,.14,.12,.08],
            "source":SOURCE,"source_match_id":str(300000+i)}))
    return out

def frozen():
    return [{"id":"it.1|999999","league":"it.1","date":"2026-10-17",
             "home":"Roma","away":"Como","home_id":"roma","away_id":"como",
             "source_match_id":"999999","kickoff_utc":"2026-10-17T14:00:00+00:00",
             "model":"xgq_production_formula",
             "picks":{"xgq_production_formula":"home"}}]

class TestReplay(unittest.TestCase):
    def test_no_same_day_leak_or_mutation(self):
        h=history();saved=frozen()
        first=replay(saved,h)
        self.assertEqual(first["generated"],1)
        self.assertEqual(first["games"][0]["status"],"retrospective_replay_not_frozen")
        self.assertEqual(saved[0]["model"],"xgq_production_formula")
        next_game=strict_row({"league":"it.1","date":"2026-10-17",
            "home_team":"Roma","away_team":"Como",
            "home_goals":4,"away_goals":0,
            "home_shots_xg":[.9],"away_shots_xg":[.01],
            "source":SOURCE,"source_match_id":"999999"})
        after=replay(saved,h+[next_game])
        self.assertEqual(first["games"][0]["models"],after["games"][0]["models"])
        self.assertEqual(after["verified_finals"],1)

if __name__=="__main__":
    unittest.main()
