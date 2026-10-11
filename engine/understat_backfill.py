"""Bounded, resumable private Understat history backfill for the five major leagues.

Backfills actual final league matches and per-shot xG only, after owner-confirmed
collection and storage rights. D1 retains only verified match summaries and rolling
team form. No public GitHub cache, no browser impersonation and no 403/429 bypass.
"""
from __future__ import annotations
import argparse
from collections import defaultdict, deque
from datetime import date, datetime, timedelta, timezone
import json
import time
from urllib.error import HTTPError, URLError
from .provider_understat import SOURCE, LEAGUES, fetch, match_index, parse_match, AccessDenied
from .understat_private import verified_row
from .team_form import team_profiles
from .understat_d1 import D1, D1Error

TARGET_MAX = 15_000
BATCH_MAX = 400


def validate_config(config):
    if not isinstance(config, dict) or config.get('enabled') is not True or config.get('owner_confirmed_collection_and_retention') is not True:
        raise PermissionError('Owner-confirmed collection AND storage authorization required in private D1')
    leagues=config.get('leagues')
    if not isinstance(leagues, list) or not leagues or len(set(leagues)) != len(leagues) or any(x not in LEAGUES for x in leagues):
        raise ValueError('Invalid private league selection')
    target=config.get('backfill_target', 10000)
    if type(target) is not int or not 1 <= target <= TARGET_MAX:
        raise ValueError('Private backfill target out of bounds')
    seasons=config.get('backfill_seasons', list(range(date.today().year, 2019, -1)))
    if not isinstance(seasons, list) or not 1 <= len(seasons) <= 13 or any(type(s) is not int or not 2014 <= s <= date.today().year for s in seasons) or len(set(seasons)) != len(seasons):
        raise ValueError('Invalid season cohort')
    return leagues, sorted(seasons, reverse=True), target


def prioritize(indexes, previous, budget):
    """Select newest not-yet-imported matches, balancing five leagues per round."""
    known_ids={r['source_match_id'] for r in previous}
    queues={}
    for league, indexed in indexes.items():
        seen=set()
        future=[]
        for row in sorted(indexed,key=lambda x:(x['date'],int(x['id'])), reverse=True):
            if row['id'] not in known_ids and row['id'] not in seen:
                seen.add(row['id'])
                future.append(row)
        queues[league]=deque(future)
    current={k:sum(r['league']==k for r in previous) for k in queues}
    selected=[]
    while len(selected)<budget and any(queues.values()):
        candidates=[league for league in queues if queues[league]]
        # Prefer undersampled leagues, then more recent dates. Deterministic tie-break.
        league=min(candidates,key=lambda x:(current[x],-int(queues[x][0]['date'].replace('-','')),x))
        selected.append(queues[league].popleft())
        current[league]+=1
    return selected


def backfill(db, *, max_new=250, min_interval=1.0, fetcher=fetch, clock=time.monotonic, sleeper=time.sleep, today=None):
    if type(max_new) is not int or not 1<=max_new<=BATCH_MAX:
        raise ValueError('Excessive per-run backfill request budget')
    if type(min_interval) not in (float,int) or not .5<=min_interval<=15:
        raise ValueError('Invalid request pacing')
    today=today or date.today()
    leagues,seasons,target=validate_config(db.get_setting())
    before=db.history()
    total=len(before)
    if total>=target:
        report={'status':'target_reached','target':target,'total':total,'added':0,'as_of':today.isoformat()}
        db.set_progress(report)
        return report
    budget=min(max_new,target-total,TARGET_MAX-total)
    last_request=None
    def paced_fetch(kind,ident):
        nonlocal last_request
        if last_request is not None:
            elapsed=clock()-last_request
            if elapsed<min_interval:sleeper(min_interval-elapsed)
        # Use monotonic at request end so each request is spaced.
        try:return fetcher(kind,ident)
        finally:last_request=clock()
    indexes=defaultdict(list)
    for league in leagues:
        for year in seasons:
            try:
                raw=paced_fetch('league',(league,year))
                indexes[league].extend(match_index(raw,league,year,today=today))
            except AccessDenied:
                raise
            except (HTTPError,URLError,TimeoutError,ValueError,KeyError,TypeError):
                # Missing historical season is allowed, but no silent fail if all fail.
                continue
    if not any(indexes.values()):
        raise RuntimeError('No verified Understat indexes accessible; leaving private D1 unchanged')
    candidates=prioritize(indexes,before,budget)
    added=[]; rejected=0; inspected=0
    by_league=defaultdict(int)
    # All selected IDs come from verified league indexes and strictly final matches.
    for item in candidates:
        try:
            row=verified_row(parse_match(item,paced_fetch('match',item['id'])))
            added.append(row)
            by_league[item['league']]+=1
        except AccessDenied:
            raise  # never bypass a denied or throttled source
        except (HTTPError,URLError,TimeoutError):
            raise RuntimeError('Understat transport unavailable: stopping safely') from None
        except (ValueError,KeyError,TypeError):
            rejected+=1
        inspected+=1
        if len(added)>=25:
            db.upsert_history(added)
            added.clear()
    if added:
        db.upsert_history(added)
    # Reload from D1 so history and computed forms are based on what is committed.
    all_rows=db.history()
    if len(all_rows) > TARGET_MAX:
        raise D1Error('Unexpected backfill size growth')
    profiles=team_profiles(all_rows,as_of=(today+timedelta(days=1)).isoformat(),source=SOURCE,min_games=1)
    db.upsert_forms(profiles)
    report={'status':'target_reached' if len(all_rows)>=target else 'progress',
            'target':target,'total':len(all_rows),'added':len(all_rows)-total,
            'rejected':rejected,'inspected':inspected,'profiles':len(profiles),
            'season_count':len(seasons),'by_league_imported':dict(by_league),
            'as_of':today.isoformat(),'completed_at':datetime.now(timezone.utc).isoformat()}
    db.set_progress(report)
    return report


def main(argv=None):
    ap=argparse.ArgumentParser()
    ap.add_argument('--max-new',type=int,default=250)
    ap.add_argument('--min-interval',type=float,default=1.0)
    args=ap.parse_args(argv)
    stats=backfill(D1(),max_new=args.max_new,min_interval=args.min_interval)
    # Counts only: no provider payload, tokens or private match identifiers in logs.
    print(json.dumps(stats,sort_keys=True))

if __name__=='__main__':
    main()
