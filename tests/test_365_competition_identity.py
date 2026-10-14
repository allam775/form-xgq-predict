"""Synthetic, offline tests for exact 365Scores competition ID resolver."""
import copy
import unittest
from engine.competition365 import resolve

def payload(cid=572,name="UEFA Champions League",international=True,country=999):
    return {"game":{"id":4732693,"competitionId":cid,
                    "competitionDisplayName":name},
            "competitions":[{"id":cid,"name":name,
                             "countryId":country,"isInternational":international}]}

class CompetitionTests(unittest.TestCase):
    def test_three_leagues_plus_ucl(self):
        for cid,name,lg,international in (
            (572,"UEFA Champions League","uefa.cl",True),
            (73,"Liga Portugal","pt.1",False),
            (78,"Süper Lig","tr.1",False),
            (17,"Serie A","it.1",False),
            (98,"Jupiler Pro League","be.1",False),
            (7,"Premier League","en.1",False),
            (11,"LaLiga","es.1",False)):
            with self.subTest(cid=cid):
                r=resolve(payload(cid,name,international))
                self.assertTrue(r["ok"],r)
                self.assertEqual(r["league"],lg)
                self.assertTrue(r["catalog_verified"])
    def test_country_comma_league_display_as_returned_by_real_provider(self):
        cases=[
            (572,"Europe, UEFA Champions League","UEFA Champions League",True),
            (73,"Portugal, Liga Portugal","Liga Portugal",False),
            (17,"Italy, Serie A","Serie A",False),
            (78,"Turkiye, Super Lig","Super Lig",False),
            (98,"Belgium, Jupiler Pro League","Jupiler Pro League",False),
            (7,"England, Premier League","Premier League",False),
            (11,"Spain, LaLiga","LaLiga",False)]
        for cid,display,catalog_name,is_international in cases:
            with self.subTest(id=cid):
                obj=payload(cid,catalog_name,is_international)
                obj["game"]["competitionDisplayName"]=display
                r=resolve(obj)
                self.assertTrue(r["ok"],r)
                self.assertTrue(r["catalog_verified"])

    def test_wrong_country_comma_league_is_not_accepted(self):
        obj=payload()
        obj["game"]["competitionDisplayName"]="Portugal, UEFA Champions League"
        self.assertEqual(resolve(obj)["reason"],"game_competition_name_disagrees")
        obj=payload(73,"Liga Portugal",False)
        obj["game"]["competitionDisplayName"]="Europe, Liga Portugal"
        self.assertEqual(resolve(obj)["reason"],"game_competition_name_disagrees")

    def test_missing_game_display_can_use_same_response_catalog(self):
        x=payload()
        del x["game"]["competitionDisplayName"]
        self.assertTrue(resolve(x)["ok"])
    def test_missing_catalog_can_use_explicit_game_display(self):
        x=payload()
        del x["competitions"]
        r=resolve(x)
        self.assertTrue(r["ok"])
        self.assertFalse(r["catalog_verified"])
    def test_only_numeric_id_not_enough_without_catalog(self):
        x=payload()
        del x["competitions"]
        del x["game"]["competitionDisplayName"]
        self.assertFalse(resolve(x)["ok"])
    def test_unknown_competition_disallowed(self):
        self.assertEqual(resolve(payload(999,"Super Lig",False))["reason"],"unknown_competition_id")
    def test_conflicting_catalog_rejected(self):
        x=payload()
        x["competitions"][0]["name"]="Europa League"
        self.assertEqual(resolve(x)["reason"],"catalog_name_disagrees")
    def test_conflicting_game_display_rejected(self):
        x=payload()
        x["game"]["competitionDisplayName"]="Europa League"
        self.assertEqual(resolve(x)["reason"],"game_competition_name_disagrees")
    def test_wrong_international_type_rejected(self):
        x=payload()
        x["competitions"][0]["isInternational"]=False
        self.assertEqual(resolve(x)["reason"],"international_type_disagrees")
    def test_missing_country_id_rejected(self):
        x=payload(country=None)
        self.assertEqual(resolve(x)["reason"],"catalog_country_identity_missing")
    def test_missing_or_duplicate_same_id_rejected(self):
        x=payload(); x["competitions"][0]["id"]=888
        self.assertEqual(resolve(x)["reason"],"catalog_id_missing_or_duplicate")
        x=payload();x["competitions"].append(x["competitions"][0].copy())
        self.assertEqual(resolve(x)["reason"],"catalog_id_missing_or_duplicate")
    def test_cross_league_wrong_for_expected(self):
        self.assertEqual(resolve(payload(),expected_leagues={"it.1"})["reason"],"competition_not_requested")
    def test_bool_id_is_not_accepted(self):
        x=payload()
        x["game"]["competitionId"]=True
        self.assertEqual(resolve(x)["reason"],"unknown_competition_id")
    def test_catalog_long_name_accepted(self):
        x=payload()
        x["competitions"][0]["name"]="Champions League"
        x["competitions"][0]["longName"]="UEFA Champions League"
        self.assertTrue(resolve(x)["ok"])
if __name__=="__main__":unittest.main()
