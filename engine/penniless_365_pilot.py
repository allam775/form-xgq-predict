"""Penniless 365Scores EUROPEAN pilot: offline, user-supplied responses only.

This does not contact 365Scores or enable the existing provider adapter.
All examples are synthetic tests. Real provider use requires verified rights.

Never infer genuine shot xG from aggregate xG / number of shots.
Require *independent same-source evidence* of each team's total shot count
and team xG, otherwise a plausible-looking chartEvents subset is NOT usable.
"""
from __future__ import annotations
from datetime import date
from math import isfinite
from urllib.parse import urlparse
import re
import unicodedata

from . import provider365
from .xgq import strict_row


def canon(value):
    norm=unicodedata.normalize("NFKD",str(value or "").casefold())
    return " ".join(re.sub(r"[^a-z0-9]+"," ",
                       "".join(c for c in norm if not unicodedata.combining(c))).split())


# These are name/country identities, NOT guesses at numeric team or league IDs.
# Expanding beyond these values requires individually verified match evidence.
PILOT_COMPETITIONS={
 "uefa.cl":({"uefa champions league","champions league"},
            {"europe","international","uefa"}),
 "pt.1":({"liga portugal","primeira liga","liga portugal betclic"},
          {"portugal"}),
 "tr.1":({"super lig","trendyol super lig"},{"turkey","turkiye"}),
 "nl.1":({"eredivisie"},{"netherlands","holland"}),
 "be.1":({"jupiler pro league","first division a","pro league"},{"belgium"}),
 "no.1":({"eliteserien"},{"norway"}),
 "at.1":({"bundesliga","austrian bundesliga"},{"austria"}),
 "gr.1":({"super league","super league 1","super league greece"},{"greece"}),
}
MAX_SHOTS=150
SOURCE="365Scores (opt-in; rights required)"


class UnverifiedMatch(ValueError):
    pass


def _positive_int(v):
    return type(v) is int and 1<=v<=MAX_SHOTS


def _xg_number(v):
    return (type(v) in (int,float) and isfinite(v) and v>=0)


def valid_web_source(url):
    """Source link for auditor; NOT a source to automatically fetch."""
    try:
        p=urlparse(url)
        return (p.scheme=="https" and p.hostname in ("www.365scores.com","365scores.com")
                and "/football/match/" in p.path)
    except (TypeError,ValueError,AttributeError):
        return False


def audit_game(payload, league, witness, *, expected_team_id=None):
    """Verify all shot events against independently observed 90-minute totals.

    witness: transcription from legally viewed SAME MATCH source with
      match_id, source_url, verified_date, time_scope='90m',
      home_shots, away_shots, home_xg, away_xg,
      shot_xg_decimals and aggregate_xg_decimals (each 1..4).
    Missing documentation never gets treated as zero or assumed true.
    """
    if league not in PILOT_COMPETITIONS:
        raise UnverifiedMatch("Unverified European competition")
    if not isinstance(witness,dict):
        raise UnverifiedMatch("Missing independently verified totals")
    keys=("match_id","source_url","verified_date","time_scope",
          "home_shots","away_shots","home_xg","away_xg",
          "shot_xg_decimals","aggregate_xg_decimals")
    if any(k not in witness for k in keys):
        raise UnverifiedMatch("Every documented total, scope and precision is required")
    if witness["time_scope"]!="90m":
        raise UnverifiedMatch("Only 90-minute matches with independently verified shot totals")
    if not valid_web_source(witness["source_url"]):
        raise UnverifiedMatch("Invalid provider match-source URL")
    try:
        date.fromisoformat(witness["verified_date"])
    except (TypeError,ValueError):
        raise UnverifiedMatch("Missing valid verification date") from None
    if not re.fullmatch(r"[1-9][0-9]{1,13}",str(witness["match_id"])):
        raise UnverifiedMatch("Missing real match ID")
    for k in ("home_shots","away_shots"):
        if not _positive_int(witness[k]):
            raise UnverifiedMatch("Missing verified non-zero shot count")
    for k in ("home_xg","away_xg"):
        if not _xg_number(witness[k]) or witness[k]>witness[k.replace("_xg","_shots")]:
            raise UnverifiedMatch("Invalid independently verified aggregate xG")
    for k in ("shot_xg_decimals","aggregate_xg_decimals"):
        if type(witness[k]) is not int or not 1<=witness[k]<=4:
            raise UnverifiedMatch("Missing decimal precision for comparison")

    game=payload.get("game",payload) if isinstance(payload,dict) else None
    if not isinstance(game,dict) or not provider365._final(game):
        raise UnverifiedMatch("Not a completed match")
    if provider365._game_id(game)!=str(witness["match_id"]):
        raise UnverifiedMatch("Source match identity differs")
    cid,name,country=provider365._competition(game)
    names,countries=PILOT_COMPETITIONS[league]
    if canon(name) not in {canon(s) for s in names} or canon(country) not in {canon(s) for s in countries}:
        raise UnverifiedMatch("Wrong competition, country or missing independently verified identity")
    if expected_team_id is not None and str(expected_team_id) not in provider365._identity(game):
        raise UnverifiedMatch("Requested team absent from actual match")
    home,away=(provider365._side(game,s) for s in ("home","away"))
    hid=str(home.get("id") or home.get("competitorId") or "")
    aid=str(away.get("id") or away.get("competitorId") or "")
    if not hid or not aid or hid==aid:
        raise UnverifiedMatch("Ambiguous team identities")

    events=game.get("chartEvents") or game.get("chart_events")
    if isinstance(events,dict):
        events=events.get("events") or events.get("chartEvents") or events.get("items")
    if not isinstance(events,list) or not events or len(events)>1000:
        raise UnverifiedMatch("No bounded complete shot events")
    shots={hid:[],aid:[]}
    for event in events:
        if not isinstance(event,dict):
            raise UnverifiedMatch("Invalid event entry")
        if not provider365._is_shot(event):
            continue
        xg=provider365._xg(event)
        if xg is None:
            raise UnverifiedMatch("A shot event is missing a valid individual xG")
        competitor=event.get("competitor") if isinstance(event.get("competitor"),dict) else {}
        tid=str(event.get("competitorId") or event.get("teamId") or competitor.get("id") or "")
        if tid not in shots:
            if type(event.get("isHome")) is bool:
                tid=hid if event["isHome"] else aid
            elif event.get("competitorNum") in (1,2):
                tid=hid if event["competitorNum"]==1 else aid
            else:
                raise UnverifiedMatch("Shot has no authenticated team identity")
        shots[tid].append(xg)
    # Cross-check both the count and rounded xG subtotal.
    for side,tid in (("home",hid),("away",aid)):
        n=witness[side+"_shots"]
        if len(shots[tid])!=n:
            raise UnverifiedMatch(f"{side}: {len(shots[tid])} chart shots != {n} verified shots")
        # Worst-case rounding error: each displayed shot xG +/-0.5 ULP,
        # and team's displayed total +/-0.5 ULP. No arbitrary relaxation.
        tolerance=(.5*10**(-witness["shot_xg_decimals"])*n
                   +.5*10**(-witness["aggregate_xg_decimals"])+1e-9)
        if abs(sum(shots[tid])-witness[side+"_xg"])>tolerance:
            raise UnverifiedMatch(f"{side}: shot xG sum does not reconcile with reported total")
    record=strict_row({
        "date":provider365._date(game),
        "league":league,
        "home_team":str(home.get("name") or home.get("displayName") or ""),
        "away_team":str(away.get("name") or away.get("displayName") or ""),
        "home_goals":provider365._score(game,"home",home),
        "away_goals":provider365._score(game,"away",away),
        "home_shots_xg":shots[hid],
        "away_shots_xg":shots[aid],
        "source":SOURCE,
        "source_match_id":str(witness["match_id"])
    })
    # Compact summary only; don't persist event arrays/provider payloads.
    return {
        "id":record["id"],"date":record["date"],"league":record["league"],
        "home":record["home"],"away":record["away"],
        "score":[record["hg"],record["ag"]],
        "home_shots":record["home_shots"],
        "away_shots":record["away_shots"],
        "home_xg":record["home_xg"],"away_xg":record["away_xg"],
        "home_xgq":record["home_xgq"],"away_xgq":record["away_xgq"],
        "completeness":"shot-count-and-xg-reconciled",
        "source":SOURCE,
        "source_match_id":record["source_match_id"],
        "audit_date":witness["verified_date"],
        "public_release_permitted":False
    }
