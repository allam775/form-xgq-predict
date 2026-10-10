"""Private D1 persistence for 365Scores-derived, verified MATCH summaries.

No raw event streams, credentials, or provider response payloads are stored.
This module does not grant rights to store/use provider data. Only run after
confirming authorization, and NEVER commit decoded private history to GitHub.
"""
from __future__ import annotations

import argparse
from datetime import date
import json
import math
from pathlib import Path
import re

from .xgq import normalized

MAX_PRIVATE_MATCHES = 20000
SOURCE = "365Scores (opt-in; rights required)"


def verified_row(row):
    """Validate a compact existing XGQ row before restoring it from private D1."""
    if not isinstance(row, dict) or row.get("source") != SOURCE:
        raise ValueError("Unrecognized private source")
    if row.get("league") not in ("en.1", "de.1", "es.1", "it.1", "fr.1"):
        raise ValueError("Invalid private league")
    dt = date.fromisoformat(row["date"]).isoformat()
    h, a = normalized(row.get("home")), normalized(row.get("away"))
    identity = f"{row['league']}|{dt}|{h}|{a}"
    if not h or not a or h == a or row.get("id") != identity:
        raise ValueError("Invalid private match identity")
    mid = row.get("source_match_id")
    if not isinstance(mid, str) or not re.fullmatch(r"[1-9][0-9]{1,13}", mid):
        raise ValueError("Invalid private source match ID")
    if row.get("h") != h or row.get("a") != a:
        raise ValueError("Invalid normalized team IDs")
    if any(type(row.get(k)) is not int or not (0 <= row[k] <= 30)
           for k in ("hg", "ag")):
        raise ValueError("Invalid final result")
    for side in ("home", "away"):
        shots = row.get(f"{side}_shots")
        xg = row.get(f"{side}_xg")
        xgq = row.get(f"{side}_xgq")
        if type(shots) is not int or not 1 <= shots <= 150:
            raise ValueError("Invalid historical shot count")
        if any(type(v) not in (int, float) or not math.isfinite(v) for v in (xg, xgq)):
            raise ValueError("Invalid historical xG values")
        if not 0 <= xg <= shots or not 0 <= xgq <= 1:
            raise ValueError("Out-of-range historical xG")
    return row


def decode_wrangler_result(payload):
    """Wrangler `d1 execute --remote --json` produces [{success,results:[...]}]."""
    if not isinstance(payload, list) or not payload:
        raise ValueError("Private D1 read result missing")
    items = []
    for batch in payload:
        if not isinstance(batch, dict) or batch.get("success") is not True or not isinstance(batch.get("results"), list):
            raise ValueError("Private D1 read was not confirmed successful")
        for result in batch["results"]:
            if not isinstance(result, dict) or not isinstance(result.get("payload"), str):
                raise ValueError("Malformed private D1 result row")
            items.append(verified_row(json.loads(result["payload"])))
            if len(items) > MAX_PRIVATE_MATCHES:
                raise ValueError("Private history exceeds configured safety gate")
    if len(set(r["id"] for r in items)) != len(items):
        raise ValueError("Duplicate rows in private D1 history")
    return items


def quote(text):
    return "'" + str(text).replace("'", "''") + "'"


def export_sql(history, destination):
    """Idempotent UPSERT, with no DELETE or public forecast surface."""
    private_rows = [verified_row(r) for r in history if isinstance(r, dict) and r.get("source") == SOURCE]
    if len(private_rows) > MAX_PRIVATE_MATCHES or len(set(r["id"] for r in private_rows)) != len(private_rows):
        raise ValueError("Invalid private export size or duplicate rows")
    statements = [
        "INSERT OR REPLACE INTO private_shot_history(id,payload) VALUES (" +
        quote(r["id"]) + "," + quote(json.dumps(r, ensure_ascii=False, separators=(",", ":"))) + ");"
        for r in private_rows
    ]
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("\n".join(statements) + "\n" if statements else "-- No new private history to persist.\n", encoding="utf8")
    return len(private_rows)


def main(argv=None):
    parser = argparse.ArgumentParser()
    actions = parser.add_subparsers(dest="operation", required=True)
    for op in ("decode", "export"):
        p = actions.add_parser(op)
        p.add_argument("--input", required=True)
        p.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    raw = json.loads(Path(args.input).read_text(encoding="utf8"))
    if args.operation == "decode":
        rows = decode_wrangler_result(raw)
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(json.dumps(rows, ensure_ascii=False), encoding="utf8")
        print(f"Restored {len(rows)} private verified match summaries from D1")
    else:
        if not isinstance(raw, list):
            raise ValueError("History JSON must be an array")
        count = export_sql(raw, args.output)
        print(f"Prepared {count} private match summaries for D1")


if __name__ == "__main__":
    main()
