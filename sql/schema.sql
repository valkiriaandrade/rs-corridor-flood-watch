-- RS Corridor Flood Watch: archive of forecast runs for later verification (SQLite).
-- level: -1 no data, 0 Normal, 1 Atenção/Watch, 2 Alerta/Warning for the EDI rule; level_api: same for the API rule.
-- Rule = thresholds + frozen 3-day trigger (floodwatch.rules), recorded per run in `runs`. date = 12-12 UTC day (label = end day).
-- lead_days = date - observed_cutoff of the run (<= 0: observed rows, >= 1: forecast).

CREATE TABLE IF NOT EXISTS runs (
    run_id          TEXT PRIMARY KEY,   -- folder name, creation time UTC
    created_utc     TEXT,
    ecmwf_run       TEXT,
    gfs_run         TEXT,
    observed_cutoff TEXT,               -- last day with MERGE observed rainfall
    predictor       TEXT,
    thr_attention   REAL,
    thr_alert       REAL,
    antecedent_json TEXT,               -- MERGE product of the last 30 days (final/late/early)
    thr_api_attention REAL,
    thr_api_alert     REAL,
    trigger_p3_edi    REAL,             -- frozen 3-day trigger (mm) of the run; NULL for runs made before it existed
    trigger_p3_api    REAL
);

CREATE TABLE IF NOT EXISTS municipal (
    run_id     TEXT REFERENCES runs(run_id),
    date       TEXT,
    codarea    TEXT,                    -- IBGE municipality code
    nome       TEXT,
    corridors  TEXT,                    -- e.g. '116/386'
    model      TEXT,                    -- ECMWF | GFS
    source     TEXT,                    -- 'observado' | 'previsão'
    lead_days  INTEGER,
    P1 REAL, P3 REAL, P7 REAL, P30 REAL, PE REAL, EDI REAL,
    level      INTEGER,
    API REAL,
    level_api  INTEGER,
    rain_mm    REAL,                    -- daily basin rainfall of the day (P1..P30 take the max over d-1 and d)
    PRIMARY KEY (run_id, date, codarea, model)
);

CREATE TABLE IF NOT EXISTS corridor (
    run_id    TEXT REFERENCES runs(run_id),
    date      TEXT,
    model     TEXT,
    br        TEXT,
    source    TEXT,
    lead_days INTEGER,
    level     INTEGER,                  -- display rule: level present in >= 20% of the corridor municipalities
    n_att     INTEGER,
    n_alert   INTEGER,
    n         INTEGER,
    level_api   INTEGER,
    n_att_api   INTEGER,
    n_alert_api INTEGER,
    PRIMARY KEY (run_id, date, model, br)
);

CREATE TABLE IF NOT EXISTS events (       -- official flood records (Atlas/S2iD), loaded when available
    protocol TEXT PRIMARY KEY,
    codarea  TEXT,
    date     TEXT,
    cobrade  TEXT
);

CREATE INDEX IF NOT EXISTS ix_mun_date ON municipal (date, codarea);
CREATE INDEX IF NOT EXISTS ix_events ON events (codarea, date);

-- Observed truth per municipality-day: the most recent run that holds the day as observed
-- (later runs carry more mature MERGE products: early -> late -> final).
DROP VIEW IF EXISTS verification;
DROP VIEW IF EXISTS observed;
CREATE VIEW observed AS
SELECT m.date, m.codarea, m.nome, m.corridors, m.rain_mm, m.P1, m.P3, m.EDI, m.level, m.API, m.level_api, m.run_id AS observed_in_run
FROM municipal m
WHERE m.source = 'observado' AND m.model = 'ECMWF'      -- observed rows are identical for both models
  AND m.run_id = (SELECT MAX(m2.run_id) FROM municipal m2
                  WHERE m2.source = 'observado' AND m2.model = 'ECMWF' AND m2.date = m.date AND m2.codarea = m.codarea);

-- Each forecast paired with what was later observed (and with official records, when loaded).
CREATE VIEW verification AS
SELECT f.run_id, f.date, f.lead_days, f.model, f.codarea, f.nome, f.corridors,
       f.rain_mm AS fc_rain, o.rain_mm AS obs_rain, f.P1 AS fc_P1, o.P1 AS obs_P1, f.P3 AS fc_P3, o.P3 AS obs_P3, f.EDI AS fc_EDI, o.EDI AS obs_EDI,
       f.level AS fc_level, o.level AS obs_level,
       f.API AS fc_API, o.API AS obs_API, f.level_api AS fc_level_api, o.level_api AS obs_level_api,
       EXISTS (SELECT 1 FROM events e WHERE e.codarea = f.codarea
               AND e.date BETWEEN date(f.date, '-1 day') AND f.date) AS official_record
FROM municipal f
JOIN observed o ON o.date = f.date AND o.codarea = f.codarea
WHERE f.source = 'previsão'
  -- several refreshes may reuse the same model runs: keep only the last refresh of each issuance
  AND f.run_id IN (SELECT MAX(run_id) FROM runs GROUP BY ecmwf_run, gfs_run, observed_cutoff);
