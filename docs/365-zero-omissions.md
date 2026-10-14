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
python -m engine.coverage365 --competition-id 572 --league eu.cl \
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
