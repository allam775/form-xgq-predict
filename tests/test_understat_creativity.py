"""Source and no-fabrication rules for official roster-created xA/key passes."""
import unittest
from engine.provider_understat import SOURCE, parse_match
from engine.understat_creativity import parse_creativity, validate_creativity


def sample():
    indexed={"id":"921001","league":"en.1","date":"2026-10-01",
      "home":"Example Home","away":"Example Away","home_id":"123","away_id":"456",
      "hg":0,"ag":0}
    def shot(side, xg, situation="OpenPlay", assisted=""):
        return {"match_id":"921001","h_a":side,"xG":str(xg),"situation":situation,
                "player_assisted":assisted,"result":"MissedShots"}
    payload={"shots":{"h":[shot("h",.4,assisted="Creator"),
                           shot("h",.78,situation="Penalty")],
                       "a":[shot("a",.15)]},
     "rosters":{
       "h":{"1":{"team_id":"123","xA":"0.31","key_passes":"2",
                 "xGChain":"0.6","xGBuildup":"0.2"}},
       "a":{"2":{"team_id":"456","xA":"0.15","key_passes":"1",
                 "xGChain":"0.3","xGBuildup":"0.12"}}}}
    return indexed,payload


class CreativityTests(unittest.TestCase):
    def test_genuine_match_rosters_and_penalty_exclusion(self):
        indexed,payload=sample()
        raw=parse_match(indexed,payload)
        meta=parse_creativity(indexed,payload,previous=raw)
        self.assertEqual(meta["home_key_passes"],2)
        self.assertEqual(meta["away_key_passes"],1)
        self.assertEqual(meta["home_xa"],.31)
        self.assertEqual(meta["home_npxg"],.4)
        self.assertEqual(meta["home_high_xg_attempts"],1)
        self.assertEqual(meta["home_assisted_shots"],1)
        self.assertEqual(meta["big_chance_metric"],"nonpenalty_shots_with_xg_at_least_0.30_proxy")
        self.assertNotIn("Creator",str(meta))
        self.assertNotIn("rosters",str(meta))
        self.assertNotIn("player_assisted",str(meta))

    def test_no_fake_roster_stats_or_mixed_team_identity(self):
        indexed,payload=sample()
        del payload["rosters"]["h"]["1"]["xA"]
        with self.assertRaises(ValueError):
            parse_creativity(indexed,payload)
        indexed,payload=sample()
        payload["rosters"]["h"]["1"]["team_id"]="456"
        with self.assertRaises(ValueError):
            parse_creativity(indexed,payload)

    def test_shot_history_checksum_check(self):
        indexed,payload=sample()
        previous=parse_match(indexed,payload)
        previous["home_xg"]+=.1
        with self.assertRaises(ValueError):
            parse_creativity(indexed,payload,previous=previous)

    def test_absent_big_chance_cannot_be_labeled_official(self):
        indexed,payload=sample()
        result=parse_creativity(indexed,payload)
        self.assertNotIn("big_chances_created",result)
        self.assertTrue(validate_creativity(result)["home_high_xg_attempts"]>=1)


if __name__=="__main__":
    unittest.main()
