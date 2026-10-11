"""Private, chronology-safe benchmark of production XGQ against useful football baselines.

Every displayed number is derived from FINAL Understat match summaries in private D1.
No bookmaker odds are manufactured. Optional market comparisons require separately
licensed, time-stamped pre-match prices and are explicitly unavailable here.
Predictions use only matches whose *date* is strictly earlier than the target match.
Model variants are selected on per-league date-blocked validation; test is untouched.
No candidate is deployed or used to overwrite previously published forecasts.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from itertools import groupby
import json
import math
from random import Random

from .provider_understat import SOURCE
from .understat_private import verified_row
from .understat_quality import OUTCOMES, actual_outcome, historical_league_baseline, score
from .understat_d1 import D1
from .xgq import predict_xgq, weighted_form, poisson_probabilities
from .understat_hybrid import HYBRID_CANDIDATES, hybrid_probs

# Preregistered simple alternatives; validation determines the challenger.
VARIANTS = ((0.0, 0.0), (0.25, 0.0), (0.50, 0.0),
            (0.0, 0.15), (0.25, 0.15), (0.50, 0.15))
MIN_EVAL = 30


def clamp(x, low, high):
    return max(low, min(high, x))


def _probabilities(h, d, a):
    probs = {'home': float(h), 'draw': float(d), 'away': float(a)}
    if any(not math.isfinite(v) or v < 0 for v in probs.values()):
        raise ValueError('Invalid 1X2 probability')
    s = sum(probs.values())
    if s <= 0:
        raise ValueError('Zero 1X2 probability')
    return {k: v / s for k, v in probs.items()}


def _poisson_rates(lh, la, *, rho=-0.08):
    """Dixon-Coles-type, fixed-rho low-score dependence (NOT fitted DC)."""
    lh, la = clamp(lh, .2, 4.0), clamp(la, .2, 4.0)
    def pmf(mu):
        out = [math.exp(-mu)]
        for k in range(1, 13):
            out.append(out[-1] * mu / k)
        return out
    home, away = pmf(lh), pmf(la)
    probs = [0.0, 0.0, 0.0]
    for i, ph in enumerate(home):
        for j, pa in enumerate(away):
            tau = 1.0
            if i == 0 and j == 0: tau = 1 - lh * la * rho
            elif i == 0 and j == 1: tau = 1 + lh * rho
            elif i == 1 and j == 0: tau = 1 + la * rho
            elif i == 1 and j == 1: tau = 1 - rho
            prob = ph * pa * max(0.0, tau)
            probs[0 if i > j else 1 if i == j else 2] += prob
    return _probabilities(*probs)


def _dc_baseline(prior, game):
    if len(prior) < 40:
        return None
    team_home, team_away = game['h'], game['a']
    total = (sum(r['hg'] + r['ag'] for r in prior) / (2 * len(prior)))
    gh = sum(r['hg'] for r in prior) / len(prior)
    ga = sum(r['ag'] for r in prior) / len(prior)
    if total < .1:
        return None
    def rates(team):
        games = [r for r in prior if team in (r['h'], r['a'])][-20:]
        if len(games) < 5:
            return None
        scored = sum(r['hg'] if r['h'] == team else r['ag'] for r in games)
        conceded = sum(r['ag'] if r['h'] == team else r['hg'] for r in games)
        # Six league-mean pseudo-observations stabilize promoted/rare teams.
        return (scored + 6 * total) / (len(games) + 6), (conceded + 6 * total) / (len(games) + 6)
    h, a = rates(team_home), rates(team_away)
    if h is None or a is None:
        return None
    lh = gh * clamp(h[0] / total * a[1] / total, .45, 2.3)
    la = ga * clamp(a[0] / total * h[1] / total, .45, 2.3)
    return _poisson_rates(lh, la)


def _elo_probs(prior, ratings, game):
    if len(prior) < 40:
        return None
    delta = ratings.get(game['h'], 1500) + 65 - ratings.get(game['a'], 1500)
    non_draw_home = 1 / (1 + 10 ** (-delta / 400))
    draw_rate = historical_league_baseline(prior)['draw']
    draw = clamp(draw_rate * (1 - .22 * abs(delta) / 400), .12, .40)
    return _probabilities((1 - draw) * non_draw_home, draw, (1 - draw) * (1 - non_draw_home))


def _update_elo_batch(ratings, games):
    """Update AFTER the whole match day, using pre-day ratings for every match."""
    changes = defaultdict(float)
    for game in games:
        h, a = game['h'], game['a']
        delta = ratings.get(h, 1500) + 65 - ratings.get(a, 1500)
        expected = 1 / (1 + 10 ** (-delta / 400))
        actual = 1 if game['hg'] > game['ag'] else .5 if game['hg'] == game['ag'] else 0
        change = 22 * (actual - expected)
        changes[h] += change
        changes[a] -= change
    for key, diff in changes.items():
        ratings[key] = ratings.get(key, 1500) + diff


def _dynamic_adjustment(base, prior, game, strength):
    if not strength:
        return _probabilities(*(base['probabilities'][k] for k in OUTCOMES))
    d, league = game['date'], game['league']
    home = weighted_form(prior, league, game['h'], d, lookback=16, half_life=90)
    away = weighted_form(prior, league, game['a'], d, lookback=16, half_life=90)
    h5 = weighted_form(prior, league, game['h'], d, lookback=5, half_life=60)
    a5 = weighted_form(prior, league, game['a'], d, lookback=5, half_life=60)
    if not all((home, away, h5, a5)):
        return _probabilities(*(base['probabilities'][k] for k in OUTCOMES))
    def direction(recent, long, key):
        return clamp((recent[key] + .005) / (long[key] + .005), .65, 1.35)
    home_trend = direction(h5, home, 'xgq_for') * direction(a5, away, 'xgq_against')
    away_trend = direction(a5, away, 'xgq_for') * direction(h5, home, 'xgq_against')
    lh = base['expected_home_goals'] * clamp(1 + strength * (home_trend - 1), .78, 1.27)
    la = base['expected_away_goals'] * clamp(1 + strength * (away_trend - 1), .78, 1.27)
    probs = poisson_probabilities(lh, la)
    return _probabilities(*(probs[k] for k in OUTCOMES))


def _variant_probs(base, prior, game, baseline, params):
    strength, shrinkage = params
    dyn = _dynamic_adjustment(base, prior, game, strength)
    return _probabilities(*(dyn[k] * (1 - shrinkage) + baseline[k] * shrinkage for k in OUTCOMES))


def _calibration(entries, model_name, *, bins=10):
    """Class-wise empirical frequencies; only aggregated counts are returned."""
    buckets = {k: [{'n':0,'prediction_sum':0.,'actual_sum':0} for _ in range(bins)] for k in OUTCOMES}
    for x in entries:
        probs = x[model_name]
        for k in OUTCOMES:
            i = min(bins - 1, int(probs[k] * bins))
            r = buckets[k][i]
            r['n'] += 1
            r['prediction_sum'] += probs[k]
            r['actual_sum'] += int(x['outcome'] == k)
    result, loss, n = {}, 0., 0
    for label, arr in buckets.items():
        prepared = []
        for i, b in enumerate(arr):
            if b['n'] == 0:
                continue
            pred = b['prediction_sum']/b['n']
            obs = b['actual_sum']/b['n']
            loss += b['n'] * abs(pred - obs)
            n += b['n']
            prepared.append({'bin':f'{i/bins:.1f}–{(i+1)/bins:.1f}', 'n':b['n'],
                             'predicted':round(pred,4), 'observed':round(obs,4)})
        result[label] = prepared
    return {'classwise_expected_calibration_error':round(loss/n,6) if n else None,
            'by_outcome':result}


def _paired_ci(records, challenger, baseline='xgq', draws=1000, seed=20261011):
    blocks = defaultdict(list)
    for r in records:
        outcome = r['outcome']
        # Positive means challenger has BETTER (lower) log loss.
        delta = math.log(max(r[challenger][outcome], 1e-12)) - math.log(max(r[baseline][outcome], 1e-12))
        blocks[(r['league'], r['date'])].append(delta)
    groups = list(blocks.values())
    if len(groups) < 8:
        return {'status':'insufficient', 'paired_days':len(groups)}
    rng = Random(seed)
    samples = []
    for _ in range(draws):
        chosen = [groups[rng.randrange(len(groups))] for _ in groups]
        samples.append(sum(map(sum, chosen)) / sum(map(len, chosen)))
    samples.sort()
    ci = [round(samples[int((draws-1)*.025)],6),round(samples[int((draws-1)*.975)],6)]
    return {'paired_matches':len(records),'paired_days':len(groups),
            'log_loss_gain_over_xgq_ci95':ci,'gain_confidently_positive':ci[0]>0}


def _record_scores(records, names):
    return {name:score([(r[name],r['outcome']) for r in records]) for name in names}


def evaluate(rows, *, min_test=MIN_EVAL, min_validation=MIN_EVAL):
    if not isinstance(rows, list):
        raise ValueError('Require verified Understat match list')
    games = [verified_row(r) for r in rows]
    if any(g['date'] > date.today().isoformat() for g in games):
        raise ValueError('Future-dated results cannot be used for a retrospective benchmark')
    if len(set(r['id'] for r in games)) != len(games) or len(set(r['source_match_id'] for r in games)) != len(games):
        raise ValueError('Duplicate private Understat identity')
    if any(r['source'] != SOURCE for r in games):
        raise ValueError('Cross-provider data must not mix')
    games.sort(key=lambda r:(r['league'],r['date'],r['id']))
    cohorts = defaultdict(list)
    for row in games:
        cohorts[row['league']].append(row)
    eligible_by_split = {'validation':[], 'test':[]}
    coverage = {}
    for league, fixtures in sorted(cohorts.items()):
        days = sorted(set(g['date'] for g in fixtures))
        if len(fixtures) < 90 or len(days) < 30:
            coverage[league] = {'status':'sparse', 'matches':len(fixtures), 'match_days':len(days)}
            continue
        val_date, test_date = days[int(len(days)*.6)], days[int(len(days)*.8)]
        coverage[league]={'matches':len(fixtures),'match_days':len(days),
                          'validation_start':val_date,'test_start':test_date}
        prior = []
        ratings = {}
        for day, group in groupby(fixtures, lambda r:r['date']):
            batch = list(group)
            split = ('train' if day < val_date else 'validation' if day < test_date else 'test')
            if split != 'train':
                cutoff=(date.fromisoformat(day)-timedelta(days=900)).isoformat()
                recent=[r for r in prior if r['date']>=cutoff]
                base_probs = historical_league_baseline(recent) if len(recent)>=40 else None
                for match in batch:
                    if base_probs is None:
                        continue
                    fixture={'league':league,'date':day,'home_team':match['home'],'away_team':match['away']}
                    forecast,reason=predict_xgq(fixture,prior,day)
                    if forecast is None:
                        continue
                    elo=_elo_probs(recent,ratings,match)
                    dc=_dc_baseline(recent,match)
                    if not elo or not dc:
                        continue
                    item={'league':league,'date':day,'outcome':actual_outcome(match),
                          'xgq':_probabilities(*(forecast['probabilities'][k] for k in OUTCOMES)),
                          'naive':base_probs,'elo':elo,'dc_fixed_rho':dc}
                    # Goal/shot hybrid candidates are pre-registered and computed
                    # exclusively from completed matches before this match day.
                    item['hybrids']={f'{w:.2f}_{q:.2f}': hybrid_probs(
                        recent,match,dc,(w,q)) for w,q in HYBRID_CANDIDATES}
                    # Generate only pre-specified variants using pre-day evidence.
                    item['variants']={f'{strength:.2f}_{shrink:.2f}':_variant_probs(
                        forecast,prior,match,base_probs,(strength,shrink)) for strength,shrink in VARIANTS}
                    eligible_by_split[split].append(item)
            _update_elo_batch(ratings,batch)
            prior.extend(batch)
    val,test=eligible_by_split['validation'],eligible_by_split['test']
    report={'status':'insufficient','method':'chronological_60_20_20_by_league_match_day_no_leakage',
            'source':'Understat private verified per-shot summaries','historical_matches':len(games),
            'latest_evidence_date':max((r['date'] for r in games),default=None),
            'validation_eligible':len(val),'test_eligible':len(test),'minimum_test':min_test, 'held_out_target':1000, 'held_out_target_met':len(test)>=1000,
            'leagues':coverage,'research_only':True,'production_model_unchanged':True,
            'live_forecasts_scored':0,
            'market_odds':{'status':'not_evaluated','reason':'No licensed timestamped pre-match 1X2 odds matched to Understat fixtures'},
            'external_global_claims':'Not comparable to published scores from other samples; same-match external benchmarks required',
            'generated_at':datetime.now(timezone.utc).isoformat()}
    if len(val)<min_validation or len(test)<min_test:
        report['reason']='too_few_chronological_eligible_matches'
        return report
    def vkey(params): return f'{params[0]:.2f}_{params[1]:.2f}'
    rank=sorted(VARIANTS,key=lambda p:(score([(r['variants'][vkey(p)],r['outcome']) for r in val])['log_loss'],p!=VARIANTS[0],p))
    selected=rank[0]
    # Tune the blend ONLY on validation, using the exact same eligible games.
    def hybrid_key(params): return f'{params[0]:.2f}_{params[1]:.2f}'
    eligible_hybrids=[]
    for params in HYBRID_CANDIDATES:
        key=hybrid_key(params)
        paired=[r for r in val if r['hybrids'].get(key) is not None]
        if len(paired)!=len(val):
            continue
        metric=score([(r['hybrids'][key],r['outcome']) for r in paired])
        eligible_hybrids.append((metric['log_loss'],params))
    if not eligible_hybrids:
        report['reason']='no_hybrid_candidate_with_complete_validation'
        return report
    hybrid_params=min(eligible_hybrids,key=lambda x:(x[0],x[1]))[1]
    key=hybrid_key(hybrid_params)
    if any(r['hybrids'].get(key) is None for r in test):
        report['reason']='hybrid_missing_on_heldout_games'
        return report
    hybrid_validation=score([(r['hybrids'][key],r['outcome']) for r in val])
    # Report on *identical* untouched held-out games; selection used validation only.
    for rec in test:
        rec['challenger']=rec['variants'][vkey(selected)]
        rec['hybrid']=rec['hybrids'][key]
        del rec['hybrids']
        del rec['variants']
    names=('xgq','naive','elo','dc_fixed_rho','challenger','hybrid')
    scores=_record_scores(test,names)
    goal_ci=_paired_ci(test,'hybrid',baseline='dc_fixed_rho')
    if 'log_loss_gain_over_xgq_ci95' in goal_ci:
        goal_ci['log_loss_gain_over_goal_model_ci95']=goal_ci.pop('log_loss_gain_over_xgq_ci95')
    goal_ci['baseline_model']='dc_fixed_rho'
    report.update({
        'status':'retrospective',
        'selected_challenger':{'recent_form_weight':selected[0],
                               'league_frequency_shrinkage':selected[1],
                               'chosen_by':'validation_log_loss_only'},
        'validation_champion_log_loss':score([(r['variants'][vkey(selected)],r['outcome']) for r in val])['log_loss'],
        'hybrid_selected':{'goal_shot_blend':hybrid_params[0],
                           'shot_xgq_influence':hybrid_params[1],
                           'selection':'validation_only',
                           'validation_log_loss':hybrid_validation['log_loss']},
        'hybrid_adoption_gate':{
            'status':'research_only_do_not_promote',
            'requirements':'out_of_sample_CI_positive_vs_current_goal_champion_and_live_forward_validation',
            'heldout_target':1000,'heldout_target_met':len(test)>=1000,
        },
        'test_scores':scores,
        'test_calibration':{name:_calibration(test,name) for name in ('xgq','challenger','elo','dc_fixed_rho','hybrid')},
        'paired_uncertainty':{name:_paired_ci(test,name) for name in ('naive','elo','dc_fixed_rho','challenger','hybrid')},
        'hybrid_vs_goal_champion_ci':goal_ci,
        'test_by_league':{league:_record_scores([r for r in test if r['league']==league],names)
                          for league in sorted({r['league'] for r in test})},
        'warning':'Research hybrid uses pre-day opponent-adjusted xG/xGA/XGQ; DC-only is a valid selected option. No production promotion.'
    })
    return report


def main():
    db=D1()
    result=evaluate(db.history())
    db.query("INSERT OR REPLACE INTO metadata(k,v) VALUES('understat_championship_report',?)",
             (json.dumps(result,separators=(',',':')),))
    # Count & aggregate metrics only; no private match identifiers or match payloads.
    print('Understat championship benchmark:',result['status'],'archive:',result['historical_matches'],
          'validation:',result['validation_eligible'],'test:',result['test_eligible'])
    if result['status']=='retrospective':
        print('Matched held-out 1X2 log loss:',{k:v['log_loss'] for k,v in result['test_scores'].items()})
    return result


if __name__=='__main__':
    main()
