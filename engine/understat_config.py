"""Owner-controlled Understat permissions stored only in private Cloudflare D1 metadata.

This module processes Wrangler's D1 JSON SELECT output, not provider responses.
It writes *non-secret* bounded runtime flags to a GitHub Actions env file.
Missing or revoked permission fails closed: no Understat collection.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .provider_understat import read_leagues

KEY = 'understat_collection_config'


def authorized_config(d1_result):
    if not isinstance(d1_result, list) or len(d1_result) != 1:
        raise ValueError('D1 opt-in lookup missing or ambiguous')
    entry = d1_result[0]
    if not isinstance(entry, dict) or entry.get('success') is not True or not isinstance(entry.get('results'), list):
        raise ValueError('D1 opt-in lookup failed')
    rows = entry['results']
    if not rows:
        return None
    if len(rows) != 1 or not isinstance(rows[0], dict) or not isinstance(rows[0].get('v'), str):
        raise ValueError('Invalid D1 opt-in record')
    config = json.loads(rows[0]['v'])
    if not isinstance(config, dict):
        raise ValueError('Invalid Understat opt-in format')
    if config.get('enabled') is not True:
        return None
    if config.get('owner_confirmed_collection_and_retention') is not True:
        raise PermissionError('Owner has not confirmed both collection and storage rights')
    raw_leagues = config.get('leagues')
    if not isinstance(raw_leagues, list) or any(not isinstance(x, str) for x in raw_leagues):
        raise ValueError('Invalid authorized league list')
    leagues = read_leagues(','.join(raw_leagues))
    max_new = config.get('max_new', 24)
    if type(max_new) is not int or not 1 <= max_new <= 48:
        raise ValueError('Understat collection budget must be 1..48')
    return {'leagues': ','.join(leagues), 'max_new': max_new}


def write_github_env(config, file):
    file = Path(file)
    if config is None:
        print('Understat private collection disabled by owner configuration')
        return False
    lines = [
        'XGQ_UNDERSTAT_ACCESS_AUTHORIZED=1',
        'XGQ_UNDERSTAT_STORAGE_AUTHORIZED=1',
        'XGQ_UNDERSTAT_LEAGUES=' + config['leagues'],
        'XGQ_UNDERSTAT_MAX_NEW=' + str(config['max_new']),
    ]
    with file.open('a', encoding='utf-8') as out:
        out.write('\n'.join(lines) + '\n')
    print('Understat owner opt-in: active for ' + str(len(config['leagues'].split(','))) +
          ' leagues, max ' + str(config['max_new']) + ' matches per refresh')
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', required=True)
    parser.add_argument('--github-env', required=True)
    args = parser.parse_args()
    payload = json.loads(Path(args.input).read_text(encoding='utf-8'))
    write_github_env(authorized_config(payload), args.github_env)


if __name__ == '__main__':
    main()
