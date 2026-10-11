"""Deterministic, offline backfill and D1 paging tests. No provider/network calls."""
from datetime import date
import json
import unittest
from engine.understat_backfill import validate_config, prioritize, backfill
from engine.understat_d1 import D1, PAGE, D1Error
from engine.provider_understat import SOURCE
from engine.xgq import strict_row


def match(mid, league='en.1', day='2026-10-01'):
    return {'id':str(mid),'league':league,'date':day,'home':'Team A','away':'Team B','hg':1,'ag':1}


def make_row(mid, league='en.1', day='2026-10-01'):
    return strict_row({'league':league,'date':day, 'home_team':f'Home {mid}', 'away_team':f'Away {mid}',
                       'home_goals':1,'away_goals':1,'home_shots_xg':[.1,.3],
                       'away_shots_xg':[.2,.3], 'source':SOURCE,'source_match_id':str(mid)})


class FakeDB:
    def __init__(self,existing=None,target=10000):
        self.rows={r['id']:r for r in (existing or [])}
        self.config={'enabled':True,'owner_confirmed_collection_and_retention':True,
                     'leagues':['en.1','it.1'],'backfill_target':target,
                     'backfill_seasons':[2026]}
        self.form=[];self.progress=[]
    def get_setting(self):return self.config
    def history(self):return list(self.rows.values())
    def upsert_history(self,rows):
        for x in rows:self.rows[x['id']]=x
        return len(rows)
    def upsert_forms(self,profiles):self.form=profiles;return len(profiles)
    def set_progress(self,status):self.progress.append(status)


def fake_index(league):
    return {'dates':[{'id':str(100+i+(1000 if league=='it.1' else 0)),
       'isResult':True,'datetime':f'2026-10-{(i%10)+1:02d} 13:00:00',
       'h':{'id':'123','title':f'{league} Home {i}'},
       'a':{'id':'456','title':f'{league} Away {i}'},
       'goals':{'h':'1','a':'1'}} for i in range(8)]}


def fake_detail(mid):
    return {'shots':{'h':[{'match_id':mid,'h_a':'h','xG':'0.1','result':'Goal'}],
                     'a':[{'match_id':mid,'h_a':'a','xG':'0.2','result':'Goal'}]}}


class BackfillTests(unittest.TestCase):
    def test_missing_rights_or_extra_safety_limits(self):
        for bad in ({},{'enabled':False,'owner_confirmed_collection_and_retention':True},
                    {'enabled':True,'owner_confirmed_collection_and_retention':False}):
            with self.assertRaises(PermissionError):validate_config(bad)
        with self.assertRaises(ValueError):validate_config({'enabled':True,'owner_confirmed_collection_and_retention':True,'leagues':['en.1'],'backfill_target':25000})

    def test_balance_leagues_and_skip_existing(self):
        index={'en.1':[match(110),match(111)],'it.1':[match(210,'it.1'),match(211,'it.1')]}
        chosen=prioritize(index,[make_row(110)],3)
        self.assertEqual(len(chosen),3)
        self.assertNotIn('110',[x['id'] for x in chosen])
        self.assertEqual(sum(x['league']=='it.1' for x in chosen),2)

    def test_private_end_to_end_and_resume_without_download_duplicates(self):
        db=FakeDB(target=6)
        calls=[]
        def source(kind,value):
            calls.append((kind,value))
            return fake_index(value[0]) if kind=='league' else fake_detail(value)
        stats=backfill(db,max_new=4,min_interval=.5,fetcher=source,sleeper=lambda n:None,clock=lambda:5,today=date(2026,10,11))
        self.assertEqual(stats['added'],4)
        self.assertEqual(stats['total'],4)
        self.assertEqual(stats['rejected'],0)
        self.assertEqual(len(db.form),8)
        self.assertEqual(len([c for c in calls if c[0]=='match']),4)
        calls.clear()
        stats2=backfill(db,max_new=4,min_interval=.5,fetcher=source,sleeper=lambda n:None,clock=lambda:5,today=date(2026,10,11))
        self.assertEqual(stats2['total'],6)
        self.assertEqual(stats2['added'],2)
        calls.clear()
        stats3=backfill(db,max_new=4,min_interval=.5,fetcher=source,sleeper=lambda n:None,clock=lambda:5,today=date(2026,10,11))
        self.assertEqual(stats3['status'],'target_reached')
        self.assertEqual(calls,[])

    def test_db_cursor_pagination(self):
        rows=[make_row(1000+i) for i in range(PAGE+10)]
        calls=[]
        def transport(req):
            calls.append(req)
            if req['sql'].startswith('SELECT payload'):
                take,offset=req['params'];result=[{'payload':json.dumps(r)} for r in rows[offset:offset+take]]
            else:result=[]
            return {'success':True,'result':[{'success':True,'results':result}]}
        db=D1(account='3dd5a8e2a5320c9436a14325d881ba07',database='cb920066-08ec-4566-ac19-2afe54c7c7c2',transport=transport)
        data=db.history()
        self.assertEqual(len(data),PAGE+10)
        self.assertEqual([q['params'] for q in calls],[[PAGE,0],[PAGE,PAGE]])

    def test_query_denial_stops_before_publish(self):
        db=D1(account='3dd5a8e2a5320c9436a14325d881ba07',database='cb920066-08ec-4566-ac19-2afe54c7c7c2',transport=lambda _: {'success':False,'result':[]})
        with self.assertRaises(D1Error):db.history()

if __name__=='__main__':unittest.main()
