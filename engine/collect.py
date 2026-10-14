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
from collections import Counter
from .xgq import normalized, strict_row, statsbomb_to_row, predict_xgq, holdout_metrics

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUTPUT = ROOT / "generated"
STATS_BOMB = "https://raw.githubusercontent.com/hudl/open-data/master/data"
FOOTBALL = "https://raw.githubusercontent.com/openfootball/football.json/master"
LEAGUES = {"en.1": "Premier League", "de.1": "Bundesliga", "es.1": "La Liga",
           "it.1": "Serie A", "fr.1": "Ligue 1", "uefa.cl": "UEFA Champions League", "pt.1": "Primeira Liga"}


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

# Source-catalog checked 2026-10-10: unusually COMPLETE top-flight
# seasons. Finish an actual season before chasing sparse one-club archives.
# Every match still requires original per-shot StatsBomb xG event evidence.
DENSE_OPEN_COHORTS = ((2, 27), (7, 27), (12, 27))


def prioritize_dense_cohort(selections, pending, league_counts=None):
    """Finish dense published seasons; first help the least represented league.

    league_counts uses only existing source-verified StatsBomb match rows. On
    repeated cloud runs, the focus moves as the smaller archives catch up.
    Explicit user-supplied season selections never call this selector.
    """
    by_pair = {(comp, season): (comp, queue) for (comp, season, queue) in pending}
    candidates = [pair for pair in DENSE_OPEN_COHORTS
                  if pair in selections and pair in by_pair and by_pair[pair][1]]
    if candidates:
        # For backwards-compatible callers without counts, preserve published
        # source priority. Tie-break by deterministic official source ordering.
        if league_counts is not None:
            candidates.sort(key=lambda pair: (league_counts.get(pair[0], 0),
                                              DENSE_OPEN_COHORTS.index(pair)))
        chosen = candidates[0]
        return [by_pair[chosen]], chosen
    return [(comp, queue) for comp, season, queue in pending], None


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


def planned_open_shot_import_quota(max_matches, target_size, cached_rows):
    """Bound public StatsBomb imports without counting private or other-source rows."""
    if target_size is None:
        return max_matches
    current = {r['id'] for r in cached_rows
               if isinstance(r, dict) and isinstance(r.get('id'), str)
               and r.get('source') == 'StatsBomb Open Data'}
    return min(max_matches, max(0, target_size - len(current)))


def shot_archive(offline=False, max_matches=80, selections=None, max_seasons_per_league=2):
    cache = DATA / "shot_history.json"
    existing = read_json(cache, [])
    rows = {r["id"]: r for r in existing if isinstance(r, dict) and "id" in r}
    details = {"cached": len(rows), "imported_statsbomb": 0, "invalid": 0, "unavailable": 0,
               "open_seasons_examined": 0}
    if offline or max_matches == 0:
        return list(rows.values()), details
    automatic = selections is None
    if automatic:
        # Source list remains discoverable if StatsBomb adds further freely
        # published seasons. No guarantee of current-competition coverage.
        competitions = fetch_json(f"{STATS_BOMB}/competitions.json", max_bytes=2_000_000)
        if not isinstance(competitions, list):
            raise ValueError("StatsBomb competition index is invalid")
        discovered = choose_open_seasons(competitions, max_seasons_per_league)
        available = {(x.get("competition_id"), x.get("season_id")) for x in competitions
                     if isinstance(x, dict)}
        selections = [pair for pair in DENSE_OPEN_COHORTS if pair in available]
        selections += [pair for pair in discovered if pair not in selections]
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
        # Feed chronological seasons from kickoff onwards; prevent random slices
        # or newest-game-first sampling that starves the team's early form.
        for match in sorted(index, key=lambda x: (x.get("match_date", ""), x.get("match_id", 0))):
            mid=str(match.get("match_id", ""))
            if mid.isdigit() and mid not in known_match_ids and isinstance(match.get("home_score"), int) and isinstance(match.get("away_score"), int):
                eligible.append(match)
        pending.append((comp, season, eligible))
    if automatic:
        league_counts = Counter(int(comp) for row in rows.values()
                                if row.get("source") == "StatsBomb Open Data"
                                for comp, league in STATS_BOMB_LEAGUE_IDS.items()
                                if row.get("league") == league)
        pending, chosen = prioritize_dense_cohort(selections, pending, league_counts)
        if chosen is not None:
            details["focus_open_cohort"] = {"competition_id": chosen[0], "season_id": chosen[1]}
            details["focus_reason"] = "least_represented_full_season"
    else:
        pending = [(comp, queue) for comp, season, queue in pending]
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
        # Do not mix Understat/StatsBomb/365Scores xG scales in one prediction.
        from .team_form import select_history_for_fixture
        cohort, _ = select_history_for_fixture(history, f, today.isoformat())
        pred, reason = predict_xgq(f, cohort, today.isoformat())
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
                # Publication time is NOT the date of the underlying shot evidence.
                # Keep these separate to avoid presenting historical data as live.
                "latest_verified_match": max(r["date"] for r in history) if history else None,
                "scheduled_fixtures": len(fixtures), "xgq_forecasts": len(all_forecasts),
                "withheld_no_verified_xgq": len(unavailable),
                "withheld_reasons": dict(sorted(Counter(
                    f["reason"] for f in unavailable).items()))},
            "model": "verified-shot-xgq-poisson-v1", "forecasts": all_forecasts,
            "unavailable": unavailable[:400], "evaluation": holdout_metrics([r for r in history if r.get("source")=="StatsBomb Open Data"], today.isoformat()),
            "provenance": ["StatsBomb Open Data (attribution required)",
                            "OpenFootball fixtures (not shot data)"]}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true", help="Read only local data/shot_history.json and data/fixtures.json")
    ap.add_argument("--as-of", help="YYYY-MM-DD override for reproducible tests")
    ap.add_argument("--max-new-matches", type=int, default=80)
    ap.add_argument("--target-history-size", type=int,
                    help="Optional target count for public StatsBomb shot matches; import only missing rows")
    ap.add_argument("--max-open-seasons", type=int, default=2,
                    help="Max open historical seasons selected per supported league (1..12)")
    ap.add_argument("--verified-feed", help="JSON file of complete owner XGQ shot arrays")
    ap.add_argument("--verified-feed-url", default=os.getenv("XGQ_SHOT_FEED_URL"), help="HTTPS URL of your OWN verified shot-level JSON export")
    ap.add_argument("--statsbomb-selections", default="auto", help="auto (latest open seasons per league) or comp:season list")
    ap.add_argument("--365-teams", default=os.environ.get("XGQ_365_TEAMS_FILE", ""),
                    help="Opt-in 365Scores team-ID mapping file (source terms and deployment rights apply)")
    ap.add_argument("--365-max-new", type=int, default=24,
                    help="Maximum newly inspected 365Scores games in this run (<=48)")
    opts = ap.parse_args(argv)
    if not 1 <= opts.max_open_seasons <= 12:
        ap.error("--max-open-seasons must be in [1,12]")
    if not 0 <= opts.max_new_matches <= 250:
        ap.error("--max-new-matches must be in [0,250]")
    if opts.target_history_size is not None and opts.target_history_size < 1:
        ap.error("--target-history-size must be a positive integer")
    today = date.fromisoformat(opts.as_of) if opts.as_of else date.today()
    combos = []
    if opts.statsbomb_selections.strip().lower() != "auto":
        for part in opts.statsbomb_selections.split(","):
            if part.strip():
                a,b = part.split(":")
                combos.append((int(a),int(b)))
    cached_rows = read_json(DATA / "shot_history.json", [])
    if not isinstance(cached_rows, list):
        raise ValueError("Invalid cached shot history")
    public_quota = planned_open_shot_import_quota(
        opts.max_new_matches, opts.target_history_size, cached_rows)
    history, shot_health = shot_archive(opts.offline, public_quota,
                                        combos if combos else None, opts.max_open_seasons)
    if opts.target_history_size is not None:
        shot_health['target_public_statsbomb_matches'] = opts.target_history_size
        shot_health['target_public_statsbomb_met'] = (
            sum(r.get('source') == 'StatsBomb Open Data' for r in history)
            >= opts.target_history_size)
    if opts.__dict__["365_teams"]:
        if opts.offline:
            raise ValueError("--offline cannot access 365Scores; omit --365-teams")
        from . import provider365
        if not provider365.enabled():
            raise RuntimeError("365Scores connector not enabled: set XGQ_365_ACCESS_AUTHORIZED=1 only if authorized")
        if not (provider365.publication_allowed() or provider365.private_only()):
            raise RuntimeError("365Scores connector requires either an authorized publication or an owner-confirmed private, Cloudflare-Access-protected deployment. Source usage rights still apply.")
        teams = provider365.read_teams(opts.__dict__["365_teams"])
        # GitHub public cache excludes 365Scores data by design. Restore the
        # private D1 summaries before the collector runs; fail closed if a
        # deployment that expects history cannot retrieve it.
        from .private_history import verified_row
        private_path = DATA / "private_365_history.json"
        if os.getenv("XGQ_365_REQUIRE_PRIVATE_HISTORY") == "1" and not private_path.exists():
            raise RuntimeError("Private 365 history D1 restore missing; refusing incomplete refresh")
        private_rows = read_json(private_path, [])
        if not isinstance(private_rows, list):
            raise ValueError("Invalid private history JSON")
        cached_ids = {r["id"] for r in history}
        for private_row in private_rows:
            verified_row(private_row)
            if private_row["id"] not in cached_ids:
                history.append(private_row)
                cached_ids.add(private_row["id"])
        if not teams:
            raise RuntimeError("365Scores team ID mapping is empty; no auto-discovery is attempted")
        aliases = read_json(ROOT / "config" / "365_aliases.json", {})
        if not isinstance(aliases, dict) or any(not isinstance(k,str) or not isinstance(v,str) for k,v in aliases.items()):
            raise ValueError("Invalid 365Scores team name aliases")
        history, results365 = provider365.collect(history, teams, max_new=opts.__dict__["365_max_new"], aliases=aliases)
        shot_health["provider365"] = results365
    # Rights-gated private Understat D1 import; disabled unless explicitly configured.
    from .understat_pipeline import run as run_understat
    history, understat_health = run_understat(history, asof=today)
    if understat_health.get('enabled'):
        shot_health['understat'] = understat_health
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
    if shot_health.get("provider365"):
        snapshot["provenance"].append("365Scores (opt-in source; subject to provider terms; private mode unless publication authorized)")
    if shot_health.get('understat'):
        snapshot['provenance'].append('Understat (private; owner-confirmed source rights)')
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
    # Report research honestly even when the open history is too sparse to
    # produce ANY out-of-sample prediction; never auto-promote parameters.
    from .research import benchmark
    report = benchmark([r for r in history if r.get("source") == "StatsBomb Open Data"])
    research_target = OUTPUT / "research_report.json"
    research_target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
    print(f"Historical research: {report['status']} ({report.get('reason', 'held-out evaluation')})")
    print(f"Verified shot matches: {len(history)}; fixtures: {len(fixtures)}; "
          f"honest XGQ forecasts: {len(snapshot['forecasts'])}; withheld: {len(snapshot['unavailable'])}")
    return snapshot


if __name__ == "__main__":
    main()
