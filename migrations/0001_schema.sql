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
