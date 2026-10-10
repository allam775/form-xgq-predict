"""Public shot archive quality audit; never imports third-party/private data.

All percentages refer to what the open-source PROVIDER published, not entire
official competition fixtures.  Older historical evidence cannot establish
fresh form in the current season.  This report is safe to commit to GitHub.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import date
import json
from pathlib import Path
from .xgq import normalized

# Verified from StatsBomb's *published match indexes*, 2026-10-10.
# These are not the official league fixture totals; Ligue 1 has 377 entries.
PUBLISHED_MATCH_INDEX_2015_16 = {
    "en.1": 380,
    "fr.1": 377,
    "it.1": 380,
}
OPEN_SOURCE = "StatsBomb Open Data"


def season_start_day(day: str) -> int:
    d = date.fromisoformat(day)
    return d.year if d.month >= 7 else d.year - 1


def audit_public_history(history, *, as_of: date | None = None):
    as_of = as_of or date.today()
    if not isinstance(history, list):
        raise ValueError("Public archive must be a JSON array")
    ids = set()
    source_ids = set()
    by_league = defaultdict(list)
    by_league_season = Counter()
    for r in history:
        if not isinstance(r, dict) or r.get("source") != OPEN_SOURCE:
            raise ValueError("Refusing to publish an archive audit containing private/other-source data")
        required = ("id", "source_match_id", "date", "league", "h", "a", "home_xgq", "away_xgq")
        if not all(r.get(k) is not None for k in required):
            raise ValueError("Invalid source-derived historical match identity or XGQ")
        if r["id"] in ids or r["source_match_id"] in source_ids:
            raise ValueError("Duplicate verified match identity in archive")
        ids.add(r["id"])
        source_ids.add(r["source_match_id"])
        d = date.fromisoformat(r["date"])
        if d > as_of:
            raise ValueError("Historical verified match has a future date")
        if not r["league"] or not normalized(r["h"]) or not normalized(r["a"]) or r["h"] == r["a"]:
            raise ValueError("Invalid league or two distinct competing teams are missing")
        for col in ("home_xgq", "away_xgq"):
            v = r[col]
            if type(v) not in (float, int) or not 0 <= v <= 1:
                raise ValueError("Invalid per-shot XGQ")
        by_league[r["league"]].append(r)
        by_league_season[(r["league"], season_start_day(r["date"]))] += 1

    leagues = {}
    recent_total = 0
    for league, entries in sorted(by_league.items()):
        games = sorted(entries, key=lambda x: x["date"])
        teams = Counter()
        by_season = {}
        for row in games:
            teams[normalized(row["h"])] += 1
            teams[normalized(row["a"])] += 1
        for (lg, year), n in sorted(by_league_season.items()):
            if lg == league:
                by_season[f"{year}/{str(year+1)[-2:]}"] = n
        last = date.fromisoformat(games[-1]["date"])
        recent = sum((as_of - date.fromisoformat(x["date"])).days <= 120 for x in games)
        recent_total += recent
        leagues[league] = {
            "matches": len(games),
            "first_match_date": games[0]["date"],
            "last_match_date": games[-1]["date"],
            "last_match_age_days": (as_of - last).days,
            "within_120_days": recent,
            "teams": len(teams),
            "teams_with_5_or_more_matches": sum(n >= 5 for n in teams.values()),
            "teams_with_16_or_more_matches": sum(n >= 16 for n in teams.values()),
            "season_coverage": by_season,
        }
    published_2015 = {}
    for league, expected in PUBLISHED_MATCH_INDEX_2015_16.items():
        count = by_league_season[(league, 2015)]
        published_2015[league] = {
            "verified": count,
            "published_index_matches": expected,
            "remaining_from_published_index": max(0, expected - count),
            "ratio": round(min(1, count / expected), 4),
        }
    total = len(history)
    max_share = max((len(v)/total for v in by_league.values()), default=0)
    return {
        "status": "audited",
        "as_of": as_of.isoformat(),
        "source": OPEN_SOURCE,
        "matches": total,
        "unique_match_ids": len(ids),
        "league_count": len(by_league),
        "largest_league_fraction": round(max_share, 4),
        "last_verified_match": max((x["date"] for x in history), default=None),
        "matches_within_120_days": recent_total,
        "historical_only_not_live_form": recent_total == 0,
        "leagues": leagues,
        "published_2015_16_coverage": published_2015,
        "notes": [
            "This report audits StatsBomb Open Data only; no private provider rows.",
            "Published indexes are not official league season totals.",
            "Different xG providers require independent calibration before mixing.",
            "Old historical rows alone do not validate a forecast for 2026 fixtures.",
        ],
    }


def main(argv=None):
    p = argparse.ArgumentParser(description="Audit verified public historical XGQ dataset")
    p.add_argument("--input", default="data/shot_history.json")
    p.add_argument("--output", default="reports/open_data_archive_quality.json")
    p.add_argument("--as-of", help="Override YYYY-MM-DD for reproducibility")
    opts = p.parse_args(argv)
    records = json.loads(Path(opts.input).read_text(encoding="utf8"))
    report = audit_public_history(records, as_of=date.fromisoformat(opts.as_of) if opts.as_of else None)
    dest = Path(opts.output)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf8")
    print(f"Public archive audited: {report['matches']} verified matches in "
          f"{report['league_count']} leagues, recent-120d={report['matches_within_120_days']}")
    return report


if __name__ == "__main__":
    main()
