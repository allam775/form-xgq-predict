"""Opt-in 365Scores match-shot adapter for explicitly authorized access.

This module does not use browser impersonation, cookie extraction, reverse proxying,
CAPTCHA workarounds, or endpoint enumeration. 365Scores is NOT open data.
Only use where the user has appropriate rights for collection and publication.
Source may change shape or block hosted runners; fail closed in those cases.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
import json
import os
from pathlib import Path
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .xgq import strict_row

HOST = "https://webws.365scores.com/web"
DEFAULT_QUERY = {"appTypeId": "5", "langId": "1", "timezoneName": "UTC"}
MAX_TEAMS = 24
MAX_GAMES = 48
MAX_RESPONSE = 5_000_000


class AccessDenied(RuntimeError):
    """The source did not authorize this request."""


def enabled(environ=None):
    env = environ if environ is not None else os.environ
    return env.get("XGQ_365_ACCESS_AUTHORIZED", "").strip().lower() in ("1", "true", "yes")


def publication_allowed(environ=None):
    env = environ if environ is not None else os.environ
    return env.get("XGQ_365_PUBLICATION_ALLOWED", "").strip().lower() in ("1", "true", "yes")


def private_only(environ=None):
    """Owner confirmation that the deployment is Access-protected and for private use.

    This is a configuration flag, NOT verification of source usage rights.
    """
    env = environ if environ is not None else os.environ
    return env.get("XGQ_365_PRIVATE_ONLY", "").strip().lower() in ("1", "true", "yes")


def read_teams(path):
    """Explicit known IDs only: no blind team-ID brute force or API discovery."""
    teams = json.loads(Path(path).read_text(encoding="utf8"))
    if not isinstance(teams, list) or len(teams) > MAX_TEAMS:
        raise ValueError("365Teams must be an array with <=24 explicitly supplied IDs")
    result = []
    for item in teams:
        if not isinstance(item, dict):
            raise ValueError("Invalid team config")
        team_id = str(item.get("team_id", ""))
        league = str(item.get("league", ""))
        if not re.fullmatch(r"[1-9][0-9]{0,11}", team_id) or league not in ("en.1", "de.1", "es.1", "it.1", "fr.1"):
            raise ValueError("Invalid team ID or unsupported league")
        result.append((team_id, league))
    if len(set(result)) != len(result):
        raise ValueError("Duplicate team config")
    return result


def fetch(path, params=None, transport=None):
    if path not in ("games/results/", "game/"):
        raise ValueError("Unapproved endpoint")
    query = urlencode({**DEFAULT_QUERY, **(params or {})})
    url = f"{HOST}/{path}?{query}"
    if transport is not None:
        return transport(url)
    req = Request(url, headers={"Accept": "application/json", "User-Agent": "FormXGQ-Research/0.3 (contact via project owner)"})
    try:
        with urlopen(req, timeout=18) as resp:
            raw = resp.read(MAX_RESPONSE + 1)
            if len(raw) > MAX_RESPONSE:
                raise ValueError("Provider payload too large")
            return json.loads(raw)
    except HTTPError as e:
        if e.code in (401, 403, 429):
            raise AccessDenied(f"365Scores denied the request (HTTP {e.code}); no retry/bypass") from e
        raise


def _unpack_games(payload):
    """Bounded recursion for provider calendar group variations."""
    out = []
    def walk(node, depth):
        if depth > 5 or len(out) >= 120:
            return
        if isinstance(node, list):
            for v in node[:200]:
                walk(v, depth+1)
        elif isinstance(node, dict):
            if (node.get("gameId") or node.get("id")) and (
                node.get("homeCompetitor") or node.get("homeTeam") or node.get("competitors")
            ):
                out.append(node)
                return
            for k in ("games", "results", "data", "competitions", "dates", "items"):
                if k in node:
                    walk(node[k], depth+1)
    walk(payload, 0)
    return out


def _game_id(game):
    value = game.get("gameId") or game.get("id")
    value = str(value or "")
    return value if re.fullmatch(r"[1-9][0-9]{1,13}", value) else None


def _side(game, direction):
    return game.get(f"{direction}Competitor") or game.get(f"{direction}Team") or (
        (game.get("competitors") or [None,None])[0 if direction=="home" else 1]
        if isinstance(game.get("competitors"), list) and len(game.get("competitors"))>=2 else None
    ) or {}


def _final(game):
    fields = (game.get("status"), game.get("statusText"), game.get("statusName"),
              game.get("gameStatus"), game.get("shortStatusText"))
    raw = " ".join(str(x.get("name") or x.get("description") or "") if isinstance(x, dict) else str(x or "") for x in fields).lower()
    return any(re.search(r"\b" + term + r"\b", raw) for term in
               ("final", "finished", "ended", "ft", "full.time", "after.extra.time", "aet"))


def _date(game):
    value = game.get("startTimeUTC") or game.get("startTime") or game.get("gameTime") or game.get("date")
    if isinstance(value, (int, float)) and 1e9 < value < 2e13:
        return datetime.fromtimestamp(value / (1000 if value > 1e11 else 1), tz=timezone.utc).date().isoformat()
    if isinstance(value, str) and re.fullmatch(r"\d{13}|\d{10}", value):
        return _date({"startTime": int(value)})
    if isinstance(value, str):
        return date.fromisoformat(value[:10]).isoformat()
    raise ValueError("Missing verified match date")


def _score(game, direction, side):
    value = side.get("score", game.get(direction + "Score"))
    if isinstance(value, dict):
        value = value.get("score") if value.get("score") is not None else value.get("current")
    if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 30:
        return value
    if isinstance(value, str) and value.isdigit() and int(value) <= 30:
        return int(value)
    raise ValueError("Missing final score")


def _xg(event):
    shot = event.get("shot") if isinstance(event.get("shot"), dict) else {}
    for key in ("xg", "xG", "expectedGoals", "expectedGoal", "expectedGoalsValue", "xGValue"):
        val = event.get(key, shot.get(key))
        if isinstance(val, (int,float)) and not isinstance(val, bool) and 0 <= val <= 1:
            return float(val)
    return None


def _is_shot(event):
    if _xg(event) is not None or isinstance(event.get("shot"), dict):
        return True
    name = " ".join(str(event.get(k) or "").lower() for k in ("eventType", "shotType", "type", "category"))
    return any(word in name for word in ("shot", "goal", "saved", "blocked", "missed", "penalty"))


def parse_game(payload, league, game_id=None, aliases=None):
    """Accept only full-time games with attributable xG for *every* shot event."""
    game = payload.get("game", payload) if isinstance(payload, dict) else None
    if not isinstance(game, dict) or not _final(game):
        raise ValueError("Game is not confirmed final")
    home, away = _side(game,"home"), _side(game,"away")
    hi, ai = str(home.get("id") or home.get("competitorId") or ""), str(away.get("id") or away.get("competitorId") or "")
    if not hi or not ai or hi == ai:
        raise ValueError("Ambiguous teams")
    events = game.get("chartEvents") or game.get("chart_events")
    if isinstance(events, dict):
        events = events.get("events") or events.get("chartEvents") or events.get("items")
    if not isinstance(events, list) or not events:
        raise ValueError("No shot-level chart events")
    shots = {hi: [], ai: []}
    for event in events:
        if not isinstance(event,dict) or not _is_shot(event):
            continue
        val = _xg(event)
        if val is None:
            raise ValueError("At least one shot has no individual xG")
        competitor = event.get("competitor") if isinstance(event.get("competitor"), dict) else {}
        team = str(event.get("competitorId") or event.get("teamId") or competitor.get("id") or "")
        if team not in shots:
            is_home = event.get("isHome")
            if isinstance(is_home, bool):
                team = hi if is_home else ai
            elif event.get("competitorNum") in (1, 2):
                team = hi if event["competitorNum"]==1 else ai
            else:
                raise ValueError("Cannot attribute every shot to a team")
        shots[team].append(val)
    if not shots[hi] or not shots[ai]:
        raise ValueError("Incomplete shot arrays for the two teams")
    aliases = aliases or {}
    home_name = str(home.get("name") or home.get("displayName") or "").strip()
    away_name = str(away.get("name") or away.get("displayName") or "").strip()
    return strict_row({
        "date": _date(game), "league": league,
        "home_team": aliases.get(home_name, home_name),
        "away_team": aliases.get(away_name, away_name),
        "home_goals": _score(game,"home",home), "away_goals": _score(game,"away",away),
        "home_shots_xg": shots[hi], "away_shots_xg": shots[ai],
        "source": "365Scores (opt-in; rights required)",
        "source_match_id": str(game_id or _game_id(game) or ""),
    })


def collect(existing, team_configs, *, transport=None, max_new=30, delay_s=1.2, aliases=None):
    """Make bounded requests for opted-in team IDs. Never enumerate IDs."""
    if not team_configs:
        return list(existing), {"fetched": 0, "added": 0, "rejected": 0, "configured_teams": 0}
    if len(team_configs) > MAX_TEAMS or max_new > MAX_GAMES:
        raise ValueError("Rate limit gate exceeded")
    rows = {r["id"]: r for r in existing}
    known = {str(r.get("source_match_id")) for r in existing if r.get("source", "").startswith("365Scores")}
    matches = {}
    rejected = 0
    fetched = 0
    for team_id,league in team_configs:
        payload = fetch("games/results/", {"competitors": team_id}, transport)
        fetched += 1
        for game in _unpack_games(payload):
            mid = _game_id(game)
            if mid and mid not in known:
                matches.setdefault(mid,league)
        if transport is None:
            time.sleep(delay_s)
    added = 0
    for mid, league in list(matches.items())[:max_new]:
        try:
            game = fetch("game/", {"gameId":mid}, transport)
            fetched += 1
            row = parse_game(game, league, mid, aliases=aliases)
            if row["id"] not in rows:
                rows[row["id"]] = row
                added += 1
        except (ValueError, KeyError, TypeError, HTTPError, URLError):
            rejected += 1
        if transport is None:
            time.sleep(delay_s)
    return list(rows.values()), {"fetched": fetched, "added": added,
                                  "rejected": rejected, "configured_teams": len(team_configs)}
