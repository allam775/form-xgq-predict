"""All offline, fully synthetic 365Scores Europe shot-completeness tests."""
import copy
import unittest
from engine.penniless_365_pilot import audit_game,UnverifiedMatch,PILOT_COMPETITIONS


def fake_payload(name="UEFA Champions League", country="Europe"):
 return {"game":{
  "id":4732693,"statusText":"Finished","startTimeUTC":"2025-09-18T19:00:00Z",
  "competition":{"name":name,"countryName":country,"id":572},
  "homeCompetitor":{"id":101,"name":"Club Brugge","score":2},
  "awayCompetitor":{"id":202,"name":"AS Monaco","score":1},
  "chartEvents":{"events":[
   {"xg":"0.15","competitorNum":1,"type":0},
   {"xg":"0.25","competitorNum":1,"type":0},
   {"xg":"0.10","competitorNum":2,"type":0},
   {"xg":"0.30","competitorNum":2,"type":0},
   {"type":"Foul","teamId":101}
  ]}
 }}


def fake_witness():
 return {
  "match_id":"4732693",
  "source_url":"https://www.365scores.com/football/match/uefa-champions-league-572/example-123",
  "verified_date":"2026-10-13","time_scope":"90m",
  "home_shots":2,"away_shots":2,"home_xg":0.40,"away_xg":0.40,
  "shot_xg_decimals":2,"aggregate_xg_decimals":2
 }


class EuropeanPilotTests(unittest.TestCase):
 def test_no_network_or_secrets_in_new_pilot_code(self):
  import inspect,engine.penniless_365_pilot as p
  code=inspect.getsource(p)
  self.assertNotIn("urlopen(",code)
  self.assertNotIn("requests.get(",code)
  self.assertNotIn("fetch(",code)
  self.assertNotIn("write_text(",code)
  self.assertEqual(len(PILOT_COMPETITIONS),8)

 def test_exact_xgq_and_real_two_team_counts(self):
  r=audit_game(fake_payload(),"uefa.cl",fake_witness(),expected_team_id="101")
  self.assertEqual((r['home_shots'],r['away_shots']),(2,2))
  self.assertAlmostEqual(r['home_xgq'],(.15**2+.25**2)/2,places=8)
  self.assertAlmostEqual(r['away_xgq'],(.10**2+.30**2)/2,places=8)
  self.assertFalse(r["public_release_permitted"])
  self.assertNotIn("events",r)
  self.assertNotIn("shot_xgs",r)

 def test_five_named_european_leagues_are_identified_by_country(self):
  samples={
   'pt.1':('Liga Portugal','Portugal'),
   'tr.1':('Süper Lig','Türkiye'),
   'nl.1':('Eredivisie','Netherlands'),
   'be.1':('Jupiler Pro League','Belgium'),
   'no.1':('Eliteserien','Norway'),
   'at.1':('Austrian Bundesliga','Austria'),
   'gr.1':('Super League Greece','Greece')
  }
  for league,(name,country) in samples.items():
   with self.subTest(league=league):
    r=audit_game(fake_payload(name,country),league,fake_witness())
    self.assertEqual(r["league"],league)

 def test_unverified_competition_or_wrong_country_fails(self):
  for name,country in [('Champions League','Brazil'),
                       ('Europa League','Europe'),('League Cup','Europe'),
                       ('Süper Lig','Greece')]:
   with self.subTest(name=name,country=country):
    with self.assertRaisesRegex(UnverifiedMatch,'Wrong competition'):
     audit_game(fake_payload(name,country),"uefa.cl",fake_witness())

 def test_missing_shot_fails_instead_of_silently_inventing_average_xg(self):
  x=fake_payload()
  del x["game"]["chartEvents"]["events"][0]["xg"]
  with self.assertRaisesRegex(UnverifiedMatch,'shots !='):
   audit_game(x,"uefa.cl",fake_witness())

 def test_malformed_shot_xg_fails(self):
  x=fake_payload()
  x["game"]["chartEvents"]["events"][0]["xg"]="NaN"
  with self.assertRaisesRegex(UnverifiedMatch,'missing a valid individual'):
   audit_game(x,"uefa.cl",fake_witness())

 def test_missing_one_event_fails_even_if_other_events_valid(self):
  x=fake_payload()
  x["game"]["chartEvents"]["events"].pop(1)
  with self.assertRaisesRegex(UnverifiedMatch,'chart shots !='):
   audit_game(x,"uefa.cl",fake_witness())

 def test_provider_sum_does_not_match_fails_even_when_count_correct(self):
  w=fake_witness();w["home_xg"]=0.80
  with self.assertRaisesRegex(UnverifiedMatch,'does not reconcile'):
   audit_game(fake_payload(),"uefa.cl",w)

 def test_published_totals_are_not_optional(self):
  for k in ("away_xg","home_shots","time_scope","shot_xg_decimals"):
   w=fake_witness();del w[k]
   with self.subTest(k=k):
    with self.assertRaises(UnverifiedMatch):
     audit_game(fake_payload(),"uefa.cl",w)

 def test_wrong_or_missing_90minute_scope_fails(self):
  for scope in ("full_match","120m",None):
   w=fake_witness();w["time_scope"]=scope
   with self.assertRaises(UnverifiedMatch):
    audit_game(fake_payload(),"uefa.cl",w)

 def test_wrong_fixture_id_or_team_fails(self):
  w=fake_witness();w["match_id"]="999"
  with self.assertRaisesRegex(UnverifiedMatch,'match identity'):
   audit_game(fake_payload(),"uefa.cl",w)
  with self.assertRaisesRegex(UnverifiedMatch,'Requested team'):
   audit_game(fake_payload(),"uefa.cl",fake_witness(),expected_team_id="999")

 def test_source_link_must_be_365_url_without_fake_authorization(self):
  w=fake_witness();w["source_url"]="https://example.com/football/match/1"
  with self.assertRaisesRegex(UnverifiedMatch,'Invalid provider match-source'):
   audit_game(fake_payload(),"uefa.cl",w)

 def test_final_score_required(self):
  x=fake_payload();x["game"]["statusText"]="Not Started"
  with self.assertRaisesRegex(UnverifiedMatch,'completed'):
   audit_game(x,"uefa.cl",fake_witness())

 def test_reject_wrong_side_attribution(self):
  x=fake_payload();x["game"]["chartEvents"]["events"][0].pop("competitorNum")
  with self.assertRaisesRegex(UnverifiedMatch,'authenticated team'):
   audit_game(x,"uefa.cl",fake_witness())

 def test_rounding_tolerance_bounded_by_number_of_individual_shots(self):
  w=fake_witness();w["home_xg"]=.414 # n=2, +/- .01 from per-shot rounding and +/-.005 from aggregate
  audit_game(fake_payload(),"uefa.cl",w)
  w["home_xg"]=.42
  with self.assertRaisesRegex(UnverifiedMatch,'does not reconcile'):
   audit_game(fake_payload(),"uefa.cl",w)


if __name__=="__main__":
 unittest.main()
