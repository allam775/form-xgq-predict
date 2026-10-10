# FORM / XGQ — Standalone forecasting site

**[Arabic installation and deployment instructions](README_AR.md)**

Independent website + Cloudflare Worker/D1 + scheduled open-data pipeline.

- **Strict verified XGQ only:** computed from per-shot xG, no fake results-only odds.
- **Source limitations:** StatsBomb Open Data is historical and partial; current-match coverage is not promised.
- **Club crests:** license-verified remote logo mapping; safe fallback when unlicensed.
- **Cloud-first after setup:** requires a Cloudflare account/database and GitHub Actions secrets. No paid plan required within platform limits; not deployed by this package.

Quick local test:

```sh
python -m unittest discover -s tests -v
node --check site/app.js
node --check worker/index.js
```
