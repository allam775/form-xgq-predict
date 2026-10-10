"""Opt-in Understat per-shot xG adapter, not a claim of data-use permission.

A public code repository documenting an API does NOT license the source dataset.
The connector is disabled unless the owner confirms collection AND retention rights.
No spoofed browser headers, proxies, CAPTCHA workarounds, or 403/429 retries.
Never publish provider-derived match rows to the public GitHub repository.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
import gzip
import io
import json
import os
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .xgq import normalized, strict_row

SOURCE = 'Understat (private; permission required)'
HOST = 'https://understat.com'
LEAGUES = {'en.1': 'EPL', 'de.1': 'Bundesliga', 'es.1': 'La_Liga',
           'it.1': 'Serie_A', 'fr.1': 'Ligue_1'}
MAX_LEAGUES = 5
MAX_MATCHES = 48
MAX_BYTES = 6_000_000


class AccessDenied(RuntimeError):
    """Source denied access: caller must stop instead of working around it."""


def enabled(env=None):
    env = os.environ if env is None else env
    return all(env.get(k, '').strip().lower() in ('1', 'true', 'yes') for k in
               ('XGQ_UNDERSTAT_ACCESS_AUTHORIZED', 'XGQ_UNDERSTAT_STORAGE_AUTHORIZED'))


def read_leagues(value):
    if not isinstance(value, str) or len(value) > 120:
        raise ValueError('Invalid Understat league selection')
    items = [s.strip() for s in value.split(',') if s.strip()]
    if not items or len(items) > MAX_LEAGUES or len(set(items)) != len(items) or any(x not in LEAGUES for x in items):
        raise ValueError('Understat leagues must be unique, known competition IDs')
    return items


def fetch(kind, identifier, *, transport=None):
    """Fixed known paths; transport can be injected for offline tests.

    No dynamic origin, arbitrary URL, or endpoint enumeration.
    """
    if kind == 'league':
        if not isinstance(identifier, tuple) or len(identifier) != 2:
            raise ValueError('Expected (league, season)')
        league, season = identifier
        if league not in LEAGUES or type(season) is not int or not 2014 <= season <= date.today().year:
            raise ValueError('Invalid league or season')
        path = f'/getLeagueData/{LEAGUES[league]}/{season}'
    elif kind == 'match':
        mid = str(identifier)
        if not re.fullmatch(r'[1-9][0-9]{0,9}', mid):
            raise ValueError('Invalid Understat match ID')
        path = f'/getMatchData/{mid}'
    else:
        raise ValueError('Undocumented endpoint')
    if transport is not None:
        result = transport(HOST + path)
        if not isinstance(result, dict):
            raise ValueError('Expected JSON object')
        return result
    # Honest UA; a standard AJAX marker, without pretending to be a browser.
    req = Request(HOST + path, headers={
        'Accept': 'application/json',
        'X-Requested-With': 'XMLHttpRequest',
        'User-Agent': 'FORM-XGQ-private-research/1.0 (contact: project owner)',
    })
    try:
        with urlopen(req, timeout=18) as response:
            raw = response.read(MAX_BYTES + 1)
    except HTTPError as exc:
        if exc.code in (401, 403, 429):
            raise AccessDenied(f'Understat denied the request: HTTP {exc.code}; no retry or bypass') from exc
        raise
    if len(raw) > MAX_BYTES:
        raise ValueError('Understat response too large')
    # Understat can send GZIP even when the client did not ask for compression.
    # Bound the *decompressed* size as well; never permit a zip-bomb response.
    if raw.startswith(b'\x1f\x8b'):
        with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
            raw = stream.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError('Understat decoded response too large')
    result = json.loads(raw)
    if not isinstance(result, dict):
        raise ValueError('Expected JSON object')
    return result


def _score(value):
    if type(value) is int and 0 <= value <= 30:
        return value
    if isinstance(value, str) and re.fullmatch(r'(?:[0-9]|[12][0-9]|30)', value.strip()):
        return int(value.strip())
    raise ValueError('Invalid final match score')


def _shot_xg(shot, side, mid):
    if not isinstance(shot, dict):
        raise ValueError('Malformed shot entry')
    if shot.get('h_a') != side:
        raise ValueError('Shot side does not match team')
    if str(shot.get('match_id', mid)) != mid:
        raise ValueError('Shot belongs to another match')
    xg = shot.get('xG')
    if isinstance(xg, bool):
        raise ValueError('Invalid shot xG')
    if isinstance(xg, str):
        if not re.fullmatch(r'(?:0(?:\.[0-9]+)?|1(?:\.0+)?)', xg.strip()):
            raise ValueError('Invalid shot probability string')
        xg = float(xg)
    if type(xg) not in (int, float) or not 0 <= xg <= 1:
        raise ValueError('Invalid shot xG value')
    return xg


def match_index(league_json, league, season, *, today=None):
    """Return only confirmed final LEAGUE matches; don't infer cups/friendlies."""
    if league not in LEAGUES or type(season) is not int:
        raise ValueError('Invalid league selection')
    if not isinstance(league_json, dict) or not isinstance(league_json.get('dates'), list):
        raise ValueError('Understat league index lacks dates')
    limit = (today or date.today()).isoformat()
    matches = []
    seen = set()
    for m in league_json['dates']:
        if not isinstance(m, dict):
            raise ValueError('Unexpected league index match')
        mid = str(m.get('id', ''))
        if not re.fullmatch(r'[1-9][0-9]{0,9}', mid) or mid in seen:
            raise ValueError('Invalid/duplicate league match ID')
        seen.add(mid)
        if m.get('isResult') is not True:
            continue
        raw_date = m.get('datetime', '')
        if not isinstance(raw_date, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}(?:[ T].*)?', raw_date):
            raise ValueError('Invalid match datetime')
        when = date.fromisoformat(raw_date[:10]).isoformat()
        if when > limit:
            continue
        h, a, goals = m.get('h'), m.get('a'), m.get('goals')
        if not isinstance(h, dict) or not isinstance(a, dict) or not isinstance(goals, dict):
            raise ValueError('Missing final league score or teams')
        home, away = h.get('title'), a.get('title')
        if not isinstance(home, str) or not isinstance(away, str) or not normalized(home) or not normalized(away) or normalized(home) == normalized(away):
            raise ValueError('Invalid team identity')
        if not re.fullmatch(r'[1-9][0-9]*', str(h.get('id', ''))) or not re.fullmatch(r'[1-9][0-9]*', str(a.get('id', ''))):
            raise ValueError('Missing team ID')
        matches.append({'id': mid, 'league': league, 'season': season, 'date': when,
                        'home': home, 'away': away,
                        'home_id': str(h['id']), 'away_id': str(a['id']),
                        'hg': _score(goals.get('h')), 'ag': _score(goals.get('a'))})
    return sorted(matches, key=lambda r: (r['date'], int(r['id'])))


def parse_match(indexed, match_json):
    """Validate all shot events, source identities and scores; then discard raw shots."""
    if not isinstance(indexed, dict) or not isinstance(match_json, dict):
        raise ValueError('Invalid indexed match / response')
    shots = match_json.get('shots')
    if not isinstance(shots, dict) or any(not isinstance(shots.get(k), list) for k in ('h', 'a')):
        raise ValueError('Missing full shot arrays')
    mid = indexed['id']
    # Match detail must be tied to the competition index. Shot IDs alone do not prove completion.
    home = [_shot_xg(item, 'h', mid) for item in shots['h']]
    away = [_shot_xg(item, 'a', mid) for item in shots['a']]
    row = strict_row({'league': indexed['league'], 'date': indexed['date'],
        'home_team': indexed['home'], 'away_team': indexed['away'],
        'home_goals': indexed['hg'], 'away_goals': indexed['ag'],
        'home_shots_xg': home, 'away_shots_xg': away,
        'source': SOURCE, 'source_match_id': mid})
    # Require that score and shot goal count agree when source labels all goals.
    for side, goals in (('h', indexed['hg']), ('a', indexed['ag'])):
        listed = shots[side]
        # Own goals are not credited as shots, so shot Goals may be fewer than final goals.
        shot_goals = sum(s.get('result') == 'Goal' for s in listed)
        if shot_goals > goals:
            raise ValueError('Shot goals contradict final score')
    return row


def collect(existing, leagues, seasons, *, max_new=24, transport=None, today=None):
    """Collect only indexed final matches, with a strict fixed request budget."""
    if not isinstance(existing, list) or not isinstance(seasons, list) or len(seasons) not in (1, 2):
        raise ValueError('Invalid Understat collector arguments')
    if type(max_new) is not int or not 0 <= max_new <= MAX_MATCHES:
        raise ValueError('Excessive request budget')
    if len(seasons) != len(set(seasons)) or any(type(y) is not int or y < 2014 or y > date.today().year for y in seasons):
        raise ValueError('Invalid years')
    if not leagues or len(leagues) != len(set(leagues)) or any(l not in LEAGUES for l in leagues):
        raise ValueError('Invalid leagues')
    stored = {r['id']: r for r in existing}
    known_source_ids = {r['source_match_id'] for r in existing if r.get('source') == SOURCE}
    reported = {'source': 'Understat (private)', 'added': 0, 'rejected': 0, 'inspected': 0,
                'candidate_finals': 0, 'leagues': leagues, 'seasons': seasons}
    # Prefer most recent year first for up-to-date team form; earliest first within year.
    candidates = []
    for league in leagues:
        for year in sorted(seasons, reverse=True):
            indexed = match_index(fetch('league', (league, year), transport=transport), league, year, today=today)
            candidates.extend(indexed)
    # De-duplicate across overlapping season indexes before issuing detail requests.
    fresh = []
    seen_ids = set(known_source_ids)
    for candidate in sorted(candidates, key=lambda r: (r['date'], int(r['id'])), reverse=True):
        if candidate['id'] not in seen_ids:
            fresh.append(candidate)
            seen_ids.add(candidate['id'])
    # Round-robin by league so a busy league cannot consume the whole budget.
    # Each league's matches remain newest-first for timely rolling team form.
    buckets = {league: [] for league in leagues}
    for candidate in fresh:
        buckets[candidate['league']].append(candidate)
    selected = []
    for idx in range(max((len(queue) for queue in buckets.values()), default=0)):
        for league in leagues:
            if idx < len(buckets[league]):
                selected.append(buckets[league][idx])
                if len(selected) >= max_new:
                    break
        if len(selected) >= max_new:
            break
    reported['candidate_finals'] = len(fresh)
    reported['selected_by_league'] = {league: sum(x['league'] == league for x in selected)
                                      for league in leagues}
    # No more than 48 detail fetches in one run. Don't skip rejected IDs by retrying indefinitely.
    for m in selected:
        reported['inspected'] += 1
        try:
            row = parse_match(m, fetch('match', m['id'], transport=transport))
            if row['id'] in stored and stored[row['id']]['source'] != SOURCE:
                # Never silently replace a different xG provider or mix xG scales.
                reported['rejected'] += 1
                continue
            stored[row['id']] = row
            known_source_ids.add(m['id'])
            reported['added'] += 1
        except (ValueError, KeyError, TypeError) as exc:
            reported['rejected'] += 1
    return list(stored.values()), reported
