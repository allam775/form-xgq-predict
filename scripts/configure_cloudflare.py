"""Inject the D1 binding ID supplied through a GitHub Actions secret."""
import json
import os
from pathlib import Path
p = Path(__file__).resolve().parents[1] / "wrangler.jsonc"
value = os.environ.get("CF_D1_DATABASE_ID", "")
if not value or not all(c in "0123456789abcdefABCDEF-" for c in value) or len(value) < 30:
    raise SystemExit("Configure the CF_D1_DATABASE_ID repository secret with your real D1 database ID")
data = json.loads(p.read_text(encoding="utf8"))
data["d1_databases"][0]["database_id"] = value
p.write_text(json.dumps(data, indent=2), encoding="utf8")
print("D1 binding injected without publishing any tokens")
