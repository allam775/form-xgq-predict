"""Offline privacy schema tests for the 365Scores player-field probe."""
import importlib
import unittest
p=importlib.import_module("research.365_player_stat_schema_probe")
class Tests(unittest.TestCase):
    def test_keys_and_metric_titles_only(self):
        game={"game":{"homeCompetitor":{
              "id":14,"name":"Fake Team",
              "lineups":{"players":[
                 {"player":{"id":9092,"name":"Private Shooter"},
                   "statistics":[{"name":"Total Shots","value":"3"},
                                 {"name":"Expected Goals","value":"0.75"}]},
                 {"player":{"id":9093,"name":"Player Goalkeeper"},
                   "statistics":[{"name":"Shots on Target","value":"1"}]}]}},
             "awayCompetitor":{"id":22,"name":"Another Team",
                 "lineups":{"players":[{"player":{"id":9001,"name":"Private"},"shots":2}]}},
             "members":[]}}
        out=p.profile(game)
        text=str(out)
        self.assertIn("total shots",text.lower())
        self.assertIn("expected goals",text.lower())
        self.assertNotIn("Private Shooter",text)
        self.assertNotIn("9092",text)
        self.assertNotIn("0.75",text)
    def test_no_player_text_mistaken_for_stat_name_outside_stat_nodes(self):
        out=p.profile({"game":{"homeCompetitor":{"name":"Goal Scorer",
                   "id":11},"awayCompetitor":{"name":"Shot Star","id":12}}})
        self.assertEqual(out["recognized_metric_labels"],{})
    def test_refuse_non_game_payload(self):
        with self.assertRaises(ValueError):
            p.profile([])
if __name__=="__main__":
    unittest.main()
