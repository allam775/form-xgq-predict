"""Offline, tiny, source-safe research tests; synthetic only."""
import unittest
from engine.understat_accuracy_lab import (families,trial_grid,probabilities,
                                           score_trial,discover,research)

P={'home':.48,'draw':.28,'away':.24}

def entry(day='2026-09-10',outcome='home',p=None):
    v=p or P
    return {'league':'en.1','date':day,'outcome':outcome,
            'xgq':v,'elo':v,'naive':v,'dc_fixed_rho':v,
            'hybrids':{f'{a:.2f}_{b:.2f}':v for a,b in
                       ((0.,0.),(.15,0.),(.30,0.),(.50,0.),(.20,.30),(.35,.30),(.50,.30),(.35,.65))}}

class LabTest(unittest.TestCase):
    def test_probabilities_are_normalized(self):
        x=probabilities(entry(),('dc_fixed_rho','elo',.5),1.1,.9)
        self.assertAlmostEqual(sum(x),1,places=10)
        self.assertGreater(x[0],x[1])

    def test_synthetic_classification(self):
        rows=[entry(outcome='home') for _ in range(4)]
        t=(('dc_fixed_rho',None,0.0),1.0,1.0)
        v=score_trial(rows,t)
        self.assertEqual(v['correct'],4)
        self.assertEqual(v['accuracy'],1.)

    def test_different_test_size_fails_closed(self):
        a=discover([entry() for _ in range(70)],[entry() for _ in range(8)])
        self.assertEqual(a['status'],'sample_changed')
        self.assertNotIn('retrospective_test_scan',a)

    def test_selection_only_uses_validation_data(self):
        # Synthetic n=15, no 393 historical sample here.
        validation=[entry(outcome=('home' if i%2 else 'away')) for i in range(70)]
        test=[entry(outcome='home') for i in range(15)]
        b=[entry(outcome='away') for i in range(15)]
        a=discover(validation,test,expected_test=15)
        z=discover(validation,b,expected_test=15)
        self.assertEqual(a['status'],'exploratory_research_only')
        self.assertEqual(a['validation_chosen']['rule'],z['validation_chosen']['rule'])
        self.assertNotEqual(a['validation_chosen']['test'],z['validation_chosen']['test'])

    def test_grid_finite_and_bounded(self):
        self.assertLess(len(tuple(trial_grid())),10000)
        self.assertGreater(len(families()),5)

    def test_requires_exact_archival_size_for_reproduction(self):
        a=research([],expected_history=983)
        self.assertEqual(a['status'],'source_archive_changed')
        self.assertNotIn('validation_chosen',a)

if __name__=='__main__': unittest.main()
