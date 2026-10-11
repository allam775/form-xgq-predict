"""Opponent-adjusted, decayed private Understat shot evidence blended with goal ratings.

A research-only candidate, not a trained or promoted production model.
Every statistic comes from final matches STRICTLY before the fixture date, from
one source. Never use aggregate xG as fabricated shot arrays; existing compact
match records were previously validated against actual per-shot Understat xG.
"""
from __future__ import annotations

from datetime import date
import math

from .provider_understat import SOURCE
from .xgq import poisson_probabilities

# (shot-informed blend weight, xGQ strength in shot goal rates).
# Includes DC-only champion, so cross-validation may elect NOT to use shots.
HYBRID_CANDIDATES = ((0.0, 0.0), (0.15, 0.0), (0.30, 0.0),
                     (0.50, 0.0), (0.20, 0.30), (0.35, 0.30),
                     (0.50, 0.30), (0.35, 0.65))


def _clip(value, minimum, maximum):
    return max(minimum, min(maximum, value))


def _team_form(prior, team, target_day, *, lookback=20, half_life_days=120):
    """Exponentially age-weighted attack, conceded xG and XGQ for a club."""
    records = sorted((r for r in prior if team in (r['h'], r['a']) and
                      r['date'] < target_day), key=lambda r: (r['date'], r['id']), reverse=True)[:lookback]
    if len(records) < 5:
        return None
    now = date.fromisoformat(target_day)
    totals = {'xg_for': 0., 'xg_against': 0., 'xgq_for': 0., 'xgq_against': 0.}
    weight_sum = 0.
    for r in records:
        home = r['h'] == team
        our, opp = ('home', 'away') if home else ('away', 'home')
        delta = (now - date.fromisoformat(r['date'])).days
        if delta <= 0:
            raise ValueError('Future or same-day evidence in private hybrid form')
        weight = 2 ** (-delta / half_life_days)
        for key in ('xg', 'xgq'):
            totals[key+'_for'] += weight * r[f'{our}_{key}']
            totals[key+'_against'] += weight * r[f'{opp}_{key}']
        weight_sum += weight
    return {'games': len(records), **{k: v / weight_sum for k,v in totals.items()}}


def shot_rates(prior, game, *, xgq_strength=0.0):
    """Adjusted home/away scoring intensities from xG xGA XGQ and opponent strength.

    Shrinks sparse team form back to contemporary same-league averages. Venue
    means are learned from completed league games, not invented home advantage.
    """
    if type(xgq_strength) not in (int, float) or not math.isfinite(xgq_strength) or not 0 <= xgq_strength <= 1:
        raise ValueError('Invalid XGQ shot-strength')
    day, league = game['date'], game['league']
    past = [r for r in prior if r['league'] == league and r['date'] < day and r['source'] == SOURCE]
    if len(past) < 40:
        return None
    h = _team_form(past, game['h'], day)
    a = _team_form(past, game['a'], day)
    if h is None or a is None:
        return None
    mean = sum(r['home_xg'] + r['away_xg'] for r in past) / (2*len(past))
    home_mean = sum(r['home_xg'] for r in past) / len(past)
    away_mean = sum(r['away_xg'] for r in past) / len(past)
    mean_q = sum(r['home_xgq'] + r['away_xgq'] for r in past) / (2*len(past))
    if mean <= .05 or mean_q <= 1e-6:
        return None

    def smoothed(team, field, baseline):
        # Six league-average pseudo-matches stabilise promotion/sparse form.
        return (team[field] * team['games'] + 6 * baseline) / (team['games'] + 6)

    def rate(att, defence, side_mean):
        a_xg = smoothed(att, 'xg_for', mean)
        d_xg = smoothed(defence, 'xg_against', mean)
        xg_ratio = _clip((a_xg / mean) * (d_xg / mean), .45, 2.3)
        if xgq_strength:
            a_q = smoothed(att, 'xgq_for', mean_q)
            d_q = smoothed(defence, 'xgq_against', mean_q)
            quality = _clip((a_q / mean_q) * (d_q / mean_q), .6, 1.6)
            xg_ratio *= quality ** xgq_strength
        return _clip(side_mean * xg_ratio, .2, 4.0)
    return rate(h, a, home_mean), rate(a, h, away_mean)


def hybrid_probs(prior, game, dc_probs, params):
    """Research model: combine independently learned goals and shot-based evidence.

    DC-only params are an explicit candidate. No fixture result enters the
    prediction, and caller must pass only prior-match DC probabilities.
    """
    if not isinstance(params, (tuple, list)) or len(params) != 2:
        raise ValueError('Invalid hybrid candidate')
    share, strength = params
    if (type(share) not in (int, float) or not math.isfinite(share) or
        not 0 <= share <= 1):
        raise ValueError('Invalid hybrid blend weight')
    if not isinstance(dc_probs, dict) or any(k not in dc_probs for k in ('home','draw','away')):
        raise ValueError('Missing goal baseline')
    if share == 0:
        return {k: float(dc_probs[k]) for k in ('home','draw','away')}
    rates = shot_rates(prior, game, xgq_strength=strength)
    if rates is None:
        return None
    shots = poisson_probabilities(*rates)
    result = {k: (1-share) * dc_probs[k] + share * shots[k] for k in ('home','draw','away')}
    total = sum(result.values())
    if not math.isfinite(total) or total <= 0:
        raise ValueError('Invalid hybrid probabilities')
    return {k: v / total for k,v in result.items()}
