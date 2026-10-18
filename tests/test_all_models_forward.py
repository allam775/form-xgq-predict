"""No rewriting legacy forecasts, no after-kickoff fake predictions."""
import json
import unittest
from datetime import datetime,timezone
from engine.all_models_forward import make_supplement
from engine.daily_forecast import MODEL_SUITE, LEAD, HORIZON, _forecast
from tests.test_daily_forecast import synthetic

NOW=datetime(2026,10,18,20,0,tzinfo=timezone.utc)
KO="2026-10-19T18:45:00+00:00"
def fixture():
    return {"id":"it.1|999009","league":"it.1","date":"2026-10-19",
        "source_match_id":"999009","home":"Roma","away":"Como",
        "h":"roma","a":"como","kickoff_utc":KO}

def suite():
    probs={"home":.5,"draw":.25,"away":.25}
    return {"models":{n:dict(probs) for n in MODEL_SUITE},
            "picks":{n:"home" for n in MODEL_SUITE},
            "stage3_missing_replaced_by_stage1":False}

def old_row():
    return {"id":"it.1|999009","league":"it.1","date":"2026-10-19",
        "source_match_id":"999009","home_id":"roma","away_id":"como",
        "kickoff_utc":KO,"frozen_at_utc":"2026-10-17T12:00:00+00:00",
        "model":"stage1_volume_xgq","models":{
           "xgq_production_formula":{"home":.6,"draw":.2,"away":.2},
           "stage1_volume_xgq":{"home":.6,"draw":.2,"away":.2}}}

class AllModelsForwardTests(unittest.TestCase):
    def test_only_missing_models_frozen_in_separate_ledger(self):
        old=old_row()
        old_bytes=json.dumps(old,sort_keys=True)
        new=make_supplement(fixture(),old,suite(),now=NOW)
        self.assertIsNotNone(new)
        self.assertEqual(set(new["models"]),set(MODEL_SUITE)-set(old["models"]))
        self.assertNotIn(old["model"],new["models"])
        self.assertEqual(json.dumps(old,sort_keys=True),old_bytes)
        self.assertLess(datetime.fromisoformat(new["frozen_at_utc"]),datetime.fromisoformat(new["kickoff_utc"]))
        self.assertTrue(new["no_original_prediction_changed"])
    def test_none_if_existing_complete(self):
        old=old_row()
        old["models"]=suite()["models"]
        self.assertIsNone(make_supplement(fixture(),old,suite(),now=NOW))
    def test_reject_kickoff_and_identity_changes(self):
        x=fixture()
        x["kickoff_utc"]="2026-10-20T18:45:00+00:00"
        with self.assertRaises(ValueError):
            make_supplement(x,old_row(),suite(),now=NOW)
        y=fixture()
        y["source_match_id"]="888888"
        with self.assertRaises(ValueError):
            make_supplement(y,old_row(),suite(),now=NOW)
    def test_postkickoff_refused(self):
        with self.assertRaises(ValueError):
            make_supplement(fixture(),old_row(),suite(),
                now=datetime(2026,10,19,18,30,tzinfo=timezone.utc))
    def test_unavailable_model_not_impersonated(self):
        bad=suite()
        bad["stage3_missing_replaced_by_stage1"]=True
        with self.assertRaises(ValueError):
            make_supplement(fixture(),old_row(),bad,now=NOW)
    def test_timing_constants(self):
        self.assertEqual(HORIZON.total_seconds(),72*3600)
        self.assertGreater(LEAD.total_seconds(),0)

if __name__=="__main__":
    unittest.main()
