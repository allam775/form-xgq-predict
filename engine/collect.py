"""Build a truthful shot-level-XGQ forecast snapshot from public sources.

Requires network access for live refresh (e.g. GitHub Actions); no commercial API.
Results-only OpenFootball is used for fixture schedules, NEVER XGQ labels.
"""
from __future__ import annotations
import argparse
from datetime import date, datetime, timezone, timedelta
import json
import os
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import HTTPError, URLError
import time
import re
from .xgq import normalized, strict_row, statsbomb_to_row, predict_xgq, holdout_metrics

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUTPUT = ROOT / "generated"
STATS_BOMB = "https://raw.githubusercontent.com/hudl/open-data/master/data"
FOOTBALL = "https://raw.githubusercontent.com/openfootball/football.json/master"
LEAGUES = {"en.1": "Premier League", "de.1": "Bundesliga", "es.1": "La Liga",
           "it.1": "Serie A", "fr.1": "Ligue 1"}


def fetch_json(url, max_bytes=9_000_000):
    if not url.startswith((STATS_BOMB, FOOTBALL, "https://")):
        raise ValueError("HTTPS required")
    req = Request(url, headers={"User-Agent": "XGQ-Standalone-Research/0.1", "Accept": "application/json"})
    for attempt in range(3):
        try:
            with urlopen(req, timeout=25) as response:
                raw = response.read(max_bytes + 1)
            if len(raw) > max_bytes:
                raise ValueError("Upstream data exceeds size gate")
            return json.loads(raw)
        except (URLError, TimeoutError, HTTPError):
            if attempt >= 2:
                raise
            time.sleep(1 + attempt)


def read_json(path, default):
    return json.loads(path.read_text(encoding="utf8")) if path.exists() else default


# Discover available, legally published open-data competitions rather than
# hard-coding one old La Liga season. These are *historical* datasets, NOT live feeds.
STATS_BOMB_LEAGUE_IDS = {11: "es.1", 2: "en.1", 9: "de.1", 12: "it.1", 7: "fr.1"}


def choose_open_seasons(competitions, max_seasons_per_league=2):
    """Pure, bounded selector that prioritizes recent available seasons per league."""
    found = {}
    for item in competitions:
        if not isinstance(item, dict):
            continue
        comp, season = item.get("competition_id"), item.get("season_id")
        label = str(item.get("season_name", ""))
        if comp not in STATS_BOMB_LEAGUE_IDS or not isinstance(season, int):
            continue
        years = re.findall(r"(?:19|20)\d{2}", label)
        if not years:
            continue
        found.setdefault(comp, []).append((int(years[-1]), season))
    # Interleave leagues to avoid one archive consuming an entire daily quota.
    groups = []
    for comp in sorted(found):
        seasons = sorted(set(found[comp]), reverse=True)[:max_seasons_per_league]
        groups.append([(comp, sid) for _, sid in seasons])
    output = []
    for idx in range(max_seasons_per_league):
        output.extend(group[idx] for group in groups if idx < len(group))
    return output


def shot_archive(offline=False, max_matches=80, selections=None):
    cache = DATA / "shot_history.json"
    existing = read_json(cache, [])
    rows = {r["id"]: r for r in existing if isinstance(r, dict) and "id" in r}
    details = {"cached": len(rows), "imported_statsbomb": 0, "invalid": 0, "unavailable": 0,
               "open_seasons_examined": 0}
    if offline:
        return list(rows.values()), details
    if selections is None:
        # Source list remains discoverable if StatsBomb adds further freely
        # published seasons. No guarantee of current-competition coverage.
        competitions = fetch_json(f"{STATS_BOMB}/competitions.json", max_bytes=2_000_000)
        if not isinstance(competitions, list):
            raise ValueError("StatsBomb competition index is invalid")
        selections = choose_open_seasons(competitions)
    if not selections:
        raise ValueError("No eligible open-data competition seasons")
    pending=[]
    known_match_ids = {str(r.get("source_match_id")) for r in rows.values()
                       if r.get("source") == "StatsBomb Open Data"}
    for comp, season in selections:
        try:
            index = fetch_json(f"{STATS_BOMB}/matches/{comp}/{season}.json", max_bytes=4_000_000)
        except (HTTPError, URLError, ValueError, TimeoutError):
            details["unavailable"] += 1
            continue
        details["open_seasons_examined"] += 1
        if not isinstance(index, list):
            details["invalid"] += 1
            continue
        eligible=[]
        for match in sorted(index, key=lambda x: x.get("match_date", ""), reverse=True):
            mid=str(match.get("match_id", ""))
            if mid.isdigit() and mid not in known_match_ids and isinstance(match.get("home_score"), int) and isinstance(match.get("away_score"), int):
                eligible.append(match)
        pending.append((comp, eligible))
    # Balanced round-robin across leagues and seasons: one source cannot
    # indefinitely starve every other competition of new shot-level events.
    imported=0
    while imported < max_matches and any(queue for _, queue in pending):
        advanced=False
        for comp, queue in pending:
            if imported >= max_matches:
                break
            if not queue:
                continue
            match=queue.pop(0)
            mid=str(match["match_id"])
            if mid in known_match_ids:
                continue
            try:
                events=fetch_json(f"{STATS_BOMB}/events/{mid}.json", max_bytes=13_000_000)
                row=statsbomb_to_row(match, events, STATS_BOMB_LEAGUE_IDS.get(comp, f"statsbomb.{comp}"))
                rows[row["id"]]=row
                known_match_ids.add(mid)
                imported+=1
                details["imported_statsbomb"]+=1
                advanced=True
            except (ValueError, KeyError, TypeError, HTTPError, URLError, TimeoutError):
                details["invalid"]+=1
        if not advanced and not any(queue for _,queue in pending):
            break
    return list(rows.values()), details


def ingest_verified_feed(history, feed_path):
    """Optional owner's XGQ export: real full shot xG arrays for completed matches."""
    payload = read_json(Path(feed_path), [])
    if not isinstance(payload, list):
        raise ValueError("Owner shot feed must be a list of completed matches")
    existing = {r["id"]: r for r in history}
    rejected = 0
    for raw in payload:
        try:
            row = strict_row(raw)
            if any(tag in row["source"].lower() for tag in ("illustrative", "synthetic", "example", "demo", "fake")):
                raise ValueError("Non-production shot feed labels are not publishable")
            existing[row["id"]] = row
        except (ValueError, KeyError, TypeError):
            rejected += 1
    if rejected:
        raise ValueError(f"Owner feed had {rejected} invalid / aggregate-only entries")
    return list(existing.values())


def find_fixtures(today, offline=False):
    if offline:
        return read_json(DATA / "fixtures.json", []), []
    issues = []
    season = f"{today.year}-{(today.year + 1) % 100:02d}" if today.month >= 7 else f"{today.year - 1}-{today.year % 100:02d}"
    fixtures = []
    for league, display in LEAGUES.items():
        try:
            source = fetch_json(f"{FOOTBALL}/{season}/{league}.json", max_bytes=4_000_000)
            for m in source.get("matches", []):
                match_date = str(m.get("date", ""))[:10]
                try:
                    match_day = date.fromisoformat(match_date)
                except ValueError:
                    continue
                if not today <= match_day <= today + timedelta(days=21):
                    continue
                if m.get("score") is not None:
                    continue
                home, away = str(m.get("team1", "")).strip(), str(m.get("team2", "")).strip()
                if not normalized(home) or not normalized(away) or normalized(home) == normalized(away):
                    continue
                fixtures.append({"league": league, "league_name": display, "date": match_date,
                                 "home_team": home, "away_team": away,
                                 "time_source": m.get("time") if isinstance(m.get("time"), str) else None,
                                 "kickoff_status": "unverified_source_timezone"})
        except (HTTPError, URLError, ValueError, TimeoutError) as exc:
            issues.append(f"{league}: source not available ({type(exc).__name__})")
    return fixtures, issues


def make_snapshot(history, fixtures, today):
    history = sorted((r for r in history if r["date"] < today.isoformat()), key=lambda r: r["date"])
    if len({r["id"] for r in history}) != len(history):
        raise ValueError("Duplicate shot match identity")
    all_forecasts, unavailable = [], []
    for f in fixtures:
        pred, reason = predict_xgq(f, history, today.isoformat())
        if pred:
            pred["league_name"] = f.get("league_name", f["league"])
            pred["kickoff_status"] = f.get("kickoff_status", "unknown")
            pred["time_source"] = f.get("time_source")
            pred["same_day_unverified"] = pred["date"] == today.isoformat()
            all_forecasts.append(pred)
        else:
            unavailable.append({"league": f["league"], "date": f["date"],
                                "home": f["home_team"], "away": f["away_team"], "reason": reason})
    return {"schema_version": 1, "generated_at": datetime.now(timezone.utc).isoformat(),
            "as_of": today.isoformat(), "coverage": {
                "verified_shot_matches": len(history),
                "scheduled_fixtures": len(fixtures), "xgq_forecasts": len(all_forecasts),
                "withheld_no_verified_xgq": len(unavailable)},
            "model": "verified-shot-xgq-poisson-v1", "forecasts": all_forecasts,
            "unavailable": unavailable[:400], "evaluation": holdout_metrics(history, today.isoformat()),
            "provenance": ["StatsBomb Open Data (attribution required)",
                            "OpenFootball fixtures (not shot data)"]}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true", help="Read only local data/shot_history.json and data/fixtures.json")
    ap.add_argument("--as-of", help="YYYY-MM-DD override for reproducible tests")
    ap.add_argument("--max-new-matches", type=int, default=80)
    ap.add_argument("--verified-feed", help="JSON file of complete owner XGQ shot arrays")
    ap.add_argument("--verified-feed-url", default=os.getenv("XGQ_SHOT_FEED_URL"), help="HTTPS URL of your OWN verified shot-level JSON export")
    ap.add_argument("--statsbomb-selections", default="auto", help="auto (latest open seasons per league) or comp:season list")
    opts = ap.parse_args(argv)
    today = date.fromisoformat(opts.as_of) if opts.as_of else date.today()
    combos = []
    if opts.statsbomb_selections.strip().lower() != "auto":
        for part in opts.statsbomb_selections.split(","):
            if part.strip():
                a,b = part.split(":")
                combos.append((int(a),int(b)))
    history, shot_health = shot_archive(opts.offline, opts.max_new_matches,
                                        combos if combos else None)
    if opts.verified_feed_url:
        if not re.fullmatch(r"https://[^\s?#]+(?:\?[^\s#]*)?", opts.verified_feed_url):
            raise ValueError("Online XGQ source must be HTTPS")
        owner_payload = fetch_json(opts.verified_feed_url, max_bytes=9_000_000)
        if not isinstance(owner_payload, list):
            raise ValueError("Online XGQ source must return list of complete shot-level matches")
        feed_temp = OUTPUT / ".verified-feed-pending.json"
        OUTPUT.mkdir(exist_ok=True)
        try:
            feed_temp.write_text(json.dumps(owner_payload), encoding="utf8")
            history = ingest_verified_feed(history, feed_temp)
        finally:
            feed_temp.unlink(missing_ok=True)
    if opts.verified_feed:
        history = ingest_verified_feed(history, opts.verified_feed)
    fixtures, issues = find_fixtures(today, opts.offline)
    snapshot = make_snapshot(history, fixtures, today)
    snapshot["collection"] = shot_health
    # Club crest URLs are opt-in, with documented display permission / attribution.
    logos = read_json(ROOT / "config" / "club_logos.json", {})
    for pred in snapshot["forecasts"]:
        for side in ("home", "away"):
            entry = logos.get(normalized(pred[side]))
            if isinstance(entry, dict) and entry.get("permission_verified") is True and \
                    str(entry.get("url", "")).startswith("https://") and entry.get("license_note"):
                pred[f"{side}_logo_url"] = entry["url"]
    snapshot["source_warnings"] = issues
    # Guard against upstream failure overwriting good history with an empty snapshot.
    if not opts.offline and not history:
        raise RuntimeError("No verified shot-level source data: refusing to publish")
    # Cache real/verified shot metrics; never include a synthetic XGQ fallback.
    DATA.mkdir(exist_ok=True)
    OUTPUT.mkdir(exist_ok=True)
    tmp = DATA / "shot_history.json.tmp"
    tmp.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf8")
    tmp.replace(DATA / "shot_history.json")
    p = OUTPUT / "snapshot.json.tmp"
    p.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf8")
    p.replace(OUTPUT / "snapshot.json")
    print(f"Verified shot matches: {len(history)}; fixtures: {len(fixtures)}; "
          f"honest XGQ forecasts: {len(snapshot['forecasts'])}; withheld: {len(snapshot['unavailable'])}")
    return snapshot


if __name__ == "__main__":
    main()
