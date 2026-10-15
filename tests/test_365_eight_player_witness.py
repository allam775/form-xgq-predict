"""Offline no-network eight-rejection player comparison / D1 privacy tests."""
import importlib,json,unittest
from unittest.mock import patch

mod=importlib.import_module("research.365_eight_player_witness")

def case():
    return {"source_match_id":"4732693","league":"uefa.cl",
            "competition_id":"572","date":"2026-10-13",
            "home":"Inter Milan","away":"Club Brugge","hg":3,"ag":4}
def datum():
    return {"game":{"id":4732693,"statusText":"Ended",
                    "startTimeUTC":"2026-10-13T19:00:00Z",
                    "competitionId":572,
                    "competitionDisplayName":"UEFA Champions League",
                    "homeCompetitor":{"id":2,"name":"Inter Milan","score":3},
                    "awayCompetitor":{"id":3,"name":"Club Brugge","score":4},
                    "members":[
                        {"id":11,"competitorId":2,"stats":[
                            {"name":"Total Shots","value":"2"},
                            {"name":"Expected Goals","value":"0.40"}]},
                        {"id":22,"competitorId":3,"stats":[
                            {"name":"Total Shots","value":"2"},
                            {"name":"Expected Goals","value":"0.50"}]}],
                    "chartEvents":{"events":[
                        {"playerId":11,"competitorNum":1,"xg":"0.20"},
                        {"playerId":11,"competitorNum":1,"xg":"0.20"},
                        {"playerId":22,"competitorNum":2,"xg":"0.20"},
                        {"playerId":22,"competitorNum":2,"xg":"0.30"}]}},
            "competitions":[{"id":572,"name":"UEFA Champions League",
                             "countryId":5,"isInternational":True}]}
def source():
    return {"source_stats":{"home":{"shots":2,"xg":0.8,"xg_display_decimals":2},
                            "away":{"shots":2,"xg":0.5,"xg_display_decimals":2}}}

class DB:
    def __init__(self):self.rows={}
    def query(self,sql,params=()):
        if sql.startswith("CREATE TABLE"):return []
        if "SELECT id FROM private_365_player_witness" in sql:
            return [{"id":k} for k in self.rows]
        if "SELECT payload FROM private_365_rejected_diagnosis" in sql:
            return [{"payload":json.dumps(source())}]
        if "SELECT payload FROM private_365_stats_audit" in sql:
            return [{"payload":json.dumps({"status":"home_xg_mismatch"})}]
        if "INSERT OR REPLACE INTO private_365_player_witness" in sql:
            self.rows[params[0]]=json.loads(params[1]);return []
        if "SELECT id,payload FROM private_365_player_witness" in sql:
            return [{"id":k,"payload":json.dumps(v)} for k,v in self.rows.items()]
        raise AssertionError(sql)

class Tests(unittest.TestCase):
 def test_offline_one_case_player_level_both_sides(self):
    db=DB();calls=[]
    with patch.object(mod.original,"unresolved",return_value={"4732693":case()}):
        result=mod.audit(db=db,fetch=lambda mid:calls.append(mid) or datum(),limit=1,delay=0)
    self.assertEqual(calls,["4732693"])
    self.assertEqual(result["cases_with_all_player_shots_and_xg_verified"],1)
    self.assertEqual(result["cases_where_player_only_evidence_conflicts_with_team_total"],1)
    self.assertEqual(result["match_promotions"],0)
    self.assertEqual(len(db.rows),1)
    self.assertNotIn("shot_events",str(db.rows))
    self.assertNotIn("playerId",str(result))
 def test_repeat_does_not_refetch_player_data(self):
    db=DB()
    with patch.object(mod.original,"unresolved",return_value={"4732693":case()}):
        first=mod.audit(db=db,fetch=lambda mid:datum(),limit=1,delay=0)
        second=mod.audit(db=db,fetch=lambda mid:(_ for _ in ()).throw(AssertionError("refetched")),limit=1,delay=0)
    self.assertEqual(first["provider_requests"],1)
    self.assertEqual(second["provider_requests"],0)
    self.assertEqual(second["previously_diagnosed"],1)
    self.assertEqual(second["cumulative_player_witness_complete"],1)
 def test_wrong_match_id_never_accept(self):
    g=datum();g["game"]["id"]=999999
    with self.assertRaisesRegex(ValueError,"match_id"):
        mod.validate(g,case(),"4732693")
 def test_request_limits_are_hard(self):
    with self.assertRaises(ValueError):
        mod.audit(db=DB(),limit=9,delay=0)
 def test_shooter_unique_extra_event_flag(self):
    evidence={"aggregate":{"unmapped_shots":0,"stats_shots_sum_diff":{"home":0,"away":0}},
              "by_side":{"home":{"gaps":[("11",1)],"stat_shots_total":2},
                         "away":{"gaps":[],"stat_shots_total":2}}}
    w={"home":{"shots":2},"away":{"shots":2}}
    self.assertTrue(mod.isolated_extra_shooter(evidence,w))
    evidence["by_side"]["home"]["gaps"]=[("11",1),("12",1)]
    self.assertFalse(mod.isolated_extra_shooter(evidence,w))
if __name__=="__main__":unittest.main()
