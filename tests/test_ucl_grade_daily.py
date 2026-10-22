"""New UEFA day-result source can score only pre-kickoff truly frozen picks."""
import json,unittest
from datetime import datetime,timezone
from research.ucl_forward import grade, fixtures
class FakeD1:
 def __init__(self):
  m=[x for x in fixtures() if x["date"]=="2026-10-21"][0]
  self.m=m
  self.frozen={
      "id":"ucl.1|"+m["date"]+"|"+m["home"]+"|"+m["away"],
      "date":m["date"],"home":m["home"],"away":m["away"],
      "deadline_utc":"2026-10-21T16:45:00+00:00",
      "frozen_at_utc":"2026-10-21T13:40:00+00:00",
      "models":{"ucl_pot_dc_goals":{"home":.6,"draw":.2,"away":.2}},
      "picks":{"ucl_pot_dc_goals":"home"}}
  self.results=[{"date":m["date"],"home":m["home"],"away":m["away"],
                 "hg":4,"ag":1,"competition":"uefa.cl","status":"certified_final"}]
  self.grades=[]
 def query(self,sql,params=()):
  if sql.startswith("CREATE TABLE"):return []
  if "SELECT id,payload FROM private_ucl_forward_forecasts_2026_27" in sql:
   return [{"id":self.frozen["id"],"payload":json.dumps(self.frozen)}]
  if "SELECT id,payload FROM private_ucl_forward_grades_2026_27" in sql:
   return [{"id":str(i),"payload":json.dumps(x)} for i,x in enumerate(self.grades)]
  if "SELECT payload FROM private_ucl_confirmed_finals_2026_27" in sql:
   return [{"payload":json.dumps(x)} for x in self.results]
  if sql.startswith("INSERT OR IGNORE INTO private_ucl_forward_grades_2026_27"):
   self.grades.append(json.loads(params[1]))
   return []
  raise AssertionError(sql)
class Grading(unittest.TestCase):
 def test_grade_real_saved_pick_from_later_verified_result(self):
  db=FakeD1()
  value=grade(db,now=datetime(2026,10,22,12,tzinfo=timezone.utc))
  self.assertEqual(value["newly_graded"],1)
  self.assertTrue(db.grades[0]["models"]["ucl_pot_dc_goals"]["correct"])
  self.assertIn("UEFA-verified",db.grades[0]["grade_source"])
 def test_pre_kickoff_integrity_protected(self):
  db=FakeD1()
  db.frozen["frozen_at_utc"]="2026-10-21T17:00:00+00:00"
  with self.assertRaises(ValueError):
   grade(db,now=datetime(2026,10,22,12,tzinfo=timezone.utc))
 def test_conflicting_postprocessed_score_fails_closed(self):
  db=FakeD1()
  db.results[0]["competition"]="premier.league"
  with self.assertRaises(ValueError):
   grade(db,now=datetime(2026,10,22,12,tzinfo=timezone.utc))
if __name__=="__main__":unittest.main()
