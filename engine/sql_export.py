"""Produce a D1 compatible generation-gated SQL snapshot (no secrets)."""
import json
from pathlib import Path
from .collect import ROOT, OUTPUT


def quote(value):
    if value is None:
        return "NULL"
    return "'" + str(value).replace("'", "''") + "'"


def export(snapshot, destination):
    if snapshot.get("schema_version") != 1:
        raise ValueError("Unsupported snapshot schema")
    if snapshot["coverage"]["xgq_forecasts"] != len(snapshot["forecasts"]):
        raise ValueError("Count mismatch")
    ids = [r["id"] for r in snapshot["forecasts"]]
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate forecast IDs")
    # D1 deliberately refuses BEGIN/COMMIT in SQL imports. Instead stage a full
    # new generation and switch a single metadata pointer LAST. If an import
    # aborts before the pointer change, readers still see the previous release.
    generation = snapshot["generated_at"]
    out = [
        "DELETE FROM forecasts WHERE generation != COALESCE((SELECT v FROM metadata WHERE k='published_generation'), '');",
        "DELETE FROM unavailable WHERE generation != COALESCE((SELECT v FROM metadata WHERE k='published_generation'), '');",
        "DELETE FROM release_metadata WHERE generation != COALESCE((SELECT v FROM metadata WHERE k='published_generation'), '');",
    ]
    for row in snapshot["forecasts"]:
        if row.get("source_basis") != "verified_shot_level_xg":
            raise ValueError("Reject results-only predictions")
        val = json.dumps(row, ensure_ascii=False, separators=(",", ":"))
        out.append("INSERT OR REPLACE INTO forecasts(generation,id,fixture_date,league,home,away,payload) VALUES ("+
                   ",".join(quote(x) for x in [generation,row["id"],row["date"],row["league"],row["home"],row["away"],val])+");")
    for row in snapshot["unavailable"]:
        identity = f"{row['league']}|{row['date']}|{row['home']}|{row['away']}"
        out.append("INSERT OR REPLACE INTO unavailable(generation,id,fixture_date,league,home,away,reason) VALUES ("+
                   ",".join(quote(x) for x in [generation,identity,row["date"],row["league"],row["home"],row["away"],row["reason"]])+");")
    meta = {"generated_at": snapshot["generated_at"], "as_of": snapshot["as_of"],
            "coverage": json.dumps(snapshot["coverage"]),
            "evaluation": json.dumps(snapshot["evaluation"]),
            "collection": json.dumps(snapshot.get("collection", {})),
            "source_warnings": json.dumps(snapshot.get("source_warnings", []))}
    for key, value in meta.items():
        out.append("INSERT OR REPLACE INTO release_metadata(generation,k,v) VALUES ("+quote(generation)+","+quote(key)+","+quote(value)+");")
    # Publication point: MUST be the final statement.
    out.append("INSERT OR REPLACE INTO metadata(k,v) VALUES ('published_generation',"+quote(generation)+");")
    destination.parent.mkdir(exist_ok=True,parents=True)
    destination.write_text("\n".join(out)+"\n",encoding="utf8")
    return len(ids)


def main():
    snapshot=json.loads((OUTPUT/"snapshot.json").read_text(encoding="utf8"))
    n=export(snapshot,OUTPUT/"snapshot.sql")
    print(f"D1 SQL exported: {n} shot-level forecasts")

if __name__ == "__main__":
    main()
