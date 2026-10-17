"""Calibration and leak isolation for the completed-match draw lab."""
import unittest
from datetime import date,timedelta
from engine.draw_lab import (apply_draw_calibration, feature_vector,
    fit, report,metrics,draw_watch_selection)
from engine.xgq import strict_row
from engine.provider_understat import SOURCE


class DrawLabTests(unittest.TestCase):
    def test_identity_has_no_1x2_distortion(self):
        probs={"home":.42,"draw":.24,"away":.34}
        for feats in ((1,1,1,1,1),(1,-.5,.2,.1,-.3)):
            self.assertEqual(probs,apply_draw_calibration(probs,feats,(0,)*5))
        p=apply_draw_calibration(probs,(1,1,1,1,1),(.3,.2,.2,.2,.2))
        self.assertAlmostEqual(sum(p.values()),1,places=10)
        self.assertGreater(p["draw"],probs["draw"])
        self.assertAlmostEqual(p["home"]/p["away"],probs["home"]/probs["away"])
    def test_rounded_frozen_ledger(self):
        p={"home":0.38254321,"draw":0.25123456,"away":0.36622222}
        calibrated=apply_draw_calibration(p,(1,.1,.2,0,0),
            (-.143539829,.244601568,-.107317616,0,0))
        self.assertAlmostEqual(sum(calibrated.values()),1,places=12)
        self.assertTrue(all(x>=0 for x in calibrated.values()))
    def test_no_unvalidated_draw_watch(self):
        self.assertEqual(draw_watch_selection([])["status"],"insufficient")
    def test_fitting_converges_directionally(self):
        train=[{"original":{"home":.4,"draw":.2,"away":.4},
                "features":(1,0,0,0,0),"actual":"draw" if i%2==0 else "home"}
               for i in range(200)]
        weight=fit(train)
        self.assertGreater(weight[0],0)
    def test_past_only_source(self):
        # One fixture a day, with all past games available, including season.
        rows=[]
        start=date(2025,7,1)
        for i in range(460):
            home,away=("Roma","Como") if i%2 else ("Como","Roma")
            rows.append(strict_row({"date":(start+timedelta(days=i)).isoformat(),
              "league":"it.1","home_team":home,"away_team":away,
              "home_goals":i%3,"away_goals":(i+2)%3,
              "home_shots_xg":[.07,.11,.25,.14],"away_shots_xg":[.08,.15,.31,.09],
              "source":SOURCE,"source_match_id":str(700000+i)}))
        s1=report(rows,as_of="2026-09-16")
        self.assertEqual(s1["status"],"retrospective_draw_study")
        future=strict_row({"date":"2026-09-17","league":"it.1",
              "home_team":"Roma","away_team":"Como","home_goals":10,"away_goals":0,
              "home_shots_xg":[.85],"away_shots_xg":[.03],
              "source":SOURCE,"source_match_id":"999999"})
        s2=report(rows+[future],as_of="2026-09-16")
        for k in ("selected_model","coefficients","validation","historical","season",
                  "draw_watch_rule"):
            self.assertEqual(s1[k],s2[k])

if __name__=="__main__":
    unittest.main()
