"""Private, strictly chronological 1X2 audit for the unchanged production XGQ model.

Only Understat compact, verified FINAL matches are read from private D1. No raw
matches, names, provider payloads or predictions are written to GitHub or logs.
No future or same-day matches inform a historical forecast. This retrospective
replay does not assert that currently published future forecasts were correct.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone, date, timedelta
import json
import math
from random import Random

from .provider_understat import SOURCE
from .understat_private import verified_row
from .xgq import predict_xgq
from .understat_d1 import D1

OUTCOMES = ('home', 'draw', 'away')
MIN_EVALUATED = 25


def actual_outcome(row):
    return 'home' if row['hg'] > row['ag'] else 'away' if row['hg'] < row['ag'] else 'draw'


def historical_league_baseline(prior):
    """A pre-game league 1X2 frequency baseline with Laplace smoothing."""
    counts = Counter(actual_outcome(row) for row in prior)
    denom = len(prior) + 3
    return {outcome: (counts[outcome] + 1) / denom for outcome in OUTCOMES}


def score(records):
    if not records:
        return {'tested': 0}
    ll = brier = correct = 0
    for probs, actual in records:
        ll -= math.log(max(1e-12, probs[actual]))
        brier += sum((probs[k] - int(k == actual))**2 for k in OUTCOMES)
        correct += max(OUTCOMES, key=lambda k: probs[k]) == actual
    n = len(records)
    return {'tested': n, 'log_loss': round(ll/n, 6), 'brier': round(brier/n, 6),
            'top_choice_accuracy': round(correct/n, 6)}


def bootstrap_skill(entries, *, draws=1000, seed=20261011):
    """Paired league/date block bootstrap for positive log-loss advantage."""
    if not entries:
        return {'status': 'insufficient', 'reason': 'no_paired_matches'}
    blocks = defaultdict(list)
    for entry in entries:
        actual = entry['outcome']
        difference = math.log(max(entry['model'][actual], 1e-12)) - math.log(max(entry['baseline'][actual], 1e-12))
        blocks[(entry['league'], entry['date'])].append(difference)
    groups = [blocks[k] for k in sorted(blocks)]
    rng = Random(seed)
    samples = []
    for _ in range(draws):
        selected = [groups[rng.randrange(len(groups))] for _ in groups]
        samples.append(sum(sum(group) for group in selected)/sum(map(len, selected)))
    samples.sort()
    return {'method': 'paired_bootstrap_by_league_match_date',
            'paired_dates': len(groups), 'draws': draws,
            'log_loss_gain_ci95': [round(samples[int((draws-1)*.025)], 6),
                                   round(samples[int((draws-1)*.975)], 6)],
            'positive_gain_95pct': samples[int((draws-1)*.025)] > 0}


def evaluate(rows, *, min_evaluated=MIN_EVALUATED):
    if not isinstance(rows, list):
        raise ValueError('Expected verified private match history list')
    verified = [verified_row(row) for row in rows]
    if len({row['id'] for row in verified}) != len(verified):
        raise ValueError('Duplicate private match ID')
    if len({row['source_match_id'] for row in verified}) != len(verified):
        raise ValueError('Duplicate private source match ID')
    verified.sort(key=lambda r: (r['date'], r['league'], r['id']))
    leagues = defaultdict(list)
    for row in verified:
        if row['source'] != SOURCE:
            raise ValueError('Mixed-provider historical evidence')
        leagues[row['league']].append(row)
    blocks = {}
    test_rows = []
    for league, records in sorted(leagues.items()):
        days = sorted(set(row['date'] for row in records))
        if len(days) < 15 or len(records) < 60:
            blocks[league] = {'status': 'too_little_data', 'matches': len(records), 'dates': len(days)}
            continue
        pivot = days[max(1, int(.75 * len(days)))]
        candidates = [row for row in records if row['date'] >= pivot]
        blocks[league] = {'status': 'candidate_window', 'matches': len(records),
                          'dates': len(days), 'test_candidate_matches': len(candidates),
                          'start_date': pivot}
        test_rows.extend(candidates)
    entries = []
    withheld = Counter()
    for row in test_rows:
        past = [r for r in leagues[row['league']] if r['date'] < row['date']]
        fixture = {'date': row['date'], 'league': row['league'],
                   'home_team': row['home'], 'away_team': row['away']}
        forecast, reason = predict_xgq(fixture, verified, row['date'])
        if forecast is None:
            withheld[reason or 'unknown'] += 1
            continue
        baseline_prior = [r for r in past if r['date'] >= (
            date.fromisoformat(row['date']) - timedelta(days=900)).isoformat()]
        if len(baseline_prior) < 40:
            withheld['league_baseline_insufficient'] += 1
            continue
        model = {k: float(forecast['probabilities'][k]) for k in OUTCOMES}
        if abs(sum(model.values()) - 1) > 0.001:
            raise ValueError('Invalid model 1X2 probability sum')
        entries.append({'date': row['date'], 'league': row['league'],
                        'outcome': actual_outcome(row),
                        'model': model, 'baseline': historical_league_baseline(baseline_prior)})
    pairs = [(e['model'],e['outcome']) for e in entries]
    simple = [(e['baseline'],e['outcome']) for e in entries]
    report = {'method': 'fixed_production_xgq_date_blocked_last_quarter_by_league',
              'evidence_source': 'Understat private verified per-shot XGQ',
              'history_matches': len(verified),
              'latest_evidence_date': verified[-1]['date'] if verified else None,
              'test_candidate_matches': len(test_rows), 'eligible_test_matches': len(entries),
              'withheld_reasons': dict(sorted(withheld.items())),
              'leagues': blocks,
              'generated_at': datetime.now(timezone.utc).isoformat(),
              'live_forecasts_scored': 0,
              'no_model_tuning_or_auto_promotion': True,
              'limitations': 'Retrospective historical replay; not an evaluation of future published forecasts.'}
    if len(entries) < min_evaluated:
        report.update(status='insufficient', reason='too_few_eligible_held_out_matches',
                      min_required=min_evaluated)
        return report
    model_metrics, baseline_metrics = score(pairs), score(simple)
    gain = baseline_metrics['log_loss'] - model_metrics['log_loss']
    report.update(status='retrospective', model=model_metrics,
                  naive_historical_league_baseline=baseline_metrics,
                  log_loss_gain_over_naive=round(gain, 6),
                  skill_against_naive_with_ci=bootstrap_skill(entries),
                  warning='Small samples and incomplete seasons may prevent generalization.')
    return report


def main():
    db = D1()
    report = evaluate(db.history())
    db.query("INSERT OR REPLACE INTO metadata(k,v) VALUES('understat_quality_report',?)",
             (json.dumps(report, separators=(',', ':')),))
    # Aggregate metrics only, no private match identifiers or raw payloads.
    print('Understat retrospective:', report['status'],
          'matches=', report['history_matches'], 'eligible=', report['eligible_test_matches'])
    if report['status'] == 'retrospective':
        print('XGQ log loss=', report['model']['log_loss'],
              'naive log loss=', report['naive_historical_league_baseline']['log_loss'],
              'XGQ Brier=', report['model']['brier'],
              'naive Brier=', report['naive_historical_league_baseline']['brier'])
    return report


if __name__ == '__main__':
    main()
