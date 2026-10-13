"""One-request, zero-cost 365Scores technical connectivity probe.

The project owner affirms prior research authorization for their original
non-commercial XGQ offensive estimators. Probe one KNOWN ID from the old
adapter's regression fixtures. No endpoint discovery, guessing match IDs,
cookies, browser impersonation, retries, or pagination. No publication or
storage of raw provider payloads. This does not infer permission for bulk
collection or public data redistribution.

Exit 0 even when the provider rejects or dataset is incomplete: this is a
DIAGNOSTIC, not a loophole to deploy collection.
"""
from __future__ import annotations
import json
from datetime import datetime,timezone
from pathlib import Path
from urllib.error import HTTPError,URLError
from engine import provider365

MATCH_ID="4732693"  # Existing original connector test ID; verify returned match identity
OUTPUT=Path("research/reports/365scores_one_match_probe.json")


def probe():
    out={
      "probe":"one historical known-id match request",
      "scope":"owner-asserted preexisting private noncommercial XGQ research",
      "query_count":1,
      "match_id_source":"existing tests/test_365_regressions.py; not discovered or enumerated",
      "provider_response_not_stored":True,
      "private_raw_event_data_written":False,
      "production_changed":False,
      "outcome":"not_started",
      "technical_shot_complete":False,
      "independent_totals_verified":False,
      "note":"No legal conclusion about prior permission scope; no bulk ingestion."
    }
    try:
        payload=provider365.fetch("game/",{"gameId":MATCH_ID,"topBookmaker":"14"})
        out["transport"]="http_success_json"
    except provider365.AccessDenied as e:
        out["outcome"]="provider_access_denied";out["reason"]="HTTP 401, 403 or 429; halted with no retry"
        return out
    except HTTPError as e:
        out["outcome"]="http_error";out["http_status"]=int(e.code)
        return out
    except (URLError,TimeoutError,ConnectionError) as e:
        out["outcome"]="connectivity_error";out["reason"]=type(e).__name__
        return out
    except (ValueError,UnicodeDecodeError) as e:
        out["outcome"]="invalid_or_excessive_response";out["reason"]=type(e).__name__
        return out
    except Exception as e:
        out["outcome"]="unexpected_error";out["reason"]=type(e).__name__
        return out
    match=payload.get("game",payload) if isinstance(payload,dict) else None
    if not isinstance(match,dict):
        out["outcome"]="invalid_game_json";return out
    received_id=provider365._game_id(match)
    out["match_identity_confirms_expected"]=received_id==MATCH_ID
    if received_id!=MATCH_ID:
        out["outcome"]="unexpected_match_identity";return out
    out["is_final"]=provider365._final(match)
    if not out["is_final"]:
        out["outcome"]="not_completed";return out
    home=provider365._side(match,"home")
    away=provider365._side(match,"away")
    h=str(home.get("id") or home.get("competitorId") or "")
    a=str(away.get("id") or away.get("competitorId") or "")
    out["both_team_ids_present"]=bool(h and a and h!=a)
    if not out["both_team_ids_present"]:
        out["outcome"]="missing_team_ids";return out
    comp_id,comp_name,comp_country=provider365._competition(match)
    out["competition_metadata_present"]=bool(comp_name and comp_country)
    events=match.get("chartEvents") or match.get("chart_events")
    if isinstance(events,dict):
        events=events.get("events") or events.get("chartEvents") or events.get("items")
    if not isinstance(events,list):
        out["outcome"]="no_chart_events_array";return out
    out["chart_events_total"]=len(events)
    counts={h:0,a:0}
    invalid_xg=unassigned=0
    for evt in events:
        if not isinstance(evt,dict):
            continue
        if not provider365._is_shot(evt):
            continue
        shot_xg=provider365._xg(evt)
        if shot_xg is None:
            invalid_xg+=1
        who=evt.get("competitor") if isinstance(evt.get("competitor"),dict) else {}
        team=str(evt.get("competitorId") or evt.get("teamId") or who.get("id") or "")
        if team not in counts:
            if isinstance(evt.get("isHome"),bool):
                team=h if evt["isHome"] else a
            elif evt.get("competitorNum") in (1,2):
                team=h if evt["competitorNum"]==1 else a
            else:
                unassigned+=1
                continue
        counts[team]+=1
    out["recognized_shot_events"]=sum(counts.values())+unassigned
    out["home_shot_events"]=counts[h]
    out["away_shot_events"]=counts[a]
    out["shot_events_with_missing_xg"]=invalid_xg
    out["shot_events_unassigned"]=unassigned
    out["valid_individual_xg_for_observed_events"]=(
      len(events)>0 and sum(counts.values())>0 and invalid_xg==0 and unassigned==0
    )
    out["outcome"]="shot_fields_present_need_independent_totals" if out[
      "valid_individual_xg_for_observed_events"] else "shot_fields_incomplete_or_absent"
    out["note"]=(
      "Only structural verification. Do not mark a match shot-complete until "
      "per-side shot counts and xG sums are independently reconciled."
    )
    return out


def main():
    result=probe()
    OUTPUT.parent.mkdir(parents=True,exist_ok=True)
    OUTPUT.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(result,ensure_ascii=False,sort_keys=True))
    return result


if __name__=="__main__":
    main()
