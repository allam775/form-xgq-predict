"""Private, source-homogeneous team form from VERIFIED matches, not invented shots.

Rolling snapshots are calculated as-of a date; no match on/after it can leak.
Separate Understat and StatsBomb xG scales. Outputs are derived numerical summaries.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from .xgq import normalized

WINDOWS = (5, 10, 20)


def team_profiles(rows, *, as_of=None, source=None, min_games=1, include_completed_today=False):
    if not isinstance(rows, list):
        raise ValueError('Expected verified compact match history')
    as_of = as_of or date.today().isoformat()
    date.fromisoformat(as_of)
    if type(min_games) is not int or not 1 <= min_games <= 20:
        raise ValueError('Invalid minimum games')
    groups = defaultdict(list)
    for r in rows:
        if not isinstance(r, dict) or source and r.get('source') != source:
            continue
        # Forecast backtests must NEVER use same-day data. A private post-match
        # dashboard may include today's results only after the source marked FINAL.
        match_date = r.get('date', '')
        if match_date > as_of if include_completed_today else match_date >= as_of:
            continue
        for home in (True, False):
            side = 'h' if home else 'a'
            team = r.get(side)
            if not isinstance(team, str) or not team:
                raise ValueError('Malformed normalized team')
            goals_for, goals_against = (r['hg'], r['ag']) if home else (r['ag'], r['hg'])
            atk, opp = ('home', 'away') if home else ('away', 'home')
            groups[(r['source'], r['league'], team)].append({
                'date': r['date'], 'home': home, 'opponent': r['a' if home else 'h'],
                'goals_for': goals_for, 'goals_against': goals_against,
                'xg_for': r[f'{atk}_xg'], 'xg_against': r[f'{opp}_xg'],
                'xgq_for': r[f'{atk}_xgq'], 'xgq_against': r[f'{opp}_xgq'],
                'shots_for': r[f'{atk}_shots'], 'shots_against': r[f'{opp}_shots']})
    output = []
    for (src, league, team), games in sorted(groups.items()):
        games.sort(key=lambda x: x['date'], reverse=True)
        if len(games) < min_games:
            continue
        result = {'source': src, 'league': league, 'team': team, 'as_of': as_of,
                  'last_seen': games[0]['date'], 'verified_games': len(games), 'windows': {}}
        for n in WINDOWS:
            window = games[:n]
            k = len(window)
            if k < min_games:
                continue
            stats = {}
            for name in ('goals_for','goals_against','xg_for','xg_against','xgq_for','xgq_against','shots_for','shots_against'):
                stats[name] = round(sum(x[name] for x in window) / k, 5)
            stats['n'] = k
            stats['wins'] = sum(g['goals_for'] > g['goals_against'] for g in window)
            stats['draws'] = sum(g['goals_for'] == g['goals_against'] for g in window)
            stats['losses'] = k - stats['wins'] - stats['draws']
            stats['home_games'] = sum(g['home'] for g in window)
            stats['away_games'] = k - stats['home_games']
            result['windows'][str(n)] = stats
        output.append(result)
    return output


def select_history_for_fixture(history, fixture, today):
    """Never mix xG models within a league prediction.

    Prefer same-source rows with recent eligible team data and >=40 league games.
    No source receives a fake/aggregated xG to satisfy the model threshold.
    """
    league, day = fixture['league'], fixture['date']
    h, a = normalized(fixture['home_team']), normalized(fixture['away_team'])
    cohorts = defaultdict(list)
    for row in history:
        if row['league'] == league and row['date'] < day and row['date'] < today:
            cohorts[row['source']].append(row)
    candidates = []
    for src, rows in cohorts.items():
        # Exact team match; normalized aliases must be explicitly resolved upstream.
        hrows = sorted((r for r in rows if r['h'] == h or r['a'] == h), key=lambda r:r['date'], reverse=True)
        arows = sorted((r for r in rows if r['h'] == a or r['a'] == a), key=lambda r:r['date'], reverse=True)
        if not hrows or not arows:
            continue
        age_h = (date.fromisoformat(today) - date.fromisoformat(hrows[0]['date'])).days
        age_a = (date.fromisoformat(today) - date.fromisoformat(arows[0]['date'])).days
        usable = len(hrows) >= 5 and len(arows) >= 5 and max(age_h, age_a) <= 120
        # Determine genuine 900-day league baseline without any invented games.
        from datetime import timedelta
        eligible_league = sum(r['date'] >= (date.fromisoformat(day)-timedelta(days=900)).isoformat() for r in rows)
        complete = usable and eligible_league >= 40
        candidates.append((int(complete), min(len(hrows),len(arows)), -max(age_h,age_a), eligible_league, src, rows))
    if not candidates:
        return [], None
    candidates.sort(key=lambda c:(c[0],c[1],c[2],c[3],c[4]), reverse=True)
    return candidates[0][-1], candidates[0][-2]
