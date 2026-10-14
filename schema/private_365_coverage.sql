-- Private 365Scores fixture inventory; no public forecasts or raw provider events.
CREATE TABLE IF NOT EXISTS private_365_fixture_catalog (
  id TEXT PRIMARY KEY NOT NULL,
  competition_id TEXT NOT NULL,
  league TEXT,
  fixture_date TEXT,
  status TEXT NOT NULL,
  payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_private365_fixtures_comp_date
  ON private_365_fixture_catalog(competition_id, fixture_date);
CREATE TABLE IF NOT EXISTS private_365_coverage_days (
  id TEXT PRIMARY KEY NOT NULL,
  competition_id TEXT NOT NULL,
  scan_date TEXT NOT NULL,
  scan_status TEXT NOT NULL,
  payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS private_365_coverage_verified (
  id TEXT PRIMARY KEY NOT NULL,
  payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS private_365_expected_fixtures (
  id TEXT PRIMARY KEY NOT NULL,
  competition_id TEXT NOT NULL,
  fixture_date TEXT NOT NULL,
  home TEXT NOT NULL,
  away TEXT NOT NULL,
  payload TEXT NOT NULL
);
