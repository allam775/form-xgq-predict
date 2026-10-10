"""Isolated, private Understat match-summary persistence: zero public publication.

Only after verification of provider rights; D1 tables are private to the project.
D1 retains compact XGQ summaries, not raw shot payloads.
"""
from __future__ import annotations
import argparse
from datetime import date
import json
import math
from pathlib import Path
import re
from .provider_understat import SOURCE, LEAGUES
from .xgq import normalized

MAX_RECORDS = 20_000


def verified_row(row):
    if not isinstance(row, dict) or row.get('source') != SOURCE or row.get('league') not in LEAGUES:
        raise ValueError('Unexpected private Understat source')
    day = date.fromisoformat(row['date']).isoformat()
    home, away = normalized(row.get('home')), normalized(row.get('away'))
    if not home or not away or home == away or row.get('h') != home or row.get('a') != away:
        raise ValueError('Invalid Understat teams')
    if row.get('id') != f"{row['league']}|{day}|{home}|{away}":
        raise ValueError('Invalid Understat match identity')
    if not re.fullmatch(r'[1-9][0-9]{0,9}', str(row.get('source_match_id', ''))):
        raise ValueError('Invalid Understat match ID')
    for key in ('hg', 'ag'):
        if type(row.get(key)) is not int or not 0 <= row[key] <= 30:
            raise ValueError('Invalid score')
    for side in ('home', 'away'):
        n, xg, xgq = (row.get(side + suffix) for suffix in ('_shots', '_xg', '_xgq'))
        if type(n) is not int or not 1 <= n <= 150:
            raise ValueError('Invalid shot count')
        if any(type(x) not in (int, float) or not math.isfinite(x) for x in (xg, xgq)):
            raise ValueError('Invalid shot metrics')
        if not 0 <= xg <= n or not 0 <= xgq <= 1:
            raise ValueError('Invalid shot metrics range')
    return row


def decode(payload):
    if not isinstance(payload, list) or not payload:
        raise ValueError('Missing D1 confirmation')
    rows = []
    for entry in payload:
        if not isinstance(entry, dict) or entry.get('success') is not True or not isinstance(entry.get('results'), list):
            raise ValueError('Failed private D1 query')
        for item in entry['results']:
            if not isinstance(item, dict) or not isinstance(item.get('payload'), str):
                raise ValueError('Invalid private D1 payload')
            rows.append(verified_row(json.loads(item['payload'])))
            if len(rows) > MAX_RECORDS:
                raise ValueError('Private Understat history exceeds safety cap')
    if len({r['id'] for r in rows}) != len(rows):
        raise ValueError('Duplicate private history')
    return rows


def sql_quote(s):
    return "'" + str(s).replace("'", "''") + "'"


def export(rows, path):
    if not isinstance(rows, list):
        raise ValueError('Expected private history list')
    accepted = [verified_row(r) for r in rows if isinstance(r, dict) and r.get('source') == SOURCE]
    if len(accepted) > MAX_RECORDS or len({r['id'] for r in accepted}) != len(accepted):
        raise ValueError('Too many or duplicate private Understat rows')
    lines = ['INSERT OR REPLACE INTO private_understat_history(id,payload) VALUES (' +
             sql_quote(r['id']) + ',' + sql_quote(json.dumps(r, ensure_ascii=False, separators=(',', ':'))) + ');'
             for r in accepted]
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text('\n'.join(lines) + '\n' if lines else '-- No private Understat rows.\n', encoding='utf8')
    return len(lines)


def export_form(rows, destination, *, as_of=None):
    """Upsert private, derived per-team form into D1, without raw shots."""
    from .team_form import team_profiles
    profiles = team_profiles(rows, as_of=as_of, source=SOURCE, min_games=1)
    statements=[]
    for profile in profiles:
        key=f"{profile['league']}|{profile['team']}"
        statements.append('INSERT OR REPLACE INTO private_understat_form(id,payload) VALUES ('+
                          sql_quote(key)+','+sql_quote(json.dumps(profile, separators=(',',':')))+');')
    destination=Path(destination)
    destination.parent.mkdir(parents=True,exist_ok=True)
    destination.write_text('\n'.join(statements)+'\n' if statements else '-- No private Understat form.\n',encoding='utf8')
    return len(profiles)


def main(argv=None):
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='cmd', required=True)
    for action in ('decode', 'export', 'form'):
        p = sub.add_parser(action)
        p.add_argument('--input', required=True)
        p.add_argument('--output', required=True)
    opts = parser.parse_args(argv)
    payload = json.loads(Path(opts.input).read_text(encoding='utf8'))
    if opts.cmd == 'decode':
        rows = decode(payload)
        dest = Path(opts.output)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(rows, ensure_ascii=False), encoding='utf8')
        print(f'Restored {len(rows)} private Understat matches')
    elif opts.cmd == 'export':
        print(f'Prepared {export(payload, opts.output)} private Understat matches for D1')
    else:
        print(f'Prepared {export_form(payload, opts.output)} private Understat team profiles for D1')


if __name__ == '__main__':
    main()
