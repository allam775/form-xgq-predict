"""One-time differential diagnosis of the 11 rejected 365Scores candidates.

Use only already known private D1 match IDs and previously used provider routes:
game/ for per-shot xG and game/stats/ for independent full-match totals.

No raw responses, player names, event sequences or individual xG are stored.
Only per-event-class AGGREGATE counts/xG and mismatches go to private D1.
Public GitHub Actions gets aggregate totals only. No updates to model or
verified records. Fail closed on source access denials. MAX 30 requests.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
import importlib
import json
import math
import time

from engine import provider365 as p
from engine.competition365 import resolve
from engine.stats365 import stats_witness, reconcile
from engine.understat_d1 import D1, D1Error
_batch=importlib.import_module("research.365_stats_completeness_batch")
candidates=_batch.candidates
prior_audits=_batch.prior_audits

FETCH_STATS=importlib.import_module("research.365_stats_schema_probe").fetch_stats
OUT=Path("research/reports/365_rejected_diagnosis_summary.json")
MAX_CASES=15
MAX_REQUESTS=30
PAUSE=1.3


def _label(event, key):
    raw=event.get(key)
    if isinstance(raw, dict):
        raw=raw.get("name") or raw.get("type") or raw.get("description") or raw.get("id")
    if isinstance(raw, bool):return str(raw).lower()
    if not isinstance(raw,(str,int,float)):return ""
    value=str(raw).strip().lower()
    return value[:65] if value else ""


def _shot_group(game):
    """Aggregate per-side observed events by stable NON-player event metadata."""
    h=p._side(game,"home");a=p._side(game,"away")
    hi=str(h.get("id") or h.get("competitorId") or "")
    ai=str(a.get("id") or a.get("competitorId") or "")
    if not hi or not ai or hi==ai:
        raise ValueError("diagnostic_competitor_identity")
    events=game.get("chartEvents") or game.get("chart_events")
    if isinstance(events,dict):
        events=events.get("events") or events.get("chartEvents") or events.get("items")
    if not isinstance(events,list) or len(events)>500:
        raise ValueError("diagnostic_event_array_missing")
    groups={"home":defaultdict(lambda:[0,0.0]),"away":defaultdict(lambda:[0,0.0])}
    totals=Counter();precision=Counter()
    keys=Counter()
    for event in events:
        if not isinstance(event,dict):continue
        keys.update(event.keys())
        if not p._is_shot(event):continue
        v=p._xg(event)
        if v is None:raise ValueError("diagnostic_missing_shot_xg")
        comp=event.get("competitor") if isinstance(event.get("competitor"),dict) else {}
        team=str(event.get("competitorId") or event.get("teamId") or comp.get("id") or "")
        if team==hi:side="home"
        elif team==ai:side="away"
        elif isinstance(event.get("isHome"),bool):side="home" if event["isHome"] else "away"
        elif event.get("competitorNum") in (1,2):side="home" if event["competitorNum"]==1 else "away"
        else:raise ValueError("diagnostic_shot_team_missing")
        shot=event.get("shot") if isinstance(event.get("shot"),dict) else {}
        sig="|".join((
            _label(event,"type"),_label(event,"eventType"),_label(event,"shotType"),
            _label(event,"outcome"),_label(event,"category"),
            _label(event,"isPenalty"),_label(event,"isOwnGoal"),
            _label(event,"period"),_label(event,"gamePeriod"),
            _label(event,"eventTypeId"),_label(shot,"type"),
        ))
        # Each classification category is aggregated; no individual values.
        groups[side][sig][0]+=1
        groups[side][sig][1]+=v
        totals[side]+=1
        xgt=event.get("xg",event.get("xG"))
        if isinstance(xgt,str) and "." in xgt:
            precision[len(xgt.split(".",1)[1])]+=1
    return {
      "events_total":len(events),
      "recognized_shots":dict(totals),
      "event_metadata_keys":sorted(keys),
      "shot_xg_precision":dict(precision),
      "groups":{
        side:[{"signature":k,"count":v[0],"sum_xg":round(v[1],6)}
              for k,v in sorted(grp.items())]
        for side,grp in groups.items()
      }
    }


def _call_detail(mid):
    return p.fetch("game/",{"gameId":mid,"topBookmaker":"14"})


def diagnosis(db=None,detail_fetch=None,stats_fetch=None,*,limit=MAX_CASES,delay=PAUSE):
    if type(limit) is not int or not 1<=limit<=MAX_CASES or delay<0:
        raise ValueError("unsafe_diagnosis_limit")
    d=db if db is not None else D1()
    existing=candidates(d);audits=prior_audits(d)
    rejected=[i for i in existing if i in audits and audits[i].get("complete") is False]
    controls=[i for i in existing if i in audits and audits[i].get("complete") is True]
    selected=rejected[:11]+controls[:min(4,max(0,limit-len(rejected[:11])))]
    d.query("""CREATE TABLE IF NOT EXISTS private_365_rejected_diagnosis(
        id TEXT PRIMARY KEY NOT NULL, payload TEXT NOT NULL)""")
    already={str(x["id"]) for x in d.query(
        "SELECT id FROM private_365_rejected_diagnosis LIMIT 100")}
    report={"kind":"one_time_365scores_rejected_differential",
            "private_only":True,"raw_events_written":0,
            "event_sequences_written":0,"match_id_published":False,
            "details_requested":0,"stats_requested":0,
            "rejected_candidates":len(rejected),"controls_available":len(controls),
            "cases_selected":len(selected),"cases_examined":0,
            "rejected_examined":0,"controls_examined":0,
            "already_diagnosed":0,
            "reproduced_reasons":{},
            "count_gap_signs":{},
            "xg_mismatch_magnitude_buckets":{},
            "failures":{},"status":"completed",
            "verified_archive_changed":False}
    causes=Counter();signs=Counter();mags=Counter();errors=Counter()
    getter_d=detail_fetch if detail_fetch is not None else _call_detail
    getter_s=stats_fetch if stats_fetch is not None else FETCH_STATS
    for mid in selected:
        if mid in already:
            report["already_diagnosed"]+=1;continue
        if report["details_requested"]+report["stats_requested"]+2>MAX_REQUESTS:
            report["status"]="max_requests_reached";break
        case=existing[mid];control=audits[mid].get("complete") is True
        try:
            report["details_requested"]+=1
            detail=getter_d(mid)
            if detail_fetch is None:time.sleep(delay)
            obj=detail.get("game",detail) if isinstance(detail,dict) else None
            if not isinstance(obj,dict) or p._game_id(obj)!=mid or not p._final(obj):
                raise ValueError("detail_game_id_not_final")
            comp=resolve(detail)
            if not comp["ok"] or comp["league"]!=case["league"]:
                raise ValueError("competition_identity_mismatch")
            if p._date(obj)!=case["date"]:
                raise ValueError("detail_match_date_mismatch")
            shot=_shot_group(obj)
            report["stats_requested"]+=1
            stats=getter_s(mid)
            if stats_fetch is None:time.sleep(delay)
            witness=stats_witness(stats,case)
            current=reconcile(case,witness)
            # Derive-only; store no raw shot payload, identities or event stream.
            row={
              "control":control,"date":case["date"],"league":case["league"],
              "previous":audits[mid].get("status"),
              "reproduced":current["reason"],
              "current_ok":current["ok"],
              "source_stats":witness,
              "cached_chart_shots":{
                s:case[s+"_chart_shots"] for s in ("home","away")},
              "cached_chart_sum_xg":{
                s:case[s+"_chart_xg_sum"] for s in ("home","away")},
              "new_chart":shot,
              "new_vs_saved":{
                "shot_counts_same":all(
                    shot["recognized_shots"].get(s,0)==case[s+"_chart_shots"]
                    for s in ("home","away")),
                "shot_xg_same":all(
                    abs(sum(g["sum_xg"] for g in shot["groups"][s])
                      -case[s+"_chart_xg_sum"])<=0.00001
                    for s in ("home","away"))
              },
              "checked_at":datetime.now(timezone.utc).isoformat()
            }
            # Save only in PRIVATE D1. Existing source/audit tables unchanged.
            d.query("INSERT OR REPLACE INTO private_365_rejected_diagnosis(id,payload) VALUES(?,?)",
                    (mid,json.dumps(row,ensure_ascii=False,separators=(",",":"))))
            report["cases_examined"]+=1
            report["controls_examined" if control else "rejected_examined"]+=1
            causes[current["reason"]]+=1
            for side in ("home","away"):
                n=witness[side]["shots"]-case[side+"_chart_shots"]
                if n:
                    signs["chart_more" if n<0 else "chart_fewer"]+=1
                dx=abs(witness[side]["xg"]-case[side+"_chart_xg_sum"])
                if dx>0.2:mags[">0.20"]+=1
                elif dx>0.1:mags["0.10-0.20"]+=1
                elif dx>0.05:mags["0.05-0.10"]+=1
                elif dx>0.01:mags["0.01-0.05"]+=1
                else:mags["<=0.01"]+=1
        except (p.AccessDenied,HTTPError) as exc:
            errors[type(exc).__name__]+=1
            if isinstance(exc,p.AccessDenied) or getattr(exc,"code",0) in (401,403,429):
                report["status"]="provider_denied_stop";break
        except (URLError,TimeoutError,ValueError,TypeError,KeyError,D1Error) as exc:
            errors[type(exc).__name__ if not isinstance(exc,ValueError)
                   else str(exc)[:65]]+=1
    report["reproduced_reasons"]=dict(sorted(causes.items()))
    report["count_gap_signs"]=dict(signs)
    report["xg_mismatch_magnitude_buckets"]=dict(mags)
    report["failures"]=dict(sorted(errors.items()))
    return report


def main():
    try:result=diagnosis()
    except (D1Error,ValueError,TypeError,KeyError) as exc:
        result={"kind":"rejected_diagnosis","status":"private_unavailable",
                "reason_type":type(exc).__name__,"raw_events_written":0,
                "event_sequences_written":0,"match_id_published":False,
                "verified_archive_changed":False}
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(result,indent=2,ensure_ascii=False)+"\n",encoding="utf8")
    print(json.dumps(result,ensure_ascii=False))
    return result

if __name__=="__main__":main()
