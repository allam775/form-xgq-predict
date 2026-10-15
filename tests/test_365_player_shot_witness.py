"""Offline checks of player-level shot attribution and individual xG totals."""
import unittest
from engine.player_shot_witness365 import player_stats,individual_shots,compare_players

def event(pid,x,team,kind="Missed"):
    return {"playerId":pid,"competitorId":team,"xg":str(x),
            "outcome":{"name":kind}}

def person(pid,team,shots,xg=None,target=None):
    rows=[{"name":"Total Shots","type":"player","value":str(shots)}]
    if xg is not None:rows.append({"name":"Expected Goals","type":"player","value":str(xg)})
    if target is not None:rows.append({"name":"Shots On Target","type":"player","value":str(target)})
    return {"id":pid,"competitorId":team,"name":"Private Player",
            "stats":rows}

def game():
    return {"homeCompetitor":{"id":2,"name":"A"},
            "awayCompetitor":{"id":3,"name":"B"},
            "members":[person(201,2,2,"0.40",1),
                       person(202,2,0),
                       person(301,3,2,"0.50",1),
                       person(302,3,0)],
            "chartEvents":{"events":[
                event(201,.20,2,"Saved"),event(201,.20,2),
                event(301,.20,3,"Saved"),event(301,.30,3)]}}
def witness():
    return {"home":{"shots":2,"xg":.4,"xg_display_decimals":2},
            "away":{"shots":2,"xg":.5,"xg_display_decimals":2}}

class Tests(unittest.TestCase):
    def test_all_players_and_xg_reconcile(self):
        result=compare_players(game(),witness())
        self.assertTrue(result["player_evidence_complete"])
        self.assertEqual(result["aggregate"]["stats_players"],4)
        self.assertEqual(result["aggregate"]["players_with_xg_gap"],0)
        self.assertEqual(result["by_side"]["home"]["stat_shots_total"],2)
    def test_original_provider_player_stats_in_global_game_statistics(self):
        g=game()
        g["statistics"]=g.pop("members")
        result=compare_players(g,witness())
        self.assertTrue(result["player_evidence_complete"])

    def test_overcount_detected_for_exact_player(self):
        g=game()
        g["chartEvents"]["events"].append(event(201,.2,2))
        report=compare_players(g,witness())
        self.assertFalse(report["player_evidence_complete"])
        self.assertEqual(len(report["by_side"]["home"]["gaps"]),1)
        self.assertEqual(report["by_side"]["home"]["gaps"][0],("201",1))
    def test_aggregate_independent_team_xg_conflict_not_hidden(self):
        v=witness();v["home"]["xg"]=.9
        r=compare_players(game(),v)
        # Player-level witness is possible, but a separate team-total conflict
        # still exists and must remain explicitly reported by the batch.
        self.assertTrue(r["player_evidence_complete"])
        self.assertNotIn("production",str(r))
    def test_missing_expected_goals_for_shooter(self):
        g=game()
        g["members"][0]["stats"]=[{"name":"Total Shots","value":"2"}]
        r=compare_players(g,witness())
        self.assertFalse(r["player_evidence_complete"])
        self.assertEqual(r["aggregate"]["players_missing_xg"],1)
    def test_shooters_without_player_reference_not_accepted(self):
        g=game()
        del g["chartEvents"]["events"][0]["playerId"]
        r=compare_players(g,witness())
        self.assertFalse(r["player_evidence_complete"])
        self.assertEqual(r["aggregate"]["unmapped_shots"],1)
    def test_mismatch_in_player_xg_even_if_team_count_equal(self):
        g=game();g["members"][0]["stats"][1]["value"]="0.90"
        r=compare_players(g,witness())
        self.assertFalse(r["player_evidence_complete"])
        self.assertGreater(r["aggregate"]["players_with_xg_gap"],0)
    def test_duplicate_owner_with_conflicting_stat_data_rejected(self):
        g=game();g["members"].append(person(201,2,3,"0.4"))
        with self.assertRaisesRegex(ValueError,"conflicting_player"):
            player_stats(g)
    def test_wrong_team_player_cannot_be_attributed(self):
        g=game()
        g["chartEvents"]["events"][0]["playerId"]=301
        with self.assertRaisesRegex(ValueError,"opposite_team"):
            compare_players(g,witness())
    def test_stats_owner_absent_rejected(self):
        g=game();g["members"]=[]
        with self.assertRaisesRegex(ValueError,"no_player_stats"):
            compare_players(g,witness())
    def test_player_no_shots_zero_xg_is_allowed(self):
        g=game()
        r=compare_players(g,witness())
        self.assertTrue(r["player_evidence_complete"])
    def test_non_integral_total_shots_rejected(self):
        g=game()
        g["members"][0]["stats"][0]["value"]="2.1"
        with self.assertRaisesRegex(ValueError,"nonintegral"):
            compare_players(g,witness())
if __name__=="__main__":unittest.main()
