"""All historical quality tests are synthetic and offline."""
import unittest
from datetime import date, timedelta
from engine.xgq import strict_row
from engine.provider_understat import SOURCE
from engine.understat_quality import evaluate, score, bootstrap_skill, historical_league_baseline


def synthetic_matches(n=180):
    teams=[f'Test Team {i}' for i in range(10)]
    rows=[]
    origin=date(2026,1,1)
    for i in range(n):
        h=teams[i%10]
        a=teams[(i+1+(i//10)%8)%10]
        if a == h:
            a=teams[(i+2)%10]
        row=strict_row({'date':(origin+timedelta(days=i)).isoformat(),'league':'en.1',
            'home_team':h,'away_team':a,'home_goals':i%4,'away_goals':(i//3)%3,
            'home_shots_xg':[0.2,0.05,0.06], 'away_shots_xg':[0.15,0.10,0.1],
            'source':SOURCE,'source_match_id':str(300000+i)})
        rows.append(row)
    return rows

class PrivateUnderstatQualityTests(unittest.TestCase):
    def test_insufficient_samples_report_honest_abstention(self):
        r=evaluate(synthetic_matches(45))
        self.assertEqual(r['status'],'insufficient')
        self.assertEqual(r['eligible_test_matches'],0)
        self.assertNotIn('model',r)

    def test_retro_baselines_on_same_eligible_test_games(self):
        report=evaluate(synthetic_matches(180))
        self.assertEqual(report['status'],'retrospective',report)
        self.assertGreaterEqual(report['eligible_test_matches'],25)
        self.assertEqual(report['model']['tested'],report['naive_historical_league_baseline']['tested'])
        self.assertIn('log_loss_gain_ci95',report['skill_against_naive_with_ci'])
        self.assertEqual(report['live_forecasts_scored'],0)
        self.assertNotIn('Test Team',str(report))

    def test_reject_wrong_provider_and_duplicate_ids(self):
        rows=synthetic_matches(3)
        with self.assertRaises(ValueError):evaluate(rows+[rows[0]])
        with self.assertRaises(ValueError):evaluate([{**rows[0], 'source':'StatsBomb Open Data'}])

    def test_naive_scoring_and_pairwise_uncertainty(self):
        p=historical_league_baseline([])
        self.assertAlmostEqual(sum(p.values()),1)
        self.assertAlmostEqual(p['draw'],1/3)
        entry=[{'league':'en.1','date':'2026-10-10','outcome':'home',
                'model':{'home':.6,'draw':.2,'away':.2},
                'baseline':{'home':.6,'draw':.2,'away':.2}}]
        ci=bootstrap_skill(entry,draws=200)
        self.assertEqual(ci['log_loss_gain_ci95'],[0.0,0.0])
        m=score([(entry[0]['model'],'home')])
        self.assertEqual(m['tested'],1)
        self.assertGreater(m['top_choice_accuracy'],0)

if __name__ == '__main__':unittest.main()
