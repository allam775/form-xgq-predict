"""Synthetic, entirely offline, guard-railed hybrid model tests."""
import unittest
from datetime import date, timedelta
from engine.xgq import strict_row
from engine.provider_understat import SOURCE
from engine.understat_hybrid import hybrid_probs, shot_rates, HYBRID_CANDIDATES
from engine.understat_championship import evaluate


def cohort(n=140):
    teams=['Home Team','Away Team','Middle Team','Other Team','Fifth Team','Sixth Team']
    base=date(2025,4,1)
    rows=[]
    for i in range(n):
        home=teams[i%6]
        away=teams[(i+1+(i//6)%4)%6]
        if home==away: away=teams[(i+2)%6]
        rows.append(strict_row({'date':(base+timedelta(days=i)).isoformat(),
            'league':'en.1','home_team':home,'away_team':away,
            'home_goals':(i*3)%4,'away_goals':(i*7)%3,
            'home_shots_xg':[.1,.2,.15],
            'away_shots_xg':[.07,.12,.15,.06],
            'source':SOURCE,'source_match_id':str(400000+i)}))
    return rows

class HybridTests(unittest.TestCase):
    def setUp(self):
        self.rows=cohort()
        self.fixture={'date':'2025-09-01','league':'en.1','h':'home team','a':'away team'}
        self.dc={'home':.45,'draw':.27,'away':.28}

    def test_candidates_and_probability_simplex(self):
        self.assertEqual(HYBRID_CANDIDATES[0],(0.,0.))
        for params in HYBRID_CANDIDATES:
            p=hybrid_probs(self.rows,self.fixture,self.dc,params)
            self.assertIsNotNone(p)
            self.assertAlmostEqual(sum(p.values()),1,places=9)
            self.assertTrue(all(0 <= x <=1 for x in p.values()))

    def test_future_matches_cannot_change_past_prediction(self):
        baseline=hybrid_probs(self.rows,self.fixture,self.dc,(.35,.30))
        # Tamper with future and same-day outcomes and shot quality.
        modified=[dict(row) for row in self.rows]
        for row in modified:
            if row['date']>=self.fixture['date']:
                row.update(home_xg=100,away_xg=100,home_xgq=1,away_xgq=1,hg=30,ag=0)
        self.assertEqual(baseline,hybrid_probs(modified,self.fixture,self.dc,(.35,.30)))

    def test_opponent_and_shot_evidence_matters(self):
        first=shot_rates(self.rows,self.fixture,xgq_strength=.3)
        mutated=[dict(row) for row in self.rows]
        for row in mutated:
            if row['date']<self.fixture['date'] and row['h']=='home team':
                row['home_xg']=min(3.0,row['home_xg']*2)
        changed=shot_rates(mutated,self.fixture,xgq_strength=.3)
        self.assertNotEqual(first,changed)

    def test_goal_only_is_reproducible_without_shot_data(self):
        p=hybrid_probs([],self.fixture,self.dc,(0.,0.))
        self.assertEqual(p,self.dc)
        self.assertIsNone(hybrid_probs([],self.fixture,self.dc,(.2,.3)))

    def test_rejects_cross_source_and_invalid_weights(self):
        wrong=[{**r,'source':'StatsBomb Open Data'} for r in self.rows]
        self.assertIsNone(shot_rates(wrong,self.fixture))
        for params in ((-1,.3),(1.1,.3),(.5,-1),(.5,1.2),(.5,float('nan'))):
            with self.assertRaises(ValueError):hybrid_probs(self.rows,self.fixture,self.dc,params)

    def test_hybrid_in_championship_research_and_sample_gate(self):
        report=evaluate(cohort(300),min_test=10,min_validation=10)
        self.assertEqual(report['status'],'retrospective',report)
        self.assertIn('hybrid',report['test_scores'])
        self.assertEqual(report['test_scores']['hybrid']['tested'],report['test_scores']['dc_fixed_rho']['tested'])
        self.assertEqual(report['hybrid_adoption_gate']['status'],'research_only_do_not_promote')
        self.assertFalse(report['hybrid_adoption_gate']['heldout_target_met'])

if __name__=='__main__':unittest.main()
