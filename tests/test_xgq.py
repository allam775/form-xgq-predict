"""Unit and end-to-end tests use shape-correct *synthetic* data, NEVER published."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from datetime import date,timedelta
from engine.xgq import shot_quality, strict_row, statsbomb_to_row, predict_xgq,holdout_metrics
from engine.collect import make_snapshot,ingest_verified_feed
from engine.sql_export import export
from engine.validate import validate


def history(n=90, offset=0):
    start=date(2025,1,1)
    res=[]
    teams=['Alpha FC','Bravo','Charlie','Delta']
    for i in range(n):
        h=teams[i%4];a=teams[(i+1+(i//4)%2)%4]
        if h==a:a=teams[(i+2)%4]
        res.append(strict_row({'league':'es.1','date':(start+timedelta(days=i*2)).isoformat(),
           'home_team':h,'away_team':a,'home_goals':i%4,'away_goals':i%3,
           'home_shots_xg':[.06,.09+.001*i,.27], 'away_shots_xg':[.04,.15,.19],
           'source':'synthetic-tests-only'}))
    return res

class MathTests(unittest.TestCase):
    def test_exact_xgq_math(self):
        self.assertAlmostEqual(shot_quality([.1,.2,.3])['xgq'],(.01+.04+.09)/3)
    def test_reject_aggregate_only(self):
        with self.assertRaises((ValueError,KeyError)):
            strict_row({'league':'en.1','date':'2026-05-01','home_team':'a','away_team':'b',
                        'home_goals':1,'away_goals':1,'home_xg':2,'away_xg':1})
    def test_reject_invalid_xg(self):
        for shots in ([],[float('nan')],[1.01],[-0.1],[None]):
            with self.subTest(shots=shots), self.assertRaises(ValueError):shot_quality(shots)
    def test_statsbomb_shape(self):
        m={'match_id':5,'match_date':'2025-01-01','home_team':{'home_team_name':'Alpha','home_team_id':11},'away_team':{'away_team_name':'Bravo','away_team_id':12},'home_score':1,'away_score':0}
        events=[{'type':{'name':'Shot'},'team':{'id':11},'shot':{'statsbomb_xg':.2}},
                {'type':{'name':'Shot'},'team':{'id':12},'shot':{'statsbomb_xg':.15}}]
        r=statsbomb_to_row(m,events,'es.1')
        self.assertEqual(r['home_xgq'],.04)
        self.assertEqual(r['source'],'StatsBomb Open Data')
    def test_shot_xg_missing_strictly_rejected(self):
        m={'match_id':5,'match_date':'2025-01-01','home_team':{'home_team_name':'Alpha','home_team_id':11},'away_team':{'away_team_name':'Bravo','away_team_id':12},'home_score':1,'away_score':0}
        with self.assertRaises(ValueError):statsbomb_to_row(m,[{'type':{'name':'Shot'},'team':{'id':11},'shot':{}}],'es.1')

class GateTests(unittest.TestCase):
    def test_live_unverified_old_data_refused(self):
        rows=history(80)
        f={'league':'es.1','date':'2026-10-10','home_team':'Alpha','away_team':'Bravo'}
        forecast, reason=predict_xgq(f,rows,'2026-10-10')
        self.assertIsNone(forecast)
        self.assertEqual(reason,'stale_xgq')
    def test_pre_match_only_and_live_forecast(self):
        rows=history(90)
        asof='2025-07-10'
        fixture={'league':'es.1','date':'2025-07-10','home_team':'Alpha','away_team':'Bravo'}
        p,reason=predict_xgq(fixture,rows,asof,max_stale_days=120)
        self.assertIsNone(reason)
        self.assertEqual(p['source_basis'],'verified_shot_level_xg')
        self.assertAlmostEqual(sum(p['probabilities'][k] for k in ('home','draw','away')),1,places=4)
        mutated=rows+[strict_row({'league':'es.1','date':'2025-07-10','home_team':'Alpha','away_team':'Bravo',
                                    'home_goals':23,'away_goals':0,'home_shots_xg':[1.0],'away_shots_xg':[.01]})]
        p2,_=predict_xgq(fixture,mutated,asof,max_stale_days=120)
        self.assertEqual(p['probabilities'],p2['probabilities'])
    def test_truthful_withholding_and_d1_export(self):
        rows=history(90)
        asof=date(2025,7,10)
        good={'league':'es.1','league_name':'La Liga','date':asof.isoformat(),'home_team':'Alpha','away_team':'Bravo'}
        unsupported={**good,'home_team':'Unknown FC','away_team':'Bravo'}
        snapshot=make_snapshot(rows,[good,unsupported],asof)
        self.assertEqual(len(snapshot['forecasts']),1)
        self.assertEqual(len(snapshot['unavailable']),1)
        self.assertEqual(validate(snapshot),1)
        with TemporaryDirectory() as tmp:
            output=Path(tmp)/'test.sql'
            self.assertEqual(export(snapshot,output),1)
            text=output.read_text()
            self.assertIn('published_generation',text)
            self.assertIn('verified_shot_level_xg',text)
            self.assertNotIn('synthetic-tests-only',text)
    def test_invalid_feed_refused(self):
        with TemporaryDirectory() as tmp:
            source=Path(tmp)/'bad.json'
            source.write_text(json.dumps([{'league':'en.1'}]))
            with self.assertRaises(ValueError):ingest_verified_feed([],source)
    def test_no_fabricated_probabilities(self):
        snapshot=make_snapshot([],[],date(2026,10,10))
        self.assertEqual(snapshot['forecasts'],[])
        self.assertEqual(validate(snapshot),0)
    def test_historical_evaluation_without_coverage_claim(self):
        ev=holdout_metrics(history(25),'2025-07-10')
        self.assertEqual(ev['status'],'insufficient')

if __name__ == '__main__':unittest.main()

class D1GenerationTests(unittest.TestCase):
    def test_published_generation_switch_is_last_sql_statement(self):
        from datetime import datetime,timezone
        from pathlib import Path
        from tempfile import TemporaryDirectory
        import sqlite3
        from engine.sql_export import export
        from engine.collect import ROOT
        rows=history(90)
        snapshot=make_snapshot(rows,[{'league':'es.1','league_name':'La Liga','date':'2025-07-10',
                          'home_team':'Alpha','away_team':'Bravo'}],date(2025,7,10))
        with TemporaryDirectory() as tmp:
            db=sqlite3.connect(':memory:')
            db.executescript((ROOT/'migrations/0001_schema.sql').read_text())
            dest=Path(tmp)/'seed.sql'
            export(snapshot,dest)
            sql=dest.read_text()
            self.assertNotIn('BEGIN TRANSACTION',sql)
            self.assertTrue(sql.strip().endswith(');'))
            db.executescript(sql)
            first_gen=db.execute("SELECT v FROM metadata WHERE k='published_generation'").fetchone()[0]
            self.assertEqual(db.execute('SELECT COUNT(*) FROM forecasts WHERE generation=?',(first_gen,)).fetchone()[0],1)
            # Simulate interruption *before* final publication pointer.
            new={**snapshot,'generated_at':'2025-07-11T00:00:00+00:00', 'forecasts':[],
                 'coverage':{**snapshot['coverage'],'xgq_forecasts':0}}
            export(new,dest)
            sql2=dest.read_text().splitlines()
            db.executescript('\n'.join(sql2[:-1]))
            self.assertEqual(db.execute("SELECT v FROM metadata WHERE k='published_generation'").fetchone()[0],first_gen)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM forecasts WHERE generation=?',(first_gen,)).fetchone()[0],1)
            # Publishing the last statement switches to the complete new generation.
            db.execute(sql2[-1])
            new_gen=db.execute("SELECT v FROM metadata WHERE k='published_generation'").fetchone()[0]
            self.assertEqual(new_gen,new['generated_at'])
            self.assertEqual(db.execute('SELECT COUNT(*) FROM forecasts WHERE generation=?',(new_gen,)).fetchone()[0],0)
            db.close()
