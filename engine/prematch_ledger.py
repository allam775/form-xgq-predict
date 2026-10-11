"""Immutable, private forward forecast ledger for 2026-10-11 five-league fixtures.

Only final matches strictly before today's kickoff date inform forecasts.
The experimental decision rule was fixed using HISTORICAL test outcomes and must
not be described as prospectively validated. Never forge predictions after kickoff.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
from itertools import groupby
import json
import math

from .understat_d1 import D1
from .provider_understat import SOURCE
from .understat_private import verified_row
from .understat_championship import _dc_baseline, _elo_probs, _update_elo_batch
from .understat_hybrid import hybrid_probs
from .xgq import normalized, predict_xgq

FIXTURE_DATE = '2026-10-11'
# Independent competition schedule identifiers, kickoffs confirmed at 2026-10-11T04:49Z.
# Times are UTC (Egypt = UTC+3). Never edit this list after first publication.
# Schema: fixture ID, league, home ID, away ID, kickoff UTC, English display names.
FIXTURES = (
    (72221300, 'en.1', 'crystal palace', 'nottingham forest', '2026-10-11T13:00:00+00:00', 'Crystal Palace', 'Nottingham Forest'),
    (72221302, 'en.1', 'hull', 'everton', '2026-10-11T13:00:00+00:00', 'Hull City', 'Everton'),
    (72221306, 'en.1', 'liverpool', 'manchester city', '2026-10-11T15:30:00+00:00', 'Liverpool', 'Manchester City'),
    (72478610, 'es.1', 'elche', 'celta vigo', '2026-10-11T12:00:00+00:00', 'Elche', 'Celta Vigo'),
    (72478624, 'es.1', 'real sociedad', 'deportivo la coruna', '2026-10-11T14:15:00+00:00', 'Real Sociedad', 'Deportivo La Coruña'),
    (72478608, 'es.1', 'real betis', 'osasuna', '2026-10-11T16:30:00+00:00', 'Real Betis', 'Osasuna'),
    (72478618, 'es.1', 'racing santander', 'valencia', '2026-10-11T19:00:00+00:00', 'Racing Santander', 'Valencia'),
    (71945290, 'it.1', 'como', 'roma', '2026-10-11T10:30:00+00:00', 'Como', 'Roma'),
    (71945296, 'it.1', 'lazio', 'monza', '2026-10-11T13:00:00+00:00', 'Lazio', 'Monza'),
    (71945298, 'it.1', 'lecce', 'bologna', '2026-10-11T13:00:00+00:00', 'Lecce', 'Bologna'),
    (71945302, 'it.1', 'sassuolo', 'ac milan', '2026-10-11T16:00:00+00:00', 'Sassuolo', 'AC Milan'),
    (71945288, 'it.1', 'cagliari', 'juventus', '2026-10-11T18:45:00+00:00', 'Cagliari', 'Juventus'),
    (72513234, 'de.1', 'cologne', 'borussia m gladbach', '2026-10-11T13:30:00+00:00', 'Cologne', 'Borussia Mönchengladbach'),
    (72513226, 'de.1', 'freiburg', 'schalke 04', '2026-10-11T15:30:00+00:00', 'Freiburg', 'Schalke 04'),
    (72036212, 'fr.1', 'nice', 'strasbourg', '2026-10-11T13:00:00+00:00', 'Nice', 'Strasbourg'),
    (72036216, 'fr.1', 'rennes', 'auxerre', '2026-10-11T15:15:00+00:00', 'Rennes', 'Auxerre'),
    (72036218, 'fr.1', 'troyes', 'marseille', '2026-10-11T18:45:00+00:00', 'Troyes', 'Marseille'),
)

LEDGER_TABLE = 'private_prematch_forecasts_20261011'
GRADE_TABLE = 'private_prematch_grades_20261011'
OUTCOMES = ('home','draw','away')


def fixture_dict(spec):
    fid, league, home, away, utc, home_name, away_name = spec
    assert fid > 0 and league and normalized(home_name) and normalized(away_name)
    return {'id':f'{FIXTURE_DATE}|{league}|{fid}', 'date':FIXTURE_DATE,'league':league,
            'source_fixture_id':fid,'h':home,'a':away,'home':home_name,'away':away_name,
            'kickoff_utc':utc}


def normalize_probabilities(p):
    if not p or set(p) != set(OUTCOMES) or any(not isinstance(v,(float,int)) or not math.isfinite(v) or v < 0 for v in p.values()):
        raise ValueError('Missing/non-finite 1X2 probability')
    total=sum(p.values())
    if total<=0:raise ValueError('Zero 1X2 probability')
    return {k:round(p[k]/total,8) for k in OUTCOMES}


def research_52(elo, hybrid):
    # Fixed research-only test-selected formula: known hindsight overfit.
    p={k:.25*elo[k]+.75*hybrid[k] for k in OUTCOMES}
    return normalize_probabilities({'home':.88*p['home'],'draw':1.28*p['draw'],'away':p['away']})


def _ratings_by_league(before):
    grouped=defaultdict(list)
    for r in before: grouped[r['league']].append(r)
    ratings={}
    for league, games in grouped.items():
        rating={}
        for _, batch in groupby(sorted(games,key=lambda r:(r['date'],r['id'])),key=lambda r:r['date']):
            _update_elo_batch(rating, list(batch))
        ratings[league]=rating
    return ratings


def create_forward_rows(rows, *, now=None):
    now=now or datetime.now(timezone.utc)
    if now.tzinfo is None:raise ValueError('Forecast creation needs timezone-aware timestamp')
    now=now.astimezone(timezone.utc)
    # Source includes completed match summaries on/after target? Never use them.
    before=sorted((verified_row(r) for r in rows if r['date'] < FIXTURE_DATE),key=lambda r:(r['league'],r['date'],r['id']))
    if any(r['source']!=SOURCE for r in before):raise ValueError('Mixed xG providers')
    history_id=sha256(json.dumps([(r['id'],r['source_match_id'],r['hg'],r['ag'],r['home_xgq'],r['away_xgq']) for r in before],separators=(',',':')).encode()).hexdigest()
    pools=defaultdict(list)
    for r in before:pools[r['league']].append(r)
    ratings=_ratings_by_league(before)
    result=[]
    for spec in FIXTURES:
        game=fixture_dict(spec)
        kickoff=datetime.fromisoformat(game['kickoff_utc'])
        if kickoff.date()!=date.fromisoformat(FIXTURE_DATE):raise ValueError('Incorrect fixture date')
        ledger={'id':game['id'],'date':game['date'],'league':game['league'],
                'source_fixture_id':game['source_fixture_id'],'home':game['home'],'away':game['away'],
                'home_id':game['h'],'away_id':game['a'],'kickoff_utc':game['kickoff_utc'],
                'frozen_at_utc':now.isoformat(),'prior_evidence_date_lt':game['date'],
                'understat_source':SOURCE,'history_sha256':history_id,
                'history_total':len(before),'production_unchanged':True,
                'research52_hindsight_selected':True,'status':None}
        if kickoff <= now:
            ledger.update(status='missed_pre_kickoff_deadline',reason='No retrospective forecast allowed')
            result.append(ledger);continue
        prior=pools[game['league']]
        club_counts={t:sum(t in (r['h'],r['a']) for r in prior) for t in (game['h'],game['a'])}
        ledger['prior_team_games']={'home':club_counts[game['h']],'away':club_counts[game['a']]}
        if len(prior)<40 or min(club_counts.values())<5:
            ledger.update(status='withheld',reason='insufficient_verified_team_history')
            result.append(ledger);continue
        dc=_dc_baseline(prior,game)
        elo=_elo_probs(prior,ratings.get(game['league'],{}),game)
        baseline, xg_reason=predict_xgq({'league':game['league'],'date':game['date'],
             'home_team':game['h'],'away_team':game['a']},prior,FIXTURE_DATE)
        # If either model is absent, do not substitute invented values.
        goal_shot=hybrid_probs(prior,game,dc,(.50,.0)) if dc else None
        research_hybrid=hybrid_probs(prior,game,dc,(.35,.30)) if dc else None
        if not all((dc,elo,goal_shot,research_hybrid,baseline)):
            ledger.update(status='withheld',reason=xg_reason or 'missing_model_evidence')
            result.append(ledger);continue
        models={'xgq_production_formula':{k:baseline['probabilities'][k] for k in OUTCOMES},
                'goal_fixed_rho':dc,'elo':elo,'hybrid_393_validation':research_hybrid,
                'exploratory_52_test_selected':research_52(elo,goal_shot)}
        ledger['models']={k:normalize_probabilities(v) for k,v in models.items()}
        ledger['picks']={k:max(OUTCOMES,key=lambda y:vals[y]) for k,vals in ledger['models'].items()}
        ledger.update(status='frozen',reason=None)
        result.append(ledger)
    return result


def ensure_tables(db):
    db.query(f'CREATE TABLE IF NOT EXISTS {LEDGER_TABLE}(id TEXT PRIMARY KEY, payload TEXT NOT NULL)')
    db.query(f'CREATE TABLE IF NOT EXISTS {GRADE_TABLE}(id TEXT PRIMARY KEY, payload TEXT NOT NULL)')


def freeze(db, *, now=None):
    now=now or datetime.now(timezone.utc)
    ensure_tables(db)
    # Reusing prior entries is allowed; INSERT OR IGNORE means no future overwrites.
    existing=db.query(f'SELECT id FROM {LEDGER_TABLE}')
    if len(existing)==len(FIXTURES):
        return {'status':'already_frozen','saved':len(existing),'frozen':len([r for r in db.query(f'SELECT payload FROM {LEDGER_TABLE}') if json.loads(r['payload']).get('status')=='frozen'])}
    existing_ids={r['id'] for r in existing}
    rows=create_forward_rows(db.history(),now=now)
    if len(rows)!=len(FIXTURES):raise RuntimeError('Incomplete day fixture count')
    for record in rows:
        if record['id'] in existing_ids:
            continue  # An earlier frozen forecast must never be overwritten.
        db.query(f'INSERT OR IGNORE INTO {LEDGER_TABLE}(id,payload) VALUES(?,?)',
                 (record['id'],json.dumps(record,separators=(',',':'),ensure_ascii=False)))
    actual=db.query(f'SELECT COUNT(*) AS n FROM {LEDGER_TABLE}')
    if actual[0]['n']!=len(FIXTURES):raise RuntimeError('Incomplete ledger persisted')
    saved=[json.loads(r['payload']) for r in db.query(f'SELECT payload FROM {LEDGER_TABLE}')]
    return {'status':'frozen','saved':len(saved),'frozen':sum(r['status']=='frozen' for r in saved),
            'withheld':sum(r['status']=='withheld' for r in saved),
            'missed':sum(r['status']=='missed_pre_kickoff_deadline' for r in saved),
            'frozen_at':now.isoformat()}


def grade(db, *, now=None):
    now=now or datetime.now(timezone.utc)
    ensure_tables(db)
    saved=[json.loads(r['payload']) for r in db.query(f'SELECT payload FROM {LEDGER_TABLE} ORDER BY id')]
    history=db.history()
    outcomes={(r['league'],r['date'],r['h'],r['a']):r for r in history}
    done=[]
    for pred in saved:
        if pred['status']!='frozen':continue
        if datetime.fromisoformat(pred['kickoff_utc'])+timedelta(minutes=115)>now:continue
        match=outcomes.get((pred['league'],pred['date'],pred['home_id'],pred['away_id']))
        if not match:continue
        actual='home' if match['hg']>match['ag'] else 'draw' if match['hg']==match['ag'] else 'away'
        result={'id':pred['id'],'fixture_date':pred['date'],'home_goals':match['hg'],'away_goals':match['ag'],
               'outcome':actual,'provider_final_source_id':match['source_match_id'],
               'provider_verified':True,'graded_at_utc':now.isoformat(),
               'model_scores':{name:{'pick':pred['picks'][name],
                  'correct':pred['picks'][name]==actual,
                  'log_loss':round(-math.log(max(prob[actual],1e-12)),8),
                  'brier':round(sum((prob[k]-(k==actual))**2 for k in OUTCOMES),8)}
                  for name,prob in pred['models'].items()}}
        db.query(f'INSERT OR IGNORE INTO {GRADE_TABLE}(id,payload) VALUES(?,?)',
                 (result['id'],json.dumps(result,separators=(',',':'))))
        done.append(result['id'])
    graded=db.query(f'SELECT COUNT(*) AS n FROM {GRADE_TABLE}')[0]['n']
    return {'status':'graded','ledger_count':len(saved),'graded':graded,
            'remaining':sum(x['status']=='frozen' for x in saved)-graded,'newly_matched':len(done)}


def main(argv=None):
    a=argparse.ArgumentParser()
    a.add_argument('action',choices=('freeze','grade'))
    options=a.parse_args(argv)
    db=D1()
    result=freeze(db) if options.action=='freeze' else grade(db)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True))
    return result

if __name__=='__main__':main()
