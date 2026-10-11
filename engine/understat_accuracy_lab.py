"""Private 393-match research: test a pre-specified grid of 1X2 decision rules.

The *same* 40/15/45 by-league match-day split as the original expanded audit is
used. Never persist fixture identities or match-level provider data. Critical:
exploratory test-set maximum is explicitly contaminated (data snooping) and
MUST NOT be interpreted as out-of-sample accuracy or promoted to production.
The validation-chosen rule is evaluated without selecting on test outcomes,
but the historic test games were seen in earlier research; true validation
requires new forward matches.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
import math
from .understat_championship import evaluate
from .understat_d1 import D1
from .understat_hybrid import HYBRID_CANDIDATES

OUTCOMES=('home','draw','away')
# Authored before inspecting the search outputs. Finite bounded hypothesis family.
HOME_FACTORS=(.80,.88,.94,1.0,1.06,1.12,1.20,1.30)
DRAW_FACTORS=(.65,.78,.88,1.0,1.12,1.28,1.45)
BLEND_WEIGHTS=(.25,.50,.75)
EXPECTED_REFERENCE_HISTORY=983
EXPECTED_REFERENCE_TEST=393


def _component(record, key):
    if key.startswith('hybrid:'):
        p=record['hybrids'].get(key[7:])
    else:
        p=record.get(key)
    if not isinstance(p,dict) or any(k not in p for k in OUTCOMES):
        return None
    return p


def families():
    base=['dc_fixed_rho','elo','xgq','naive']
    # Not all combinations are equally plausible; a compact trial family avoids
    # thousands of pure-noise, unrelated model blends.
    hybrids=[f'hybrid:{a:.2f}_{b:.2f}' for a,b in HYBRID_CANDIDATES]
    singles=base+hybrids
    all_specs=[(name,None,0.) for name in singles]
    pairs=[('dc_fixed_rho','elo'),('dc_fixed_rho','xgq'),('elo','xgq'),
           ('dc_fixed_rho','naive'),('elo','naive')]
    pairs += [('dc_fixed_rho',h) for h in hybrids]
    pairs += [('elo',h) for h in hybrids]
    for a,b in pairs:
        for w in BLEND_WEIGHTS:
            all_specs.append((a,b,w))
    return tuple(all_specs)


def probabilities(rec,spec,h_factor,d_factor):
    a,b,w=spec
    p=_component(rec,a)
    q=_component(rec,b) if b is not None else p
    if p is None or q is None:
        return None
    h=((1-w)*p['home']+w*q['home'])*h_factor
    d=((1-w)*p['draw']+w*q['draw'])*d_factor
    away=(1-w)*p['away']+w*q['away']
    denom=h+d+away
    if not math.isfinite(denom) or denom<=0:
        raise ValueError('Invalid adjusted 1X2 probability')
    return (h/denom,d/denom,away/denom)


def trial_grid():
    for spec in families():
        for h in HOME_FACTORS:
            for d in DRAW_FACTORS:
                yield (spec,h,d)


def _summary(accuracy_count,n,ll,brier):
    return {'matches':n,'correct':accuracy_count,'accuracy':round(accuracy_count/n,6),
            'log_loss':round(ll/n,6),'brier':round(brier/n,6)}


def score_trial(records, trial):
    if not records:return None
    spec,h,d=trial
    ll=0.; brier=0.; correct=0
    for record in records:
        p=probabilities(record,spec,h,d)
        if p is None: return None
        y=OUTCOMES.index(record['outcome'])
        correct+=int(max(range(3),key=lambda i:p[i])==y)
        ll-=math.log(max(p[y],1e-12))
        brier+=sum((p[k]-int(k==y))**2 for k in range(3))
    return _summary(correct,len(records),ll,brier)


def _describe_trial(trial):
    spec,h,d=trial
    a,b,w=spec
    return {'first_model':a,'second_model':b,'second_weight':w,
            'home_probability_multiplier':h,'draw_probability_multiplier':d,
            'away_probability_multiplier':1.0,
            'decision':'argmax of normalized weighted 1X2 probabilities'}


def discover(validation,test, *, expected_test=EXPECTED_REFERENCE_TEST):
    if len(test)!=expected_test:
        return {'status':'sample_changed','validation_matches':len(validation),
                'test_matches':len(test),'expected_test_matches':expected_test,
                'reason':'Original expanded audit match-set is not reproduced; no 52% claim'}
    if len(validation)<60:
        return {'status':'insufficient_validation','validation_matches':len(validation),'test_matches':len(test)}
    grid=tuple(trial_grid())
    ranked=[]
    for idx,rule in enumerate(grid):
        s=score_trial(validation,rule)
        if s is not None:
            ranked.append((s['correct'],-s['log_loss'],-idx,rule,s))
    if not ranked: return {'status':'no_complete_rules','test_matches':len(test)}
    # Selection is on historical validation only, never on test outcomes.
    best=max(ranked,key=lambda x:(x[0],x[1],x[2]))
    picked=best[3]
    tested=score_trial(test,picked)
    # Explicit *optimistic* in-sample maximum on the already-observed 393 games,
    # NEVER evidence of genuine prospective skill. Includes selection over many rules.
    test_rank=[]
    for idx,trial in enumerate(grid):
        s=score_trial(test,trial)
        if s is not None:
            test_rank.append((s['correct'],-s['log_loss'],-idx,trial,s))
    hindsight=max(test_rank,key=lambda t:(t[0],t[1],t[2]))
    return {
        'status':'exploratory_research_only','method':'same_40_15_45_chronological_split',
        'comparison':'all 393 identical matches, no same/future-day match used for features',
        'validation_matches':len(validation),'test_matches':len(test),
        'rules_examined':len(grid),'rules_eligible':len(ranked),
        'validation_chosen':{'rule':_describe_trial(picked),'validation':best[4],
                             'test':tested,'achieved_52pct_on_original_test':tested['accuracy']>.52},
        'retrospective_test_scan':{'rule':_describe_trial(hindsight[3]),'test':hindsight[4],
                  'achieved_52pct_in_hindsight':hindsight[4]['accuracy']>.52,
                  'warning':'SELECTED USING TEST LABELS: OPTIMISTIC, INVALID AS OUT-OF-SAMPLE'},
        'warnings':[
            'The 393 test matches were already used in previous model comparisons.',
            'Do not promote any trial from this search without new chronologically later games.',
            'Accuracy threshold was user-requested after seeing previous results: multiple-comparison bias.',
            'A score above 52% here is not prospective performance or evidence of bookmaker superiority.'
        ]}


def research(rows, *, expected_history=EXPECTED_REFERENCE_HISTORY):
    if len(rows)!=expected_history:
        return {'status':'source_archive_changed','historical_matches':len(rows),
                'expected_historical_matches':expected_history,
                'reason':'Cannot claim exactly the same fixed 393-match audit against modified history'}
    holder={}
    def tap(val,test):
        holder.update(discover(val,test))
    audit=evaluate(rows,split_mode='expanded_350',on_splits=tap)
    out=dict(holder)
    out.update({'historical_matches':len(rows),'reference_audit_test':audit['test_eligible'],
                'reference_goal_accuracy':audit.get('test_scores',{}).get('dc_fixed_rho',{}).get('top_choice_accuracy'),
                'reference_hybrid_accuracy':audit.get('test_scores',{}).get('hybrid',{}).get('top_choice_accuracy'),
                'generated_at':datetime.now(timezone.utc).isoformat(),
                'production_model_unchanged':True,'live_forecasts_scored':0})
    if out.get('test_matches')!=audit['test_eligible']:
        raise RuntimeError('Research and reference evaluated different sets')
    return out


def main(argv=None):
    parser=argparse.ArgumentParser()
    parser.add_argument('--expected-history',type=int,default=EXPECTED_REFERENCE_HISTORY)
    args=parser.parse_args(argv)
    db=D1()
    # Freeze the EXACT identities of the reference 983-match research sample.
    # The refresh scheduler may add earlier-season matches during this run;
    # avoid quietly changing the 393-match evaluation split.
    frozen=db.query("SELECT v FROM metadata WHERE k='understat_accuracy_52_original_983_ids' LIMIT 1")
    if len(frozen)!=1:
        raise RuntimeError('Private 983-match sample identity snapshot missing')
    ids=json.loads(frozen[0]['v'])
    if (not isinstance(ids,list) or len(ids)!=EXPECTED_REFERENCE_HISTORY
            or len(set(ids))!=len(ids)):
        raise RuntimeError('Corrupt fixed research-sample identity list')
    archived=db.history()
    lookup={row['id']:row for row in archived}
    if len(set(ids)-set(lookup)):
        raise RuntimeError('Previously frozen private match identities are missing')
    frozen_rows=[lookup[id_] for id_ in ids]
    report=research(frozen_rows,expected_history=args.expected_history)
    report['current_full_archive_matches']=len(archived)
    report['reference_sample_identity_freeze']=True
    db.query("INSERT OR REPLACE INTO metadata(k,v) VALUES('understat_accuracy_52_search',?)", 
             (json.dumps(report,separators=(',',':')),))
    print('52pct audit research:',report.get('status'),'tests:',report.get('test_matches',0))
    if report.get('status')=='exploratory_research_only':
        print('Validation selected',report['validation_chosen']['test']['accuracy'],
              'hindsight maximum',report['retrospective_test_scan']['test']['accuracy'])
    return report

if __name__=='__main__':main()
