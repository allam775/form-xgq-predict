"""Regression checks for immutable 2026-10-11 forward forecasts; all synthetic evidence."""
from datetime import datetime, timedelta, timezone
import json
import unittest

from engine.xgq import strict_row
from engine.provider_understat import SOURCE
from engine.prematch_ledger import (FIXTURES, FIXTURE_DATE, OUTCOMES, create_forward_rows,
                                    fixture_dict, research_52, freeze, grade)

UTC=timezone.utc


def synthetic_history():
    entries=[]
    origin=datetime(2026,7,1,tzinfo=UTC)
    for i in range(65):
        day=(origin+timedelta(days=i)).date().isoformat()
        entries.append(strict_row({'date':day,'league':'it.1','home_team':'Como' if i%2 else 'Roma',
             'away_team':'Roma' if i%2 else 'Como', 'home_goals':i%3,'away_goals':(i+1)%3,
             'home_shots_xg':[.05,.12,.35], 'away_shots_xg':[.05,.1,.3],
             'source':SOURCE,'source_match_id':str(500000+i)}))
    return entries


class FakeD1:
    def __init__(self,history):self.hist=list(history);self.ledger={};self.grades={};self.created=set()
    def history(self):return list(self.hist)
    def query(self,sql,params=()):
        if sql.startswith('CREATE TABLE'):
            self.created.add(sql.split('EXISTS ')[1].split('(')[0]);return []
        if sql.startswith('SELECT id FROM private_prematch_forecasts_20261011'):
            return [{'id':k} for k in self.ledger]
        if sql.startswith('SELECT payload FROM private_prematch_forecasts_20261011'):
            return [{'payload':v} for v in self.ledger.values()]
        if sql.startswith('SELECT COUNT(*)'):
            return [{'n':len(self.ledger)}] if 'forecasts' in sql else [{'n':len(self.grades)}]
        if sql.startswith('INSERT OR IGNORE INTO private_prematch_forecasts_20261011'):
            self.ledger.setdefault(params[0],params[1]);return []
        if sql.startswith('INSERT OR IGNORE INTO private_prematch_grades_20261011'):
            self.grades.setdefault(params[0],params[1]);return []
        raise AssertionError(sql)


class PrematchLedgerTests(unittest.TestCase):
    def test_all_fixture_ids_and_kickoffs_are_distinct_and_utc(self):
        self.assertEqual(len(FIXTURES),17)
        self.assertEqual(len({r[0] for r in FIXTURES}),17)
        for spec in FIXTURES:
            f=fixture_dict(spec)
            self.assertEqual(f['date'],FIXTURE_DATE)
            self.assertEqual(datetime.fromisoformat(f['kickoff_utc']).utcoffset(),timedelta())

    def test_52_rule_is_fixed_prospective_distribution_not_claimed_skill(self):
        result=research_52({'home':.5,'draw':.3,'away':.2},{'home':.3,'draw':.3,'away':.4})
        self.assertAlmostEqual(sum(result.values()),1,places=6)
        self.assertIn(max(OUTCOMES,key=lambda k:result[k]),OUTCOMES)

    def test_missing_history_is_withheld_instead_of_invented(self):
        now=datetime(2026,10,11,4,0,tzinfo=UTC)
        records=create_forward_rows([],now=now)
        self.assertEqual(len(records),17)
        self.assertTrue(all(x['status']=='withheld' for x in records))

    def test_future_match_results_cannot_change_frozen_probabilities(self):
        now=datetime(2026,10,11,4,0,tzinfo=UTC)
        history=synthetic_history()
        a=create_forward_rows(history,now=now)
        como=next(r for r in a if r['home_id']=='como')
        self.assertEqual(como['status'],'frozen')
        poisoned=history+[strict_row({'date':FIXTURE_DATE,'league':'it.1',
                       'home_team':'Como','away_team':'Roma', 'home_goals':10,'away_goals':0,
                       'home_shots_xg':[.6], 'away_shots_xg':[.01],
                       'source':SOURCE, 'source_match_id':'8888888'})]
        b=create_forward_rows(poisoned,now=now)
        self.assertEqual(como['models'],next(x for x in b if x['home_id']=='como')['models'])

    def test_late_creation_never_backdates_forecast(self):
        rows=create_forward_rows(synthetic_history(),now=datetime(2026,10,11,11,0,tzinfo=UTC))
        como=next(r for r in rows if r['home_id']=='como')
        self.assertEqual(como['status'],'missed_pre_kickoff_deadline')
        self.assertNotIn('models',como)

    def test_ledger_immutability_and_verified_final_scoring(self):
        fake=FakeD1(synthetic_history())
        morning=datetime(2026,10,11,4,0,tzinfo=UTC)
        first=freeze(fake,now=morning)
        self.assertEqual(first['saved'],17)
        key=next(k for k,v in fake.ledger.items() if json.loads(v)['home_id']=='como')
        before=fake.ledger[key]
        later=datetime(2026,10,11,12,30,tzinfo=UTC)
        self.assertEqual(freeze(fake,now=later)['status'],'already_frozen')
        self.assertEqual(fake.ledger[key],before)
        self.assertEqual(grade(fake,now=later)['graded'],0)
        done=strict_row({'date':FIXTURE_DATE,'league':'it.1','home_team':'Como','away_team':'Roma',
            'home_goals':2,'away_goals':0,'home_shots_xg':[.2,.3],
            'away_shots_xg':[.05,.15], 'source':SOURCE, 'source_match_id':'8888888'})
        fake.hist.append(done)
        self.assertEqual(grade(fake,now=later)['graded'],1)
        self.assertEqual(grade(fake,now=later)['graded'],1)
        self.assertEqual(fake.ledger[key],before)
        outcome=json.loads(fake.grades[key])
        self.assertEqual(outcome['outcome'],'home')
        self.assertIn('exploratory_52_test_selected',outcome['model_scores'])

if __name__=='__main__':unittest.main()
