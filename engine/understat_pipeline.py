"""Rights-gated incremental Understat pipeline: private D1, no public cache.

Authorized collection only. Restore from private D1 before fetching each run.
Never fall back to aggregate xG, and never use StatsBomb xG in Understat form.
"""
from __future__ import annotations
from datetime import date
import json
import os
from pathlib import Path

from .provider_understat import SOURCE, enabled, read_leagues, collect
from .understat_private import verified_row

ROOT = Path(__file__).resolve().parents[1]


def run(history, *, env=None, asof=None, private_path=None, transport=None):
    env = os.environ if env is None else env
    selection = env.get('XGQ_UNDERSTAT_LEAGUES', '').strip()
    if not selection:
        return history, {'enabled': False}
    if not enabled(env):
        raise PermissionError('Understat collection/storage rights are not confirmed: connector remains disabled')
    leagues = read_leagues(selection)
    today = asof or date.today()
    if not isinstance(today, date):
        raise ValueError('Invalid as-of date')
    private_path = Path(private_path) if private_path else ROOT / 'data' / 'private_understat_history.json'
    if not private_path.exists():
        raise RuntimeError('Understat private D1 restore required; refusing history loss')
    previous = json.loads(private_path.read_text(encoding='utf8'))
    if not isinstance(previous, list):
        raise ValueError('Malformed private Understat D1 data')
    stored = {r['id']: r for r in history}
    for row in previous:
        verified_row(row)
        if row['id'] in stored and stored[row['id']]['source'] != SOURCE:
            raise ValueError('Cross-provider identity collision')
        stored[row['id']] = row
    count = env.get('XGQ_UNDERSTAT_MAX_NEW', '24')
    if not count.isdecimal() or not 0 <= int(count) <= 48:
        raise ValueError('Understat request budget must be between 0 and 48')
    current_start = today.year if today.month >= 7 else today.year-1
    years = [current_start, current_start - 1]
    rows, report = collect(list(stored.values()), leagues, years,
                           max_new=int(count), transport=transport, today=today)
    report.update(enabled=True, rights_confirmed_by_owner=True,
                  restored_private=len(previous),
                  private_rows=sum(r.get('source') == SOURCE for r in rows))
    return rows, report
