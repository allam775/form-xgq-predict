-- Execute once or repeatedly; release publication is version-pointer based.
CREATE TABLE IF NOT EXISTS forecasts (
 generation TEXT NOT NULL,
 id TEXT NOT NULL,
 fixture_date TEXT NOT NULL,
 league TEXT NOT NULL,
 home TEXT NOT NULL,
 away TEXT NOT NULL,
 payload TEXT NOT NULL,
 PRIMARY KEY(generation, id)
);
CREATE INDEX IF NOT EXISTS idx_forecasts_gen_date ON forecasts(generation, fixture_date, league);
CREATE TABLE IF NOT EXISTS unavailable (
 generation TEXT NOT NULL,
 id TEXT NOT NULL,
 fixture_date TEXT NOT NULL,
 league TEXT NOT NULL,
 home TEXT NOT NULL,
 away TEXT NOT NULL,
 reason TEXT NOT NULL,
 PRIMARY KEY(generation, id)
);
CREATE INDEX IF NOT EXISTS idx_unavailable_gen_date ON unavailable(generation, fixture_date);
CREATE TABLE IF NOT EXISTS release_metadata (
 generation TEXT NOT NULL, k TEXT NOT NULL, v TEXT NOT NULL,
 PRIMARY KEY(generation,k)
);
CREATE TABLE IF NOT EXISTS metadata(k TEXT PRIMARY KEY,v TEXT NOT NULL);

-- Owner-only persistence. No public Worker route selects from this table.
CREATE TABLE IF NOT EXISTS private_shot_history (
 id TEXT PRIMARY KEY, payload TEXT NOT NULL
);

-- Isolated Understat private history and derived team-form snapshots.
CREATE TABLE IF NOT EXISTS private_understat_history (
 id TEXT PRIMARY KEY, payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS private_understat_form (
 id TEXT PRIMARY KEY, payload TEXT NOT NULL
);

-- Immutable daily pre-match model forecasts and independently verified grading.
CREATE TABLE IF NOT EXISTS private_daily_forecasts (
 id TEXT PRIMARY KEY, payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_private_daily_forecasts_date
 ON private_daily_forecasts(json_extract(payload,'$.date'));
CREATE TABLE IF NOT EXISTS private_daily_grades (
 id TEXT PRIMARY KEY, payload TEXT NOT NULL
);
