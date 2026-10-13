"""UCL 2025/26 scoreline/chronology/no-postgame-leak regressions."""
import copy
import unittest
from research.ucl_2025_26 import (
 fixtures, prediction, domestic_profiles, POT, POT_RATING, MODELS,
 update_rating, evaluate
)


class UEFA2025ReplayTests(unittest.TestCase):
    def test_all_189_results_include_correct_90_minute_knockout_results(self):
        matches=fixtures()
        self.assertEqual(len(matches),189)
        self.assertEqual(len([m for m in matches if m['phase'].startswith('League')]),144)
        self.assertEqual(len(POT),36)
        last=matches[-1]
        self.assertEqual(last['goals_90'],[1,1])
        self.assertEqual(last['penalties'],'4-3')
        juve=[m for m in matches if m['home']=='Juventus' and m['away']=='Galatasaray']
        self.assertEqual(juve[0]['goals_90'],[3,0])

    def test_pre_match_model_is_fully_normalized(self):
        rating={t:float(POT_RATING[POT[t]]) for t in POT}
        games=fixtures()
        for m in [games[0],games[9],games[50],games[188]]:
            p=prediction(m,rating,{})
            for k in MODELS:
                self.assertAlmostEqual(sum(p['probabilities'][k].values()),1.,places=8)
            self.assertAlmostEqual(sum(sum(row) for row in p['matrices']['xgq_shots_stage1']),1.,places=8)
            self.assertEqual(len(p['top5']),5)
            self.assertEqual(p['top5'][0]['probability'],
                             p['matrices']['xgq_shots_stage1'][
                               p['top5'][0]['score'][0]][p['top5'][0]['score'][1]])

    def test_future_domestic_shots_are_ignored_strictly(self):
        def row(i,day,h,a,xg=1.0):
            return dict(id='en.1|'+day+'|'+str(i),date=day,league='en.1',h=h,a=a,
                home_xg=xg,away_xg=1.4,home_shots=11,away_shots=13,
                home_xgq=.05,away_xgq=.06)
        prior=[row(i,'2025-06-01','arsenal' if i%2 else 'chelsea',
                         'chelsea' if i%2 else 'arsenal') for i in range(50)]
        later=row(51,'2025-09-16','arsenal','chelsea',xg=1000)
        f0,_=domestic_profiles(prior,'2025-09-16')
        f1,_=domestic_profiles(prior+[later],'2025-09-16')
        self.assertEqual(f0,f1)
        self.assertIn('Arsenal',f1)
        self.assertEqual(f1['Arsenal']['games'],16)

    def test_same_day_uefa_outcomes_cannot_influence_other_matches(self):
        matches=fixtures()[:18]
        rating={t:float(POT_RATING[POT[t]]) for t in POT}
        today=sorted([r for r in matches if r['date']=='2025-09-16'],key=lambda m:m['id'])
        before=prediction(today[1],rating,{})['probabilities']
        # Re-label future (same-day) match; pre-match state must remain frozen.
        changed=copy.deepcopy(today)
        changed[0]['goals_90']=[20,0]
        self.assertEqual(before,prediction(changed[1],rating,{})['probabilities'])
        after=copy.copy(rating)
        update_rating(after,changed)
        self.assertNotEqual(after,rating)


if __name__=='__main__':
    unittest.main()
