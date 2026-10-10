"""Offline contract tests: no contact with Understat or use of unlicensed data."""
from __future__ import annotations
import json
from datetime import date
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from engine.provider_understat import (SOURCE, AccessDenied, collect, enabled, fetch,
                                       match_index, parse_match, read_leagues)
from engine.understat_private import verified_row, decode, export
from engine.team_form import team_profiles, select_history_for_fixture


def index_payload(mid='32122', day='2026-10-02', league='EPL'):
    return {'dates': [{'id': mid, 'isResult': True, 'datetime':day+' 18:00:00',
                       'h': {'id':'35', 'title':'Manchester United'},
                       'a': {'id':'43', 'title':'Liverpool'},
                       'goals': {'h':'1', 'a':'2'}},
                      {'id':'32123', 'isResult':False, 'datetime':'2026-11-01 18:00:00',
                       'h': {'id':'35','title':'Manchester United'},
                       'a': {'id':'43','title':'Liverpool'},
                       'goals': {'h':None,'a':None}}]}


def detail_payload(mid='32122'):
    return {'shots': {'h':[{'match_id':mid,'h_a':'h','xG':'0.18','result':'Goal'},
                           {'match_id':mid,'h_a':'h','xG':'0.06','result':'MissedShots'}],
                      'a':[{'match_id':mid,'h_a':'a','xG':'0.24','result':'Goal'},
                           {'match_id':mid,'h_a':'a','xG':'0.08','result':'Goal'}]}}


class UnderstatProviderTests(unittest.TestCase):
    def setUp(self):
        self.match = match_index(index_payload(),'en.1',2026,today=date(2026,10,10))[0]

    def test_league_index_only_finals(self):
        self.assertEqual(len(match_index(index_payload(), 'en.1',2026,today=date(2026,10,10))),1)
        self.assertEqual((self.match['hg'],self.match['ag']),(1,2))

    def test_shot_xgq_true_individual_not_aggregates(self):
        row=parse_match(self.match,detail_payload())
        self.assertEqual(row['source'],SOURCE)
        self.assertEqual((row['home_shots'],row['away_shots']),(2,2))
        self.assertAlmostEqual(row['home_xgq'],(.18**2+.06**2)/2,places=8)
        self.assertEqual(row['source_match_id'],'32122')

    def test_strict_wrong_side_cross_match_and_empty_shots(self):
        for key,value in [('h_a','a'),('match_id','9999'),('xG','nan'),('xG','1.2'),('xG',None)]:
            p=detail_payload();p['shots']['h'][0][key]=value
            with self.subTest(key=key,value=value),self.assertRaises(ValueError):parse_match(self.match,p)
        p=detail_payload();p['shots']['h']=[]
        with self.assertRaises(ValueError):parse_match(self.match,p)

    def test_no_final_without_score_and_bad_team(self):
        p=index_payload();p['dates'][0]['goals']['a']=None
        with self.assertRaises(ValueError):match_index(p,'en.1',2026)
        p=index_payload();p['dates'][0]['a']['title']='Manchester United'
        with self.assertRaises(ValueError):match_index(p,'en.1',2026)

    def test_fetch_only_explicit_endpoints_and_opt_in(self):
        self.assertFalse(enabled({}))
        self.assertFalse(enabled({'XGQ_UNDERSTAT_ACCESS_AUTHORIZED':'1'}))
        self.assertTrue(enabled({'XGQ_UNDERSTAT_ACCESS_AUTHORIZED':'1','XGQ_UNDERSTAT_STORAGE_AUTHORIZED':'1'}))
        self.assertEqual(read_leagues('en.1,it.1'), ['en.1','it.1'])
        with self.assertRaises(ValueError):read_leagues('en.1,en.1')
        with self.assertRaises(ValueError):fetch('match','../../etc',transport=lambda _: {})
        with self.assertRaises(ValueError):fetch('league',('no.1',2026),transport=lambda _: {})

    def test_collector_with_mock_no_network(self):
        urls=[]
        def transport(url):
            urls.append(url)
            return index_payload() if '/getLeagueData/' in url else detail_payload()
        out,state=collect([],['en.1'],[2026],max_new=3,today=date(2026,10,10),transport=transport)
        self.assertEqual(len(out),1)
        self.assertEqual((state['inspected'],state['added']), (1,1))
        self.assertEqual(len(urls),2)
        out2,state2=collect(out,['en.1'],[2026],max_new=3,today=date(2026,10,10),transport=transport)
        self.assertEqual(state2['added'],0)
        self.assertEqual(len(out2),1)

    def test_balanced_fetch_budget_across_leagues(self):
        def index(mid, league):
            return {'dates': [{**index_payload(mid=str(mid+i), day=f'2026-10-{2+i:02d}')['dates'][0]}
                              for i in range(3)]}
        def transport(url):
            from urllib.parse import urlparse
            path=urlparse(url).path
            if 'getLeagueData/EPL/' in path:
                return index(20001, 'en.1')
            if 'getLeagueData/Serie_A/' in path:
                return index(30001, 'it.1')
            return detail_payload(mid=path.rsplit('/',1)[-1])
        rows, health=collect([], ['en.1','it.1'], [2026], max_new=4,
                             today=date(2026,10,10), transport=transport)
        self.assertEqual(health['selected_by_league'], {'en.1':2,'it.1':2})
        self.assertEqual(len(rows),4)
        self.assertEqual({r['league'] for r in rows}, {'en.1','it.1'})

    def test_real_transport_decodes_gzip_safely(self):
        from unittest.mock import patch
        import gzip
        from engine.provider_understat import fetch
        class Resp:
            def __init__(self, b): self.b=b
            def __enter__(self): return self
            def __exit__(self, *_): return False
            def read(self, n): return self.b[:n]
        compressed = gzip.compress(json.dumps({'dates': []}).encode())
        with patch('engine.provider_understat.urlopen', return_value=Resp(compressed)):
            self.assertEqual(fetch('league', ('en.1',2026)), {'dates': []})
        with patch('engine.provider_understat.urlopen', return_value=Resp(gzip.compress(b'X'*6_000_001))):
            with self.assertRaisesRegex(ValueError, 'decoded response too large'):
                fetch('league', ('en.1',2026))

    def test_private_d1_roundtrip(self):
        row=parse_match(self.match,detail_payload())
        with tempfile.TemporaryDirectory() as td:
            file=Path(td)/'persist.sql'
            self.assertEqual(export([row],file),1)
            conn=sqlite3.connect(':memory:')
            conn.execute('CREATE TABLE private_understat_history(id TEXT PRIMARY KEY, payload TEXT NOT NULL)')
            conn.executescript(file.read_text())
            conn.executescript(file.read_text())
            result=conn.execute('SELECT payload FROM private_understat_history').fetchone()[0]
            self.assertEqual(decode([{'success':True,'results':[{'payload':result}]}]),[row])
        with self.assertRaises(ValueError):decode([{'success':False,'results':[]}])
        row['source']='StatsBomb Open Data'
        with self.assertRaises(ValueError):verified_row(row)

    def test_private_form_windows_and_no_future(self):
        match=parse_match(self.match,detail_payload())
        profiles=team_profiles([match],as_of='2026-10-10',source=SOURCE)
        self.assertEqual(len(profiles),2)
        m=next(x for x in profiles if x['team']=='manchester united')
        self.assertEqual(m['windows']['5']['wins'],0)
        self.assertEqual(m['windows']['5']['shots_for'],2)
        self.assertEqual(team_profiles([match],as_of='2026-10-02',source=SOURCE),[])

    def test_source_homogeneity(self):
        r=parse_match(self.match,detail_payload())
        baseline={**r,'source':'StatsBomb Open Data','date':'2024-05-17'}
        fixtures={'league':'en.1','date':'2026-10-11','home_team':'Manchester United','away_team':'Liverpool'}
        rows,src=select_history_for_fixture([baseline,r],fixtures,'2026-10-10')
        self.assertEqual(src,SOURCE)
        self.assertTrue(all(v['source']==SOURCE for v in rows))


if __name__=='__main__':unittest.main()

class UnderstatPipelineTests(unittest.TestCase):
    def test_fail_closed_when_unconfigured_rights(self):
        from engine.understat_pipeline import run
        self.assertEqual(run([], env={})[1], {'enabled': False})
        with self.assertRaises(PermissionError):
            run([], env={'XGQ_UNDERSTAT_LEAGUES':'en.1'})

    def test_no_restore_refuses_recollect(self):
        from engine.understat_pipeline import run
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(RuntimeError):
                run([], env={'XGQ_UNDERSTAT_LEAGUES':'en.1',
                             'XGQ_UNDERSTAT_ACCESS_AUTHORIZED':'1',
                             'XGQ_UNDERSTAT_STORAGE_AUTHORIZED':'1'},
                    private_path=Path(td)/'missing.json', asof=date(2026,10,10))

    def test_pipeline_restores_fetches_and_generates_rolling_profiles(self):
        from engine.understat_pipeline import run
        from engine.understat_private import export_form
        with tempfile.TemporaryDirectory() as td:
            cache=Path(td)/'private.json';cache.write_text('[]')
            def transport(u):return index_payload() if '/getLeagueData/' in u else detail_payload()
            env={'XGQ_UNDERSTAT_LEAGUES':'en.1',
                 'XGQ_UNDERSTAT_ACCESS_AUTHORIZED':'1',
                 'XGQ_UNDERSTAT_STORAGE_AUTHORIZED':'1',
                 'XGQ_UNDERSTAT_MAX_NEW':'3'}
            rows,state=run([],env=env,asof=date(2026,10,10),private_path=cache,transport=transport)
            self.assertEqual(state['added'],1)
            self.assertEqual(state['private_rows'],1)
            conn=sqlite3.connect(':memory:')
            conn.execute('CREATE TABLE private_understat_form(id TEXT PRIMARY KEY,payload TEXT NOT NULL)')
            path=Path(td)/'form.sql'
            self.assertEqual(export_form(rows,path,as_of='2026-10-10'),2)
            conn.executescript(path.read_text())
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM private_understat_form').fetchone()[0],2)
