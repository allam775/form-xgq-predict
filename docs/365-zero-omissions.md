# 365Scores competition-wide coverage: no silent omissions

The private FORM/XGQ pipeline now distinguishes **fixture inventory** from **verified per-shot XGQ**. A match lacking xG must remain in the fixture ledger; it must never enter the model with fabricated shot values.

## Identified causes

- Legacy source discovery was team-centric, using games/results/ with competitors=teamId. This misses other teams and can ignore the team filter.
- Historical XGQ collector had per-run limits (24 teams, 48 games); the original Analyzer also stopped at matchLimit. Neither is a complete season index.
- In earlier testing 20 of 28 inspected matches were acceptable, while 8 still had shot/aggregate disagreement or ambiguous shot inclusion.

## New approach

1. Scan **every calendar date**, with games/allscores/, sports=1, startDate=DD/MM/YYYY, endDate=DD/MM/YYYY, onlyMajorGames=false, withTop=false. Match exact verified competition IDs.
2. Persist game IDs and fixture metadata in a private ledger, including failed dates and unknown competition identities. Never silently truncate a day with more than 120 matches.
3. Fetch game/ per match, require genuine shot-level xG, and independently reconcile both sides against game/stats/ total shots and expected goals.
4. Only reconciled games are exported to the existing private XGQ shot history. Incomplete/mismatched games remain pending, not dropped.
5. Compare the final ID set with independently sourced official fixtures; a complete date sweep alone is not proof that the provider exposed every game.

## Private backfill command

Run only with permission to use the provider data and with a private Access-protected destination. The flags do not themselves establish permissions.

```bash
export XGQ_365_ACCESS_AUTHORIZED=1
export XGQ_365_PRIVATE_ONLY=1
python -m engine.coverage365 --competition-id 572 --league uefa.cl \
  --start 2025-07-01 --end 2026-06-30 \
  --output data/private_365_catalog_cl2526.json \
  --max-days 14 --max-details 48 \
  --history-output data/private_365_history.json
```

Repeat the same command to resume remaining dates, preserving the private ledger after each date. To compare an independently verified array of 365Scores game IDs, add --expected-ids /private/ids.json. Restore the existing private D1 cache before a hosted run; use the existing private D1 export after it. Do not commit private history.

## Quality and completeness

- not_checked: fixture indexed; per-shot data not yet inspected.
- pending_verification: incomplete/mismatched real shots or statistics. Not eligible for model inputs.
- verified_xg: individual shot arrays and aggregate expected goals/total shots agree. Eligible for private XGQ history.
- unresolved:*: fixture found without a usable game ID.
- unassigned_games: game found without a verified competition ID.
- failed_days: source inaccessible, incomplete, paginated, or malformed. Retry but never misreport as an empty date.

Reconciliation checks use a strict 0.06 xG tolerance for known rounding. Tolerance cannot be expanded solely to raise nominal coverage. 401, 403 and 429 must not be bypassed.

**Important:** This change prevents silent omissions and creates an accountable backfill mechanism. A claim of 100% of the season requires a successful live scan and an independent fixture register. The eight previously disputed matches are not automatically resolved by this patch.

## Cloudflare persistence and automation (2026-10-14)

The existing private D1 database named **xgq-predictions** has been extended with the tables `private_365_fixture_catalog`, `private_365_coverage_days` and `private_365_coverage_verified`. All three tables are for private staging only. The initial source-backed research manifest has 28 distinct game IDs (five verified competition identities), of which 20 have separately verified shot-level evidence and eight still lack a satisfactory verification. The verified 20 are **research-only; `training_release=false` is retained**. There are no records in the production `private_shot_history` table. No publication permission is inferred from the private study records.

A separate workflow `.github/workflows/365-private-coverage.yml` restores per-competition D1 data, scans up to fourteen previously unscanned dates (never future dates), checks at most 24 completed match details, and writes an idempotent D1 checkpoint. The scheduled trigger is daily at 03:25 UTC **only after merging the branch**, and runs solely when these requirements are explicitly configured:

- GitHub secrets `CLOUDFLARE_ACCOUNT_ID` and `CLOUDFLARE_API_TOKEN` (rights restricted to this database).
- The workflow is explicitly locked to the owner repository and the confirmed private research/D1 workflow. It sets `XGQ_365_ACCESS_AUTHORIZED=1` and `XGQ_365_PRIVATE_ONLY=1` for this specific collector. Revoke this gate if source rights are withdrawn; it is not permission to publish private source records.

The configured 2026/27 source-verified competitions are **7** Premier League, **11** La Liga, **17** Serie A, **73** Portugal Primeira Liga and **572** UEFA Champions League. To add more leagues, first validate their competition IDs with reliable source evidence and extend the matrix. Never enumerate unknown identifiers. The scanner neither changes public site predictions nor overrides `training_release`.

The D1 checkpoint may be saved only if the script reaches the SQL export step; the program also persists a local atomic JSON checkpoint per date. If GitHub stops a job before the SQL export, a subset of that batch may be re-requested on the next run without producing duplicate D1 records. The script deliberately does not retry 401/403/429 with evasive tactics.

**Unresolved requirement:** independently verify completeness of each official competition schedule, including the actual game IDs and official date range. The source may omit games, change its response shape, or fail outright. No code can assert 100% historical availability from source data alone.

## Live verification checkpoint

On 14 October 2026 a one-time GitHub-hosted ordinary HTTP request to 365Scores returned 259 football games for 13 October 2026, including nine competition ID 572 Champions League games. The nine game IDs were inserted/reconciled into private D1, and all nine home/away pairings matched UEFA's official 2026/27 matchday 2 fixture list. Previously only four of those nine appeared in the research sample. This proves one-day fixture discovery, not full-season or nine-match shot-level XGQ completeness. The one-time live probe workflow has been removed after success.

Source: UEFA official 2026/27 Champions League fixtures, published 9 October 2026: https://www.uefa.com/uefachampionsleague/news/02a8-2174c9e9019d-f909a77bd77a-1000--2026-27-champions-league-all-the-league-phase-fixtures-a/

## Live game/stats layout correction

An authorized schema-only inspection of the real 365Scores `game/stats/` response found `statistics[]` rows shaped like `{name, competitorId, value}`: home and away are represented by *separate records*, not a combined two-value row. The updated `aggregate_totals` parser now attributes each metric against the actual match's home/away competitor IDs, rejects irrelevant competitors, keeps xG separate from xGOT, and retains legacy paired formats. The result of rechecking the 13 October 2026 UEFA batch was **two newly verified per-shot-xG matches**, taking the private verified staging archive from 20 to 22. The remaining disputed fixtures stay in the inventory, with real discrepancies recorded rather than invented xG.

The schema-only debug probe was removed from the repository after use; it does not run on the main branch.
