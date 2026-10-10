"""Offline private persistence and tamper safeguards."""
import copy
import json
import sqlite3
import tempfile
from pathlib import Path
import unittest
from engine.private_history import decode_wrangler_result, export_sql, verified_row
from engine.provider365 import parse_game


def row():
    game = {"game": {"id": "4732693", "statusText": "Ended", "startTimeUTC": "2026-10-09T20:00:00Z",
        "competition": {"id": 500, "name": "Serie A", "countryName": "Italy"},
        "homeCompetitor": {"id": 111, "name": "AS Roma", "score":1},
        "awayCompetitor": {"id": 224, "name": "Inter Milan", "score":2},
        "chartEvents": {"events": [{"xg":"0.1", "competitorNum":1}, {"xg":"0.2", "competitorNum":2}]}}}
    return parse_game(game, 'it.1', expected_team_id='224')


class PrivateHistoryTests(unittest.TestCase):
    def test_roundtrip_private_sql(self):
        r=row()
        with tempfile.TemporaryDirectory() as td:
            sql=Path(td)/'secret.sql'
            self.assertEqual(export_sql([r],sql),1)
            conn=sqlite3.connect(':memory:')
            conn.execute('CREATE TABLE private_shot_history (id TEXT PRIMARY KEY, payload TEXT NOT NULL)')
            conn.executescript(sql.read_text())
            conn.executescript(sql.read_text())  # idempotent
            rows=conn.execute('SELECT payload FROM private_shot_history').fetchall()
            self.assertEqual(len(rows),1)
            restored=decode_wrangler_result([{'success':True,'results':[{'payload':rows[0][0]}]}])
            self.assertEqual(restored[0],r)

    def test_empty_remote_result_valid(self):
        self.assertEqual(decode_wrangler_result([{'success':True,'results':[]}]),[])

    def test_fail_closed_on_invalid_remote_result(self):
        for result in ({'error':'unauthorized'}, [], [{'results':[]}], [{'success':False,'results':[]}]):
            with self.subTest(result=result):
                with self.assertRaises(ValueError):decode_wrangler_result(result)

    def test_reject_corrupted_match(self):
        for k,v in (('home_xgq',3),('hg',-2),('source','Unknown'),('source_match_id','invalid'),('id','fake')):
            item=copy.deepcopy(row());item[k]=v
            with self.subTest(field=k):
                with self.assertRaises(ValueError):verified_row(item)


if __name__=='__main__':unittest.main()
