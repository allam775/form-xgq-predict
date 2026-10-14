"""Transfer *private* 365Scores fixture ledger checkpoints to/from Cloudflare D1.

Never publishes them in the public snapshot. All SQL uses fixed table names
and single-quoted escaped values. Wrangler auth lives in the runner secrets,
not in this Python module or GitHub.
"""
from __future__ import annotations
import argparse
from datetime import date
import json
from pathlib import Path

from .coverage365 import new_ledger, _save_atomic


def wrangler_rows(path):
    payload = json.loads(Path(path).read_text(encoding="utf8"))
    if not isinstance(payload, list) or not payload:
        raise ValueError("Expected wrangler D1 --remote --json output array")
    rows = []
    for result in payload:
        if not isinstance(result, dict) or result.get("success") is not True or not isinstance(result.get("results"), list):
            raise ValueError("D1 did not confirm a successful read")
        rows.extend(result["results"])
    return rows


def restore(matches_input, days_input, verified_input, output, *, competition_id, league, start, end):
    ledger = new_ledger(competition_id, league, start, end)
    for row in wrangler_rows(matches_input):
        if str(row.get("competition_id")) != str(competition_id):
            raise ValueError("Mixed competition catalog is not permitted")
        key = str(row.get("id") or "")
        if not key:
            raise ValueError("Fixture missing game id")
        data = json.loads(row["payload"])
        if isinstance(data, dict) and "fixture_status" in data and "xg_status" in data:
            fixture = data
        else:
            # Initial read-only research staging already present in D1.
            mid = str(data.get("source_match_id") or key)
            fixture = {
                "id": mid if mid.isdecimal() else None,
                "competition_id": str(competition_id),
                "observed_date": data.get("date") or row.get("fixture_date"),
                "home": data.get("home", ""), "away": data.get("away", ""),
                "home_id": "", "away_id": "",
                "fixture_status": "final" if isinstance(data.get("hg"), int)
                                       and isinstance(data.get("ag"), int)
                                  else "not_final_or_unknown",
                "xg_status": "research_verified_not_released"
                             if row.get("status") == "research_verified_not_released"
                             else "pending_verification",
                "xg_issue": "preexisting_research_stage_no_training_release",
            }
        ledger["matches"][key] = fixture
    for row in wrangler_rows(days_input):
        if str(row.get("competition_id")) != str(competition_id):
            raise ValueError("Mixed competition day checkpoint")
        dt = row.get("scan_date")
        if not dt or not start <= dt <= end:
            raise ValueError("Unexpected day outside season window")
        status = str(row.get("scan_status"))
        if status == "complete":
            ledger["scanned_days"].append(dt)
        elif status == "failed":
            ledger["failed_days"][dt] = str(json.loads(row["payload"]).get("error") or "failed")
        else:
            raise ValueError("Unknown persisted day status")
    for row in wrangler_rows(verified_input):
        mid = str(row.get("id") or "")
        data = json.loads(row["payload"])
        if mid and str(data.get("source_match_id")) == mid and data.get("league") == league:
            # Preserve auditable aggregate-verified research data in a staging-only table.
            ledger["verified_rows"][mid] = data
        else:
            raise ValueError("Stored source-match identity conflict")
    ledger["scanned_days"] = sorted(set(ledger["scanned_days"]))
    _save_atomic(output, ledger)
    return {"restored_matches": len(ledger["matches"]), "restored_days": len(ledger["scanned_days"]),
            "staged_verified": len(ledger["verified_rows"])}


def quote(value):
    return "'" + str(value).replace("'", "''") + "'"


def upsert_sql(table, columns, values):
    quoted = ",".join(quote(value) for value in values)
    keys = ",".join(columns)
    updates = ",".join(f"{name}=excluded.{name}" for name in columns if name != "id")
    return f"INSERT INTO {table}({keys}) VALUES ({quoted}) ON CONFLICT(id) DO UPDATE SET {updates};"


def export_sql(path, sql_output):
    ledger = json.loads(Path(path).read_text(encoding="utf8"))
    if ledger.get("schema_version") != 1:
        raise ValueError("Unknown fixture catalog schema")
    cid, league = str(ledger["competition_id"]), str(ledger["league"])
    sql = ["-- Private 365Scores fixture/checkpoint upserts; no DELETE, no publication."]
    for key, item in sorted(ledger["matches"].items()):
        sql.append(upsert_sql("private_365_fixture_catalog",
            ("id", "competition_id", "league", "fixture_date", "status", "payload"),
            (key, cid, league, item.get("observed_date") or "", item.get("xg_status") or "not_checked",
             json.dumps(item, ensure_ascii=False, separators=(",", ":")))))
    for dt in sorted(set(ledger["scanned_days"]) | set(ledger["failed_days"])):
        done = dt in ledger["scanned_days"]
        sql.append(upsert_sql("private_365_coverage_days",
            ("id", "competition_id", "scan_date", "scan_status", "payload"),
            (f"{cid}|{dt}", cid, dt, "complete" if done else "failed",
             json.dumps({"day": dt, "error": ledger["failed_days"].get(dt)}, separators=(",", ":")))))
    for mid, item in sorted(ledger.get("verified_rows", {}).items()):
        sql.append(upsert_sql("private_365_coverage_verified",
            ("id", "payload"),
            (mid, json.dumps({**item, "training_release": False}, ensure_ascii=False, separators=(",", ":")))))
    target = Path(sql_output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(sql) + "\n", encoding="utf8")
    return {"fixtures": len(ledger["matches"]), "days": len(ledger["scanned_days"]),
            "verified_staged_not_released": len(ledger.get("verified_rows", {}))}


def main(argv=None):
    ap = argparse.ArgumentParser()
    commands = ap.add_subparsers(dest="cmd", required=True)
    r = commands.add_parser("restore")
    r.add_argument("--matches-input", required=True)
    r.add_argument("--days-input", required=True)
    r.add_argument("--verified-input", required=True)
    r.add_argument("--output", required=True)
    r.add_argument("--competition-id", required=True)
    r.add_argument("--league", required=True)
    r.add_argument("--start", required=True)
    r.add_argument("--end", required=True)
    e = commands.add_parser("export")
    e.add_argument("--input", required=True)
    e.add_argument("--output", required=True)
    args = ap.parse_args(argv)
    if args.cmd == "restore":
        result = restore(args.matches_input, args.days_input, args.verified_input,
                         args.output, competition_id=args.competition_id,
                         league=args.league, start=args.start, end=args.end)
    else:
        result = export_sql(args.input, args.output)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
