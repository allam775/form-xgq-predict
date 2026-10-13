"""Offline tests for bounded mixed-source Penniless XGQ sampling."""
from __future__ import annotations
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlparse,parse_qs
from research import penniless_multisource_samples as p


class SampleMatrixTests(unittest.TestCase):
    def test_allowlisted_public_urls_only(self):
        with self.assertRaises(ValueError):
            p.get("http://raw.githubusercontent.com/hudl/open-data")
        with self.assertRaises(ValueError):
            p.get("https://example.com/api/raw")
        self.assertEqual(p.MAX_READ,15000000)

    def test_known_team_lookup_is_bounded_and_no_bruteforce(self):
        requests=[]
        def transport(url):
            parsed=urlparse(url)
            params=parse_qs(parsed.query)
            requests.append((parsed.path,params))
            if parsed.path.endswith("games/results/"):
                self.assertEqual(params["competitors"],["224"])
                return {"games":[
                   {"gameId":"4732693","homeCompetitor":{"id":111},"awayCompetitor":{"id":224}},
                   {"gameId":"4732694","homeCompetitor":{"id":224},"awayCompetitor":{"id":222}},
                   {"gameId":"4732695","homeCompetitor":{"id":224},"awayCompetitor":{"id":223}},
                   {"gameId":"4732696","homeCompetitor":{"id":224},"awayCompetitor":{"id":225}},
                   {"gameId":"4732697","homeCompetitor":{"id":224},"awayCompetitor":{"id":226}},
                   {"gameId":"4732698","homeCompetitor":{"id":991},"awayCompetitor":{"id":992}},
                ]}
            return {"game":{
              "id":int(params["gameId"][0]),"statusText":"Ended",
              "homeCompetitor":{"id":111,"name":"Roma"},
              "awayCompetitor":{"id":224,"name":"Inter"},
              "chartEvents":{"events":[
                 {"xg":"0.25","competitorNum":1},
                 {"xg":"0.14","competitorNum":2} ]}}}
        x=p.run_365(transport=transport,limit=4,sleep=0)
        self.assertEqual(x["status"],"candidate_samples_inspected")
        self.assertEqual(x["queries_made"],5)
        self.assertEqual(len(x["details"]),4)
        self.assertEqual(x["accepted_complete_xgq"],0)
        self.assertTrue(all(z["accepted_complete_xgq"] is False
                            for z in x["details"]))
        self.assertEqual(len(requests),5)
        self.assertEqual(sum("game/" in x[0] for x in requests),4)
        self.assertNotIn("raw_payload",str(x))

    def test_missing_screenshot_score_rejected_for_completeness_but_no_crash(self):
        game={"game":{"id":"4732693","statusText":"Finished",
           "homeCompetitor":{"id":111},"awayCompetitor":{"id":224},
           "chartEvents":{"events":[
              {"xg":"0.20","competitorNum":1},
              {"xg":"0.20","competitorNum":2}]}}}
        z=p._shot_diagnostics(game,"4732693")
        self.assertEqual(z["shot_events"],2)
        self.assertFalse(z["score_present"])
        self.assertFalse(z["accepted_complete_xgq"])
        self.assertEqual(z["status"],"missing_competition_identity")

    def test_missing_xg_detected_no_fabricated_shot_series(self):
        game={"game":{"id":"4732693","statusText":"Finished",
           "homeCompetitor":{"id":111},"awayCompetitor":{"id":224},
           "chartEvents":{"events":[
               {"xg":"NaN","competitorNum":1},
               {"xg":"0.40","competitorNum":2}]}}}
        z=p._shot_diagnostics(game,"4732693")
        self.assertEqual(z["status"],"missing_individual_shot_xg")
        self.assertEqual(z["shots_missing_xg"],1)
        self.assertEqual(z["accepted_complete_xgq"],False)

    def test_integral_float_scores_and_provider_catalog_match(self):
        game={"game":{"id":"4732693","statusText":"Finished",
           "competitionId":572,"competitionDisplayName":"UEFA Champions League",
           "homeCompetitor":{"id":111,"score":2.0},
           "awayCompetitor":{"id":224,"score":1.0},
           "chartEvents":{"events":[
               {"xg":"0.25","competitorNum":1},
               {"xg":"0.45","competitorNum":2}]}},
           "competitions":[{"id":572,"name":"UEFA Champions League",
                            "countryId":999,"isInternational":True}]}
        z=p._shot_diagnostics(game,"4732693")
        self.assertEqual(z["status"],"partial_unverified")
        self.assertTrue(z["score_present"])
        self.assertTrue(z["competition_catalog_identity_confirmed"])
        self.assertFalse(z["accepted_complete_xgq"])
        game["game"]["homeCompetitor"]["score"]=2.5
        z=p._shot_diagnostics(game,"4732693")
        self.assertFalse(z["score_present"])

    def test_source_reports_are_sanitized_before_written_in_public(self):
        report_data={"status":"candidate_samples_inspected",
           "queries_made":2,"details":[{"status":"missing_competition_identity",
               "home_shots_detected":18,"away_shots_detected":16}],
           "accepted_complete_xgq":0}
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(p,"OUT",Path(folder)/"out.json"), \
             patch.object(p,"run_365",return_value=report_data), \
             patch.object(p,"run_understat",return_value={"status":"existing_private_shot_history","rows_available":123}), \
             patch.object(p,"run_statsbomb",return_value={"status":"sampled_public_shot_events","accepted":2}), \
             patch.object(p,"run_openfootball",return_value={"status":"results_only"}), \
             patch.object(p,"run_football_data",return_value={"status":"results_only"}), \
             patch.object(p,"run_clubelo_catalog",return_value={"status":"metadata_sample_only"}):
            result=p.main()
            disk=Path(folder,"out.json").read_text()
            self.assertNotIn("home_shots_detected",disk)
            self.assertNotIn("away_shots_detected",disk)
            self.assertEqual(result["sources"]["365scores_legacy_authorized_pilot"]["matches_inspected"],1)
            self.assertEqual(result["sources"]["365scores_legacy_authorized_pilot"]["detail_diagnostic_status_counts"]["missing_competition_identity"],1)


if __name__=="__main__":unittest.main()
