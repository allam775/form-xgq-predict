"""Offline deterministic tests for all-match source-isolated championship benchmark."""
import unittest
from datetime import date, timedelta
from engine.xgq import strict_row
from engine.provider_understat import SOURCE
from engine.understat_championship import (evaluate,_poisson_rates,_calibration,
                                           _update_elo_batch, _elo_probs, _paired_ci)


def sample_matches(n=400,league='en.1'):
    teams=[f'Benchmark Team {i}' for i in range(12)]
    origin=date(2024,8,1)
    rows=[]
    for i in range(n):
        home=teams[i % 12]
        away=teams[(i + 1 + (i//12) % 8) % 12]
        if home==away:
            away=teams[(i+2)%12]
        rows.append(strict_row({'date':(origin+timedelta(days=i)).isoformat(),'league':league,
                 'home_team':home,'away_team':away,'home_goals':i%4,'away_goals':(i//3)%3,
                 'home_shots_xg':[.06,.10,.22,.03], 'away_shots_xg':[.08,.19,.04],
                 'source':SOURCE,'source_match_id':str(i+3000000 + ({'en.1':0, 'fr.1':1000000}.get(league,2000000)))}))
    return rows


class ChampionshipTests(unittest.TestCase):
    def test_unavailable_external_market_not_invented(self):
        report=evaluate(sample_matches(400),min_test=15,min_validation=15)
        self.assertEqual(report['status'],'retrospective',report)
        self.assertEqual(report['market_odds']['status'],'not_evaluated')
        self.assertEqual(report['live_forecasts_scored'],0)
        self.assertGreaterEqual(report['test_eligible'],15)
        self.assertEqual(report['test_scores']['xgq']['tested'],report['test_scores']['elo']['tested'])
        self.assertEqual(report['test_scores']['xgq']['tested'],report['test_scores']['dc_fixed_rho']['tested'])
        self.assertNotIn('Benchmark Team',str(report))

    def test_fixed_score_poisson_and_calibration_valid(self):
        probs=_poisson_rates(1.3,1.0)
        self.assertAlmostEqual(sum(probs.values()),1,places=8)
        self.assertTrue(all(0<=p<=1 for p in probs.values()))
        record={'date':'2026-03-11','league':'en.1','outcome':'home','xgq':probs}
        report=_calibration([record], 'xgq')
        self.assertIsNotNone(report['classwise_expected_calibration_error'])
        self.assertEqual(sum(x['n'] for arr in report['by_outcome'].values() for x in arr),3)

    def test_no_fictitious_skill_on_identical_predictions(self):
        p={'home':.5,'draw':.3,'away':.2}
        arr=[{'league':'en.1','date':f'2026-01-{i+1:02d}','outcome':'home','xgq':p,'challenger':p}
             for i in range(15)]
        self.assertEqual(_paired_ci(arr,'challenger')['log_loss_gain_over_xgq_ci95'],[0.0,0.0])

    def test_elo_day_batches_are_order_independent(self):
        matches=sample_matches(3)
        a,b={},{}
        _update_elo_batch(a,matches)
        _update_elo_batch(b,list(reversed(matches)))
        self.assertEqual(a,b)

    def test_sparse_and_wrong_source_protected(self):
        self.assertEqual(evaluate(sample_matches(20))['status'],'insufficient')
        rows=sample_matches(2)
        with self.assertRaises(ValueError):evaluate(rows+[rows[0]])
        with self.assertRaises(ValueError):evaluate([{**rows[0],'source':'StatsBomb Open Data'}])

    def test_expanded_350_protocol_is_predeclared_and_never_fakes_threshold(self):
        rows = sample_matches(400)
        insufficient = evaluate(rows, min_test=350, min_validation=15,
                                split_mode='expanded_350')
        self.assertEqual(insufficient['status'], 'insufficient')
        self.assertEqual(insufficient['requested_test_target'], 350)
        self.assertFalse(insufficient['requested_test_target_met'])
        self.assertEqual(insufficient['method'],
                         'chronological_40_15_45_by_league_match_day_no_leakage')
        self.assertIn('overlaps', insufficient['retrospective_overlap_warning'])
        broader = evaluate(rows, min_test=15, min_validation=15,
                           split_mode='expanded_350')
        original = evaluate(rows, min_test=15, min_validation=15)
        self.assertEqual(broader['status'], 'retrospective', broader)
        self.assertGreater(broader['test_eligible'], original['test_eligible'])
        self.assertEqual(broader['test_scores']['hybrid']['tested'], broader['test_eligible'])
        dates = broader['leagues']['en.1']
        self.assertLess(dates['validation_start'], dates['test_start'])
        self.assertEqual(dates['train_day_fraction'], .4)
        with self.assertRaises(ValueError):
            evaluate(rows, split_mode='user_chosen_after_results')

    def test_expanded_validation_unaffected_by_future_test_outcomes(self):
        rows = sample_matches(400)
        baseline = evaluate(rows, min_test=15, min_validation=15,
                            split_mode='expanded_350')
        cutoff = baseline['leagues']['en.1']['test_start']
        changed = [{**r, 'hg':4-r['hg'], 'ag':3-r['ag']}
                   if r['date']>=cutoff else r for r in rows]
        alternate = evaluate(changed, min_test=15, min_validation=15,
                             split_mode='expanded_350')
        self.assertEqual(baseline['selected_challenger'], alternate['selected_challenger'])
        self.assertEqual(baseline['hybrid_selected'], alternate['hybrid_selected'])

    def test_test_labels_cannot_select_model_or_change_past_elo(self):
        games=sample_matches(400)
        a=evaluate(games,min_test=15,min_validation=15)
        # Only test-window labels changed; validation model selection identical.
        test_start=a['leagues']['en.1']['test_start']
        swapped=[{**r,'hg': 5-r['hg'],'ag': 4-r['ag']} if r['date']>=test_start else r for r in games]
        b=evaluate(swapped,min_test=15,min_validation=15)
        self.assertEqual(a['selected_challenger'],b['selected_challenger'])
        self.assertEqual(a['hybrid_selected'],b['hybrid_selected'])
        self.assertEqual(a['validation_champion_log_loss'],b['validation_champion_log_loss'])


if __name__=='__main__':unittest.main()
