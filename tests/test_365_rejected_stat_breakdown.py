"""Synthetic categorical comparison of goal/saved/missed/post/blocked shots."""
import importlib
import unittest
m=importlib.import_module("research.365_rejected_stat_breakdown")
def candidate():
    return {"source_match_id":"4732693","home":"Roma","away":"Inter"}
def payload():
    out=[]
    for side,tid in (("home",11),("away",22)):
        vals={"Shots On Target":"3","Shots Off Target":"2","Shots Blocked":"1",
              "Hit Woodwork":"1","Total Shots":"6","Expected Goals":"1.50"}
        for n,v in vals.items():out.append({"competitorId":tid,"name":n,"value":v})
    return {"games":[{"id":4732693}],
      "competitors":[{"name":"Roma","id":11},{"name":"Inter","id":22}],
      "statistics":out}
def aggregates():
    def side():
        return [{"signature":"0|||goal|||||||","count":1},
                {"signature":"0|||saved|||||||","count":2},
                {"signature":"0|||missed|||||||","count":1},
                {"signature":"0|||post|||||||","count":1},
                {"signature":"0|||blocked|||||||","count":1}]
    return {"home":side(),"away":side()}
class Tests(unittest.TestCase):
 def test_independently_split_shot_categories(self):
    x=m.map_breakdown(payload(),candidate(),aggregates())
    self.assertEqual(x["home"]["differences"]["total"],0)
    self.assertEqual(x["home"]["differences"]["off_target"],0)
    self.assertEqual(x["home"]["differences"]["on_target"],0)
    self.assertEqual(x["home"]["differences"]["woodwork"],0)
 def test_detect_one_extra_chart_outcome(self):
    a=aggregates()
    a["away"].append({"signature":"0|||missed|||||||","count":1})
    x=m.map_breakdown(payload(),candidate(),a)
    self.assertEqual(x["away"]["differences"]["total"],-1)
    self.assertEqual(x["away"]["differences"]["off_target"],-1)
 def test_optional_woodwork_missing_is_unknown_not_zero(self):
    x=payload()
    x["statistics"]=[a for a in x["statistics"] if a["name"]!="Hit Woodwork"]
    r=m.map_breakdown(x,candidate(),aggregates())
    self.assertIsNone(r["home"]["stats"]["Hit Woodwork"])
    self.assertIsNone(r["home"]["differences"]["woodwork"])
 def test_reject_missing_independent_category(self):
    x=payload()
    x["statistics"]=[a for a in x["statistics"] if a["name"]!="Shots Blocked"]
    with self.assertRaises(ValueError):
       m.map_breakdown(x,candidate(),aggregates())
if __name__=="__main__":unittest.main()
