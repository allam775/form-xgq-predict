"""Private Cloudflare D1 interface for authorized Understat backfill.

Reads and writes compact match summaries only. No raw per-shot provider payload is
retained; no public GitHub data file is written. Tokens never enter logs.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from .understat_private import verified_row
from .provider_understat import SOURCE
from datetime import date, timedelta

PAGE = 250
MAX_RESPONSE = 4_000_000


class D1Error(RuntimeError):
    pass


class D1:
    def __init__(self, *, account=None, database=None, token=None, transport=None):
        self.account = account or os.getenv('CLOUDFLARE_ACCOUNT_ID', '')
        self.database = database or os.getenv('CF_D1_DATABASE_ID', '')
        self.token = token or os.getenv('CLOUDFLARE_API_TOKEN', '')
        self.transport = transport
        if not re.fullmatch(r'[0-9a-fA-F]{32}', self.account) or not re.fullmatch(r'[0-9a-fA-F-]{36}', self.database):
            raise D1Error('Cloudflare account / D1 database identity not configured')
        if not self.token and transport is None:
            raise D1Error('Cloudflare API token missing')

    def query(self, sql, params=()):
        if not isinstance(sql, str) or len(sql) > 50_000 or not isinstance(params, (tuple, list)):
            raise D1Error('Invalid private D1 statement')
        payload = {'sql': sql, 'params': list(params)}
        if self.transport is not None:
            result = self.transport(payload)
        else:
            url = (f'https://api.cloudflare.com/client/v4/accounts/{self.account}/d1/'
                   f'database/{self.database}/query')
            req = Request(url, data=json.dumps(payload, separators=(',', ':')).encode(),
                          headers={'Authorization': 'Bearer '+self.token,
                                   'Content-Type': 'application/json'}, method='POST')
            try:
                with urlopen(req, timeout=35) as response:
                    raw = response.read(MAX_RESPONSE+1)
            except HTTPError as exc:
                raise D1Error(f'Private D1 HTTP error {exc.code}; stopped safely') from None
            except (URLError, TimeoutError):
                raise D1Error('Private D1 connection unavailable; stopped safely') from None
            if len(raw) > MAX_RESPONSE:
                raise D1Error('Private D1 response exceeded size limit')
            result = json.loads(raw)
        if (not isinstance(result, dict) or result.get('success') is not True or
                not isinstance(result.get('result'), list) or not result['result'] or
                result['result'][0].get('success') is not True or
                not isinstance(result['result'][0].get('results'), list)):
            raise D1Error('Private D1 query unsuccessful; no publish attempted')
        return result['result'][0]['results']

    def get_setting(self):
        rows = self.query("SELECT v FROM metadata WHERE k='understat_collection_config' LIMIT 1")
        if len(rows) != 1 or not isinstance(rows[0].get('v'), str):
            return None
        try:
            return json.loads(rows[0]['v'])
        except (ValueError, TypeError):
            raise D1Error('Invalid private Understat configuration') from None

    def history(self):
        """Paginate beyond the D1 row cap. Never silently return a partial history."""
        rows=[]
        offset=0
        while True:
            page=self.query('SELECT payload FROM private_understat_history ORDER BY id LIMIT ? OFFSET ?', (PAGE, offset))
            for rec in page:
                if not isinstance(rec.get('payload'), str):
                    raise D1Error('Malformed private history payload')
                rows.append(verified_row(json.loads(rec['payload'])))
            if len(rows) > 20_000:
                raise D1Error('Understat private history exceeds maximum safe size')
            if len(page) < PAGE:
                break
            offset += len(page)
        if len({r['id'] for r in rows}) != len(rows):
            raise D1Error('Duplicate private rows; refusing backfill')
        return rows

    def upsert_history(self, rows):
        if not rows:
            return 0
        if len(rows) > 50:
            raise D1Error('Too many rows in one D1 write')
        verified=[verified_row(r) for r in rows]
        sql='INSERT OR REPLACE INTO private_understat_history(id,payload) VALUES '+','.join(['(?,?)']*len(verified))
        params=[]
        for row in verified:
            params.extend((row['id'], json.dumps(row, separators=(',', ':'), ensure_ascii=False)))
        self.query(sql, params)
        return len(verified)

    def upsert_forms(self, profiles):
        for i in range(0, len(profiles), 50):
            chunk=profiles[i:i+50]
            sql='INSERT OR REPLACE INTO private_understat_form(id,payload) VALUES '+','.join(['(?,?)']*len(chunk))
            params=[]
            for profile in chunk:
                params.extend((profile['league']+'|'+profile['team'], json.dumps(profile, separators=(',', ':'), ensure_ascii=False)))
            self.query(sql, params)
        return len(profiles)

    def set_progress(self, data):
        self.query("INSERT OR REPLACE INTO metadata(k,v) VALUES('understat_backfill_progress',?)",
                   (json.dumps(data, separators=(',', ':')),))


def main(argv=None):
    ap=argparse.ArgumentParser()
    actions=ap.add_subparsers(dest='cmd',required=True)
    p=actions.add_parser('restore')
    p.add_argument('--output',required=True)
    p=actions.add_parser('sync')
    p.add_argument('--input',required=True)
    args=ap.parse_args(argv)
    db=D1()
    if args.cmd=='restore':
        rows=db.history()
        destination=Path(args.output)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(rows, ensure_ascii=False), encoding='utf8')
        print(f'Restored {len(rows)} private authorized match summaries (paginated)')
    elif args.cmd=='sync':
        from .team_form import team_profiles
        raw=json.loads(Path(args.input).read_text(encoding='utf8'))
        if not isinstance(raw,list):raise D1Error('Expected match history list')
        candidate=[verified_row(r) for r in raw if isinstance(r,dict) and r.get('source')==SOURCE]
        previous={r['id']:r for r in db.history()}
        delta=[r for r in candidate if previous.get(r['id'])!=r]
        for index in range(0,len(delta),50):db.upsert_history(delta[index:index+50])
        history=db.history()
        profiles=team_profiles(history,as_of=(date.today()+timedelta(days=1)).isoformat(),source=SOURCE,min_games=1)
        db.upsert_forms(profiles)
        print(f'Updated {len(delta)} private Understat matches; {len(history)} total; {len(profiles)} team profiles')

if __name__=='__main__':
    main()
