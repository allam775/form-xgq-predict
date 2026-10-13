# Penniless XGQ — 365Scores zero-cost, private-research feasibility audit
Date: 2026-10-13

## Project rule
**Zero cost.** No paid API, paid plan, commercial data license or fee is proposed. Evaluate 365Scores only for private, not-for-profit research where source access/storage terms allow it. This document neither claims that public visibility grants data-mining rights nor instructs bypassing restrictions.

## Verified public website evidence (human-readable page, NOT verified API dataset)

| Scope | Real match page | Actual team-level evidence displayed | Individual-shot xG preview |
|---|---|---|---|
| UCL 2025/26 | https://www.365scores.com/football/match/uefa-champions-league-572/club-brugge-monaco-471-1169-572 | Club Brugge 26 shots, xG 3.28; Monaco 13 shots, xG 1.55 | Nicolò Tresoldi goal 0.47 xG |
| UCL 2025/26 | https://www.365scores.com/football/match/uefa-champions-league-572/atletico-madrid-eintracht-frankfurt-134-337-572 | Atlético xG 4.53 / 18 shots; Frankfurt 0.59 / 6 | Giacomo Raspadori shot 0.56 xG |
| UCL 2025/26 | https://www.365scores.com/football/match/uefa-champions-league-572/arsenal-club-brugge-104-1169-572 | Shot Map exposed on match page | Noni Madueke goal 0.02 xG |
| Portuguese Liga | https://www.365scores.com/football/match/liga-portugal-73/avs-sporting-cp-890-27176-73 | AVS 11 shots xG 1.66; Sporting 20 shots xG 3.36 | Rafael Nel goal 0.97 xG |
| Turkish Süper Lig | https://www.365scores.com/en-uk/football/match/super-lig-78/kasimpasa-rizespor-960-962-78 | Kasımpaşa 13 shots xG 0.73; Rizespor 14 shots xG 1.42 | Halil Dervişoğlu goal 0.41 xG |

**Interpretation:** The publicly displayed *sample* for these pages confirms shot-level values and match totals are shown to visitors. It does NOT establish that every shot's xG is accessible in a supported API, that all seasons are complete, or that programmatic collection/storage is authorized.

## Existing connector reality
- Code already exists at `engine/provider365.py`.
- `config/365_teams.json` currently contains one configured team (numeric team id 224, league `it.1`); no teams outside 5 major leagues are supported by `KNOWN_LEAGUES` or `private_history` yet.
- `XGQ_365_ACCESS_AUTHORIZED` is opt-in and off by default. `XGQ_365_PUBLICATION_ALLOWED` is off. Private publication protections are not a substitute for source authorization.
- The connector knows only two historically observed endpoint *shapes*, but they are not a published, licensed developer API.
- Existing `parse_game` rejects absent individual shot xG, invalid team attribution, wrong competition, and incomplete final-match identification. It does not guarantee that an upstream `chartEvents` array contains *all* attempted shots. Before a real XGQ import, compare each side's **observed shot event count** with independently shown match shot totals and check `sum(shot_xg)` against provider team xG within rounding tolerance (e.g. 0.005 per rounded value plus 0.02 tolerance). Treat any mismatch as not verified.

## Actual offline verification performed
A self-contained GitHub Actions workflow ran on 2026-10-13:
https://github.com/allam775/form-xgq-predict/actions/runs/38366348098

- **11** contract tests for per-shot xG parser and opt-in flags passed.
- **7** regression tests for 365Scores adapter passed.
- **4** private-D1 history serialization tests passed.
- **22 / 22 tests passed**. No 365Scores API request was made and no live response format was validated.
- No production deployment, cloud shot ingestion, public 365Scores data redistribution, or paid services occurred.

## Terms: what is and isn't confirmed
- The terms at https://www.terms.365scores.com/publisher address **advertising publishers**, and prohibit robot/scraper data gathering of advertising materials for those publishers. They cannot automatically be treated as the complete policy for an independent ordinary non-commercial researcher.
- General site terms at https://www.365scores.com/ar/pages/terms were discoverable, but their complete operative text was not retrievable during this audit, and no documented public research API license was confirmed. Non-commercial intent alone does not establish a data-extraction right.
- Contact for a free, small, private academic/research pilot: **Contact@365scores.com**, published at https://www.365scores.com/en-us/pages/contact . Request explicit allowance for research collection, local storage of derived per-match aggregates, desired limits and prohibited redistribution. Do not enable scraping before permission is resolved.

## Concrete next steps under Penniless rules
1. Request **free research permission**, not a paid subscription, for a small sample (e.g. 10-20 matches from the 2025/26 UCL and Portuguese/Turkish leagues). Ask specifically about shot-event xG and reuse/storage of compact private XGQ summaries.
2. When permitted, conduct **1–3 bounded live match probes** with the owner's known match IDs (no enumeration, authentication bypass, rotating IPs, spoofed browser headers, or public publishing). Inspect counts, xG values and event completeness privately; stop at 401/403/429.
3. In a separate experimental branch/path, add league IDs/aliases for authorized competitions and test their accurate team names, dates, scores, and leagues before scaling; do not modify five-league production forecast.
4. Compute exact XGQ only after every shot has a verified per-event xG and counts reconcile with the published totals. Historical predictions must only use snapshots from strictly earlier match dates.
5. Run matched 189-game historical UCL audit + separate frozen prospective ledger; publish only **model-generated aggregate performance** where authorized.
6. If authorization or complete per-shot values are not available, retain non-network, manually reviewed public-reference analysis or pivot to genuinely open-data providers. **No cost, no invented XGQ.**

## What would count as successful proof
- A documented source and permitted research acquisition path.
- Every accepted match has genuine xG for *all shots of both teams*, matching verified counts and consistent xG totals.
- No missing matches silently treated as zero; explicit coverage % by country, league, season, team and match.
- At least 350 matched, chronological, held-out football predictions before claiming >52% out-of-sample 1X2 accuracy.

**Current verdict:** VISUAL SHOT-xG COVERAGE CONFIRMED / OFFLINE PARSER PASSED / LIVE PROGRAMMATIC DATA RIGHTS, COMPLETENESS AND INGESTION NOT CONFIRMED.
