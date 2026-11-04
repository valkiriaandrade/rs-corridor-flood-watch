-- Validation queries. Run: sqlite3 data/processed/forecast/forecasts.sqlite < sql/validation.sql
.headers on
.mode column

-- 1) How many forecasts can already be verified, by model and lead
SELECT model, lead_days, COUNT(*) AS n FROM verification GROUP BY model, lead_days ORDER BY model, lead_days;

-- 2) Level agreement: Watch-or-above forecast vs Watch-or-above computed with observed rainfall
SELECT model, lead_days,
       SUM(fc_level >= 1 AND obs_level >= 1) AS hits,
       SUM(fc_level >= 1 AND obs_level = 0)  AS false_alarms,
       SUM(fc_level = 0  AND obs_level >= 1) AS misses,
       SUM(fc_level = 0  AND obs_level = 0)  AS correct_normal,
       ROUND(1.0 * SUM(fc_level >= 1 AND obs_level >= 1) / NULLIF(SUM(obs_level >= 1), 0), 3) AS POD,
       ROUND(1.0 * SUM(fc_level >= 1 AND obs_level = 0) / NULLIF(SUM(fc_level >= 1), 0), 3) AS FAR
FROM verification WHERE fc_level >= 0 AND obs_level >= 0
GROUP BY model, lead_days ORDER BY model, lead_days;

-- 2b) Same for the experimental API (rows from runs made after the API was added)
SELECT model, lead_days,
       SUM(fc_level_api >= 1 AND obs_level_api >= 1) AS hits,
       SUM(fc_level_api >= 1 AND obs_level_api = 0)  AS false_alarms,
       SUM(fc_level_api = 0  AND obs_level_api >= 1) AS misses,
       ROUND(1.0 * SUM(fc_level_api >= 1 AND obs_level_api >= 1) / NULLIF(SUM(obs_level_api >= 1), 0), 3) AS POD,
       ROUND(1.0 * SUM(fc_level_api >= 1 AND obs_level_api = 0) / NULLIF(SUM(fc_level_api >= 1), 0), 3) AS FAR
FROM verification WHERE fc_level_api >= 0 AND obs_level_api >= 0
GROUP BY model, lead_days ORDER BY model, lead_days;

-- 3) Daily rainfall of the day itself (rain_mm): bias and mean absolute error of the forecast, by model and lead
--    (runs archived before rain_mm existed are skipped; P1 is the max over d-1 and d, not the day's rainfall)
SELECT model, lead_days, COUNT(*) AS n,
       ROUND(SUM(fc_rain) / NULLIF(SUM(obs_rain), 0), 2) AS bias_ratio,
       ROUND(AVG(ABS(fc_rain - obs_rain)), 2)            AS mae_mm,
       SUM(fc_rain >= 20 AND obs_rain >= 20)              AS heavy_hits,
       SUM(obs_rain >= 20)                                AS heavy_observed
FROM verification WHERE fc_rain IS NOT NULL AND obs_rain IS NOT NULL
GROUP BY model, lead_days ORDER BY model, lead_days;

-- 4) Against official records (after `python -m floodwatch.forecast_db events <atlas.csv>`)
SELECT model, lead_days, SUM(official_record) AS records,
       SUM(official_record AND fc_level >= 1) AS records_at_watch_or_above,
       SUM(official_record AND fc_level_api >= 1) AS records_at_watch_or_above_api
FROM verification GROUP BY model, lead_days ORDER BY model, lead_days;

-- 5) Corridor levels issued in each run (what the page showed)
SELECT r.created_utc, c.date, c.model, c.br, c.lead_days, c.level, c.n_att, c.level_api, c.n_att_api, c.n
FROM corridor c JOIN runs r USING (run_id) WHERE c.source = 'previsão' ORDER BY r.created_utc, c.date, c.br, c.model;
