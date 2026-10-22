"""UEFA forecast is genuinely prior to kickoff, no score leakage or edits."""
import unittest
from datetime import datetime,timezone
from research.ucl_forward import (fixtures,verified_results,rating_at,
 candidate_matches,VERIFIED_KICKOFFS,MODEL_VERSION,assess_oct20)

class TestUCLForward(unittest.TestCase):
 def test_only_known_uefa_fixtures_and_results(self):
  fixture=fixtures()
  a=verified_results(fixture)
  self.assertEqual(len(fixture),144)
  self.assertEqual(len(a),54) # MD1:18, MD2:18, Oct20:9, Oct21:9
  self.assertEqual(a[("2026-10-20","PSG","Barcelona")],(4,2))
  self.assertEqual(a[("2026-10-21","Como","Manchester United")],(4,1))
 def test_tuesday_results_never_leak_into_same_day_picks(self):
  fixture=fixtures()
  a=verified_results(fixture)
  first=rating_at(fixture,a,before="2026-10-20")
  from copy import deepcopy
  changed=deepcopy(a)
  changed[("2026-10-20","PSG","Barcelona")]=(0,22)
  self.assertEqual(first,rating_at(fixture,changed,before="2026-10-20"))
  self.assertNotEqual(rating_at(fixture,a,before="2026-10-21"),
                      rating_at(fixture,changed,before="2026-10-21"))
 def test_today_fixtures_have_verified_utc_kickoff(self):
  fixture=fixtures()
  now=datetime(2026,10,21,13,30,tzinfo=timezone.utc)
  valid=[m for m,cutoff,has_clock in candidate_matches(fixture,now=now)
         if m["date"]=="2026-10-21"]
  self.assertEqual(len(valid),9)
  self.assertEqual(len(VERIFIED_KICKOFFS),9)
 def test_no_fabricated_day_of_future_kickoff(self):
  fixture=fixtures()
  now=datetime(2026,11,3,8,0,tzinfo=timezone.utc)
  selected=[m for m,c,v in candidate_matches(fixture,now=now) if m["date"]=="2026-11-03"]
  self.assertEqual(len(selected),0)
 def test_genuine_published_day_three(self):
  r=assess_oct20()
  self.assertEqual((r["matches"],r["correct"],r["draw_picks"],r["actual_draws"]),(9,6,0,2))
  self.assertEqual(r["modal_exact_correct"],0)
if __name__=="__main__":unittest.main()
