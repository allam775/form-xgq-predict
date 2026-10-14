"""365Scores competition fixture ledger: no silently discarded games.

Authorized access only. A game is indexed even when its per-shot xG cannot
be verified. This is a private metadata ledger, NOT a public XGQ prediction
feed, and does not imply that upstream coverage is complete.
"""
from __future__ import annotations

import argparse
from datetime import date, timedelta
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import time

from . import provider365

MAX_DAYS_PER_RUN = 14
MAX_DETAILS_PER_RUN = 48
MAX_GAMES_PER_DAY = 10000


def _require_authorization():
    if not provider365.enabled() or not provider365.private_only():
        raise PermissionError(
            "Enable only with confirmed 365Scores rights and a private Access-protected "
            "destination (XGQ_365_ACCESS_AUTHORIZED=1, XGQ_365_PRIVATE_ONLY=1)."
        )


def _games(payload):
    """Flatten documented day/competition groupings without the old 120-item cutoff."""
    found = []
    def visit(node, parent_cid="", depth=0):
        if depth > 10:
            raise ValueError("Nested results feed exceeded supported depth")
        if isinstance(node, list):
            for child in node:
                visit(child, parent_cid, depth + 1)
            return
        if not isinstance(node, dict):
            return
        cid = str(node.get("competitionId") or (
            node.get("competition", {}).get("id") if isinstance(node.get("competition"), dict) else ""
        ) or parent_cid)
        home = node.get("homeCompetitor") or node.get("homeTeam")
        away = node.get("awayCompetitor") or node.get("awayTeam")
        if isinstance(home, dict) and isinstance(away, dict):
            item = dict(node)
            if cid:
                item.setdefault("competitionId", cid)
            found.append(item)
            if len(found) > MAX_GAMES_PER_DAY:
                raise ValueError("Provider day exceeds safety bound; split query or seek bulk feed")
            return
        for key in ("games", "dates", "competitions", "results", "data", "items", "groups"):
            if key in node:
                visit(node[key], cid, depth + 1)
    if not isinstance(payload, (dict, list)):
        raise ValueError("Results payload is not JSON list/object")
    visit(payload)
    if isinstance(payload, dict):
        # A cursor is NOT permission to call a query complete.
        for k in ("hasMore", "hasNext", "hasNextPage"):
            if payload.get(k) is True:
                raise ValueError("Provider paginated results; day cannot be certified complete")
        if payload.get("nextPage") not in (None, False, "", 0):
            raise ValueError("Provider returned a nextPage cursor")
        for k in ("total", "totalCount", "totalGames"):
            if isinstance(payload.get(k), int) and payload[k] > len(found):
                raise ValueError("Provider returned fewer games than advertised total")
        if not any(k in payload for k in ("games", "dates", "competitions", "results", "data", "items", "groups")):
            raise ValueError("Unknown provider schedule schema")
    return found


def _fixture(game, requested_cid, day):
    cid, _, _ = provider365._competition(game)
    if cid != str(requested_cid):
        return None
    mid = provider365._game_id(game)
    home = provider365._side(game, "home")
    away = provider365._side(game, "away")
    if not isinstance(home, dict) or not isinstance(away, dict):
        return None
    home_name = str(home.get("name") or home.get("displayName") or "").strip()
    away_name = str(away.get("name") or away.get("displayName") or "").strip()
    hi = str(home.get("id") or home.get("competitorId") or "")
    ai = str(away.get("id") or away.get("competitorId") or "")
    # Do not throw away a genuine fixture just because 365 omitted gameId.
    stable = "|".join((str(requested_cid), day, hi or home_name, ai or away_name))
    key = mid or ("unresolved:" + hashlib.sha256(stable.encode()).hexdigest()[:24])
    return key, {
        "id": mid, "competition_id": str(requested_cid),
        "observed_date": day, "home": home_name, "away": away_name,
        "home_id": hi, "away_id": ai,
        "fixture_status": "final" if provider365._final(game) else "not_final_or_unknown",
        "xg_status": "not_checked", "xg_issue": None,
    }


def new_ledger(cid, league, start, end):
    if league not in provider365.KNOWN_LEAGUES:
        raise ValueError("League is not configured for strict XGQ parsing")
    if not re.fullmatch(r"[1-9][0-9]{0,11}", str(cid)):
        raise ValueError("Use a known positive 365Scores competition ID")
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    if first > last or (last - first).days > 500:
        raise ValueError("Season window must be ordered and at most 501 days")
    return {"schema_version": 1, "competition_id": str(cid), "league": league,
            "start": start, "end": end, "scanned_days": [],
            "failed_days": {}, "matches": {}, "unassigned_games": {}, "verified_rows": {},
            "uncertain_competition_events": 0}


def _save_atomic(path, ledger):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Never create a world-readable cache by design.
    fd, name = tempfile.mkstemp(prefix=".365-ledger-", dir=path.parent)
    try:
        os.chmod(name, 0o600)
        with os.fdopen(fd, "w", encoding="utf8") as fp:
            json.dump(ledger, fp, ensure_ascii=False, indent=2, sort_keys=True)
            fp.write("\n")
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def load_or_create(path, cid, league, start, end):
    path = Path(path)
    ledger = json.loads(path.read_text(encoding="utf8")) if path.exists() else new_ledger(cid, league, start, end)
    if any(ledger.get(k) != v for k, v in {
        "schema_version": 1, "competition_id": str(cid), "league": league,
        "start": start, "end": end}.items()):
        raise ValueError("Existing ledger is for another competition/season; do not overwrite it")
    return ledger


def scan_day(ledger, day, *, transport=None):
    """One calendar day per request; use all football matches, not top-only or team teasers."""
    iso = date.fromisoformat(day).strftime("%d/%m/%Y")
    payload = provider365.fetch("games/allscores/", {
        "sports": "1", "startDate": iso, "endDate": iso,
        "onlyMajorGames": "false", "withTop": "false"
    }, transport)
    candidates = _games(payload)
    if transport is None:
        time.sleep(1.2)
    observed = 0
    # Preserve matches even if the source later stops reporting them.
    for game in candidates:
        cid, _, _ = provider365._competition(game)
        if not cid:
            # Could be from this competition, so record as unassigned rather than
            # throwing the candidate away or guessing its league.
            mid = provider365._game_id(game)
            if mid:
                ledger.setdefault("unassigned_games", {})[mid] = {
                    "observed_date": day, "reason": "missing_competition_id",
                    "home": str((provider365._side(game, "home") or {}).get("name") or ""),
                    "away": str((provider365._side(game, "away") or {}).get("name") or "")
                }
            ledger["uncertain_competition_events"] += 1
            continue
        fixture = _fixture(game, ledger["competition_id"], day)
        if fixture is None:
            continue
        key, new = fixture
        ledger.setdefault("unassigned_games", {}).pop(key, None)
        old = ledger["matches"].get(key, {})
        # Never lose previous verification when the listing lacks detailed statistics.
        for field in ("xg_status", "xg_issue"):
            if field in old:
                new[field] = old[field]
        if old.get("fixture_status") == "final":
            new["fixture_status"] = "final"
        ledger["matches"][key] = new
        observed += 1
    if day not in ledger["scanned_days"]:
        ledger["scanned_days"].append(day)
        ledger["scanned_days"].sort()
    ledger["failed_days"].pop(day, None)
    return observed



def _stat_number(value):
    if isinstance(value, dict):
        for key in ("value", "stat", "amount", "displayValue", "display", "total", "current"):
            if key in value:
                n = _stat_number(value[key])
                if n is not None:
                    return n
        return None
    if isinstance(value, bool):
        return None
    try:
        if value is None or not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", str(value).strip()):
            return None
        return float(value)
    except (ValueError, TypeError):
        return None


def aggregate_totals(payload):
    """Find documented team-level expected goals and total shots; never infer values."""
    found = {"home": {}, "away": {}}
    def walk(node, depth=0):
        if depth > 12:
            return
        if isinstance(node, list):
            for child in node:
                walk(child, depth + 1)
            return
        if not isinstance(node, dict):
            return
        if any(k in node for k in ("playerId", "athleteId", "memberId")):
            return
        label = re.sub(r"[^a-z]", "", str(
            node.get("name") or node.get("title") or node.get("label") or
            node.get("statName") or node.get("key") or ""
        ).lower())
        typ = ("xg" if label in ("expectedgoals", "expectedgoalsxg", "xg")
               else "shots" if label in ("totalshots", "shots", "shotstotal")
               else None)
        if typ:
            pair = node.get("stats")
            home = _stat_number(node.get("homeValue") if "homeValue" in node else node.get("home"))
            away = _stat_number(node.get("awayValue") if "awayValue" in node else node.get("away"))
            if isinstance(pair, list) and len(pair) >= 2:
                if home is None:
                    home = _stat_number(pair[0])
                if away is None:
                    away = _stat_number(pair[1])
            if home is not None:
                found["home"].setdefault(typ, home)
            if away is not None:
                found["away"].setdefault(typ, away)
        for key in ("statistics", "stats", "items", "rows", "groups", "categories", "data"):
            if key in node:
                walk(node[key], depth + 1)
    walk(payload)
    return found


def compare_aggregate(row, stats_payload):
    totals = aggregate_totals(stats_payload)
    if any(k not in totals[side] for side in ("home", "away") for k in ("xg", "shots")):
        return False, "aggregates_not_available_for_both_teams"
    for side in ("home", "away"):
        count = row[f"{side}_shots"]
        xg = row[f"{side}_xg"]
        if abs(totals[side]["shots"] - count) > 0.001:
            return False, (f"{side}_shot_count_mismatch:"
                           f"{count}_versus_{totals[side]['shots']}")
        if abs(totals[side]["xg"] - xg) > 0.06:
            return False, (f"{side}_xg_total_mismatch:"
                           f"{xg:.3f}_versus_{totals[side]['xg']:.3f}")
    return True, None


def refresh_details(ledger, *, transport=None, limit=MAX_DETAILS_PER_RUN):
    """Try to improve xG completeness; parsing failures stay on the fixture ledger."""
    if not 0 <= limit <= MAX_DETAILS_PER_RUN:
        raise ValueError("Exceeds bounded detail quota")
    checked = 0
    for key, fixture in sorted(ledger["matches"].items()):
        if checked >= limit:
            break
        if fixture.get("xg_status") == "verified_xg" or not fixture.get("id"):
            continue
        mid = fixture["id"]
        try:
            game = provider365.fetch("game/", {"gameId": mid}, transport)
            if transport is None:
                time.sleep(1.2)
            row = provider365.parse_game(
                game, ledger["league"], mid,
                verified_competition_ids=(ledger["competition_id"],)
            )
            # Reconcile against the independent 365Scores game/stats totals.
            # Unknown/contradictory totals keep the fixture without promoting XGQ.
            stats = provider365.fetch("game/stats/", {"games": mid}, transport)
            if transport is None:
                time.sleep(1.2)
            passed, issue = compare_aggregate(row, stats)
            fixture["xg_status"] = "verified_xg" if passed else "pending_verification"
            fixture["xg_issue"] = issue
            if passed:
                ledger["verified_rows"][mid] = row
            else:
                ledger["verified_rows"].pop(mid, None)
        except provider365.AccessDenied:
            raise
        except (ValueError, KeyError, TypeError, OSError) as exc:
            fixture["xg_status"] = "pending_verification"
            fixture["xg_issue"] = str(exc)[:240]
        checked += 1
    return checked


def audit(ledger, expected_game_ids=None):
    seen = set(ledger["matches"])
    expected = {str(x) for x in (expected_game_ids or [])}
    start, end = date.fromisoformat(ledger["start"]), date.fromisoformat(ledger["end"])
    expected_days = set()
    while start <= end:
        expected_days.add(start.isoformat())
        start += timedelta(days=1)
    pending_days = sorted(expected_days - set(ledger["scanned_days"]))
    unavailable = sorted(expected - seen)
    pending_xg = sum(m["xg_status"] != "verified_xg"
                     for m in ledger["matches"].values())
    return {
        "discovery_complete": not pending_days and not ledger["failed_days"]
                              and not unavailable and not ledger["uncertain_competition_events"],
        "matches_discovered": len(ledger["matches"]),
        "shot_and_aggregate_verified": len(ledger["verified_rows"]),
        "xg_pending": pending_xg,
        "days_not_scanned": len(pending_days),
        "failed_days": dict(ledger["failed_days"]),
        "expected_ids_missing": unavailable,
        "independent_reconciliation_complete": (expected_game_ids is not None and bool(expected)
                                                and not pending_days and not ledger["failed_days"]
                                                and not unavailable),
        "unknown_competition_events": ledger["uncertain_competition_events"],
        "unassigned_game_ids": sorted(ledger.get("unassigned_games", {})),
        "note": "Not proof of provider historical completeness without independent fixture reconciliation."
    }



def sync_private_history(ledger, path):
    """Append only aggregate-reconciled XGQ rows to the existing private D1 cache.

    Unresolved fixtures stay in the separate private catalog; they NEVER become
    estimated XGQ values. This function does not make anything public.
    """
    from .private_history import verified_row
    path = Path(path)
    previous = json.loads(path.read_text(encoding="utf8")) if path.exists() else []
    if not isinstance(previous, list):
        raise ValueError("Invalid existing private history")
    by_id = {r["id"]: verified_row(r) for r in previous}
    if len(by_id) != len(previous):
        raise ValueError("Duplicate existing private shot history")
    added = 0
    for mid, row in ledger["verified_rows"].items():
        verified_row(row)
        if row["league"] != ledger["league"] or str(row["source_match_id"]) != str(mid):
            raise ValueError("Source identity conflict in newly verified XGQ row")
        if row["id"] in by_id:
            if by_id[row["id"]].get("source_match_id") != row["source_match_id"]:
                raise ValueError("Cross-provider match identity conflict")
            continue
        by_id[row["id"]] = row
        added += 1
    _save_atomic(path, list(by_id.values()))
    return added


def run(argv=None, *, transport=None):
    ap = argparse.ArgumentParser(description="Private 365Scores season fixture ledger (no dropped games)")
    ap.add_argument("--competition-id", required=True)
    ap.add_argument("--league", required=True, choices=tuple(provider365.KNOWN_LEAGUES))
    ap.add_argument("--start", required=True, help="YYYY-MM-DD")
    ap.add_argument("--end", required=True, help="YYYY-MM-DD")
    ap.add_argument("--output", required=True, help="Private filesystem path; never commit")
    ap.add_argument("--max-days", type=int, default=MAX_DAYS_PER_RUN)
    ap.add_argument("--max-details", type=int, default=0)
    ap.add_argument("--through", help="YYYY-MM-DD; stop at this day, never scan future season dates")
    ap.add_argument("--expected-ids", help="Optional independently obtained JSON game ID array")
    ap.add_argument("--history-output", help="Existing private_365_history.json (for validated rows only)")
    options = ap.parse_args(argv)
    _require_authorization()
    if not 1 <= options.max_days <= MAX_DAYS_PER_RUN:
        ap.error("--max-days must be 1..14")
    if not 0 <= options.max_details <= MAX_DETAILS_PER_RUN:
        ap.error("--max-details must be 0..48")
    ledger = load_or_create(options.output, options.competition_id,
                            options.league, options.start, options.end)
    d, end = date.fromisoformat(options.start), date.fromisoformat(options.end)
    through = date.fromisoformat(options.through) if options.through else date.today()
    end = min(end, through)
    processed = 0
    while d <= end and processed < options.max_days:
        day = d.isoformat()
        d += timedelta(days=1)
        if day in ledger["scanned_days"]:
            continue
        try:
            scan_day(ledger, day, transport=transport)
        except provider365.AccessDenied as exc:
            ledger["failed_days"][day] = str(exc)[:240]
            _save_atomic(options.output, ledger)
            break   # never bypass or immediately retry 401/403/429
        except (OSError, ValueError, TypeError, KeyError) as exc:
            ledger["failed_days"][day] = str(exc)[:240]
        _save_atomic(options.output, ledger)
        processed += 1
    if options.max_details:
        try:
            refresh_details(ledger, transport=transport, limit=options.max_details)
        finally:
            _save_atomic(options.output, ledger)
    expected = None
    if options.expected_ids:
        expected = json.loads(Path(options.expected_ids).read_text(encoding="utf8"))
        if not isinstance(expected, list):
            raise ValueError("Expected fixture IDs must be a JSON array")
    status = audit(ledger, expected)
    # The full-season audit includes future dates. A daily run evaluates
    # coverage only up to the requested 'through' date without misreporting
    # unplayed fixtures as missed.
    daily_start = date.fromisoformat(options.start)
    elapsed = max(0, (end - daily_start).days + 1)
    status["days_not_scanned_through"] = max(
        0, elapsed - len([d for d in ledger["scanned_days"]
                         if options.start <= d <= end.isoformat()])
    )
    status["through_date"] = end.isoformat()
    if options.history_output:
        status["new_model_eligible_rows"] = sync_private_history(ledger, options.history_output)
    print(json.dumps(status, ensure_ascii=False, indent=2))
    return status


if __name__ == "__main__":
    run()
