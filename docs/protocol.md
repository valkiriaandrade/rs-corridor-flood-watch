# Study protocol — flood-potential thresholds for the BR-116 / BR-386 / BR-290 corridors (Rio Grande do Sul, Brazil)

This document is the single, consolidated protocol of the study. Every rule below was fixed **before** the
performance metrics it governs were computed, except where the [decision log](#11-decision-log) says otherwise.
The log records, with dates, every decision taken after seeing results, so that a reader can judge each number by how
it was obtained.

---

## 1. Question

Above which value of a flood-potential index do the municipalities crossed by the BR-116, BR-386 and BR-290 highways
start to show official flood records at an elevated frequency, and do those thresholds keep working in years that were
not used to set them? Two indices are evaluated, each against plain accumulated rainfall (1, 3, 7 and 30 days), to find
out whether they add anything:

- **EDI** — Effective Drought Index (Byun & Wilhite, 1999), built on effective precipitation (PE).
- **API** — Antecedent Precipitation Index (Kohler & Linsley, 1951).

## 2. Data

| Item | Source | Rule |
|---|---|---|
| Daily rainfall | MERGE/CPTEC, GPM-IMERG **V07B final**, 0.1°, 1998-01-02 → 2024-12-31 | Day D = 12 UTC of D−1 → 12 UTC of D. A file that is missing, unreadable or not V07B is a gap (NaN), never zero. |
| Rainfall 2025 → today | MERGE IMERG *late* / *early* | Used only for the 2025 test and the forecast antecedent; the product version is recorded per day. |
| Flood events | Atlas Digital de Desastres no Brasil (MIDR/CEPED-UFSC), DB v1.1 (2026-08-06) | COBRADE 12100 (riverine flood), 12200 (flash flood), 12300 (urban flooding), 13214 (heavy rain), grouped; reported event date (`Data_Evento`) 2013-01-01 → 2024-12-31. Before 2013 the date is the registration date, so earlier years are excluded. |
| Corridors | DNIT SNV 202404A | Planned (`PLA`) segments excluded. |
| Municipalities | IBGE 2022 mesh | A municipality belongs to a corridor with ≥ 0.5 km of that BR inside it → **86 municipalities**. |
| Hydrography | ANA, BHO 2017 5k, ottobacias level 6 | Upstream basin of each municipality (§3). |
| River stages | ANA HidroWeb (`HidroSerieHistorica`) | Extra validation (§8.2) and river-state predictor (§9.2). |
| Forecast rainfall | ECMWF IFS and NOAA GFS via Open-Meteo | Forecast application only (§10). |

## 3. Spatial unit: the upstream basin

Rainfall for each municipality is the area-weighted mean of MERGE cells over its **upstream basin**:

1. *Seeds*: level-6 ottobacias with ≥ 5 km² of overlap with the municipality (the cut removes boundary slivers).
2. *Upstream set*: every ottobacia b upstream of a seed a, by the ANA/Pfafstetter rule
   `cobacia(b) ≥ cobacia(a)` and `cobacia(b)` starts with `cocursodag(a)`, where `cocursodag` is the code up to its
   last even digit (the watercourse). A code without an even digit lies on the coast (coastal or lagoon interbasin,
   e.g. Lagoa dos Patos): the coastline is not a river, so nothing is upstream of it but itself.
3. *Coverage*: a day is valid only if valid cells cover ≥ 99 % of the basin area.

The municipality-only rainfall (same coverage rule) is kept as a comparison (§9.1).

## 4. Indices

Both indices come from `climate-indices` 3.0.0 (`flood` module) with the library defaults.

- **PE / EDI**: 365-day window on the all-leap calendar used by the library (the artificial 29 Feb of non-leap years is
  the mean of 28 Feb and 1 Mar, before PE; returned dates are Gregorian). Calibration fixed to **1999–2012**, before
  the whole evaluation period (no leakage); the first year is warm-up.
- **API**: `API(d) = k · API(d−1) + P(d)`, mm, real calendar, zero seed; a missing day makes the index missing from then
  on. The library requires k and has no default; **k = 0.90** (within the 0.85–0.90 range cited in its documentation)
  was fixed before any API result; 0.85 and 0.95 were run as sensitivity only.

## 5. Samples

- **Positive**: the onset day of a flood record. Records of the same municipality chained with gaps ≤ 7 days (each
  record compared with the previous one) form one event, dated by its first record.
- **Negative**: a municipality-day of 2013–2024 more than 15 days from any record of the four COBRADE codes in that
  municipality.
- **Predictor value on day d**: the maximum of d−1 and d (absorbs the 12–12 UTC convention and ±1 day in the reported
  date). No rainfall after d is ever used.
- **Episode**: events of any corridor municipality chained with gaps ≤ 5 days; the resampling block of positives.
  Negatives are blocked by year-month.

## 6. Predictors

P1, P3, P7, P30 (mm), PE (mm), EDI, API, the calendar month (seasonal baseline) and the combined rule EDI ≥ a **and**
P3 ≥ b.

## 7. Threshold selection and validation

1. **Watch threshold**: the value maximising TSS (Peirce skill score = POD − POFD) on the development data, over a grid
   of quantiles 0.50–0.9995.
2. **Warning threshold**: the lowest value with POFD ≤ 2 % on the development negatives.
3. **Primary validation**: leave-one-year-out (2013…2024); thresholds re-chosen in every fold; contingency table pooled
   out of sample.
4. **Secondary validation**: development 2013–2020 → test 2021–2024; both also without the April–May 2024 episode
   (the whole episode and the negatives within its dates removed).
5. **Uncertainty**: block bootstrap (positives by episode, negatives by year-month), 2,000 replicates, seed 20261103,
   95 % percentile intervals for AUC, POD, POFD, TSS and thresholds.
6. **Comparisons**: paired bootstrap of the out-of-sample TSS difference.

**Decision rules (fixed in advance)**

- A predictor "adds skill / improves" only if the 95 % CI of the paired TSS difference lies entirely above 0.
- A threshold is "validated" only with ≥ 30 development and ≥ 10 test episodes and an out-of-sample TSS whose 95 % CI
  has a lower bound above 0.2.
- Results are published whatever they are.

## 8. Independent tests (frozen thresholds, no re-tuning)

### 8.1 Year 2025
Thresholds refit on 2013–2024 are frozen and applied to 2025, a year no stage of the study used. Same event, episode
and negative rules; MERGE late/early rainfall. "Confirmed in 2025" only if the lower 95 % CI bound of TSS > 0.2.

### 8.2 Gauged river floods (ANA)
- Gauges with a stage board inside a corridor municipality, drainage area ≥ 100 km², not regulated (no hydropower,
  dam or reservoir in the name), started before 2017; daily stage 2013–2024 = maximum of the day's readings, consistent
  data preferred over raw data month by month; kept with ≥ 70 % valid days and ≥ 8 years with ≥ 300 valid days.
- Flood day: stage ≥ the gauge's median annual maximum (≈ 2-year flood). Events, episodes and negatives follow §5
  (negatives also need a valid stage).
- The thresholds calibrated on the S2iD records are applied unchanged.
- The dashboard rule of §10 (basin index OR P3 ≥ frozen trigger) is also scored against the river floods with all
  thresholds frozen; it was added after §9.3 and is descriptive (nothing is fitted on river data).

### 8.3 Documented road impacts
Impacts on BR-116/386/290 (DNIT/PRF bulletins and Civil Defence, 2016–2024) never enter calibration; the level on
D−2…D of each impact is reported as a qualitative check.

## 9. Supplementary analyses (each registered before it was run)

### 9.1 Upstream basin vs municipality
EDI and API from basin rainfall vs from municipality-only rainfall: same samples, procedure and tests; paired
difference on the leave-one-year-out TSS (primary) and on the secondary designs, the 2025 test and the river floods.

### 9.2 River state as an extra predictor
In municipalities with a valid gauge, "river in flood on D−1" (any gauge ≥ its flood level the day before the record)
is added with OR to the frozen index rule; no new fitting. Improvement only if the paired CI lies above 0.

### 9.3 Second, short-term trigger
Rule: Watch if index ≥ its Watch threshold **or** P3 ≥ b. In each fold the index threshold is the one of the index
alone and b (grid of P3 quantiles 0.90–0.9995 of the training years) maximises the TSS of the OR rule on the training
years. Evaluated with §7; the final b is refit on 2013–2024 and frozen. Because the hypothesis came from the 2025 test,
2025 is descriptive only; confirmation is prospective (records from 2026 onwards, §10).

### 9.4 Forecast rainfall verification (ECMWF vs GFS)
Archived Open-Meteo runs (previous-runs API), ECMWF IFS 0.25° open data and GFS, 2024-03-01 → last MERGE day; 34
boxes of 0.5° over the corridor municipalities; 12–12 UTC days; leads D+1 to D+5. Primary metric: ETS for ≥ 20 mm/day,
mean of D+1..D+3; paired block bootstrap by month (2,000 replicates, seed 20261104). A model is "more accurate" only if
the CI of the difference excludes zero.

### 9.5 Hindcast of the forecast levels
Question: how much of the observed-rainfall skill (§7) survives when the rule runs on forecast rainfall, by lead.
- Rainfall: Open-Meteo previous-runs API (as §9.4), hourly `precipitation_previous_day{L}`, ECMWF IFS 0.25°
  (`ecmwf_ifs025`) and GFS (`gfs_global`), at the operational 0.25° forecast points (`upstream.forecast_grid`), basin
  means with the operational weights, 12–12 UTC days. Lead L of day D = the value of `previous_day{L}` over D's window.
- Chain: for each issuance day X (2024-03-01 → last day with final or late MERGE), observed basin rainfall through
  X−1 followed by forecast rainfall for X … X+5 (lead of day D = D − X + 1, D+1 … D+5), indices and levels computed by
  the operational code (`forecast.index_table`, `rules.classify`, frozen rules). Nothing is fitted.
- Outcomes: (a) official records (Atlas 2024 + S2iD 2025, §5 events and controls restricted to the period); (b) the
  same rule on observed rainfall (§10 prospective definition).
- Primary: TSS at Watch-or-above against official records, mean of leads 1–3, and its paired difference to the
  observed-rainfall TSS on the same samples (skill loss); block bootstrap as §7 (episodes / year-months, 2,000
  replicates, seed 20261124). Reported per model and per lead 1–5, for 2024 and 2025 separately.
- 2024 years were used to fit the frozen thresholds: their absolute scores are in-sample, only the paired skill loss
  is interpreted for 2024. 2025 is the independent year.

### 9.6 Bias correction of forecast rainfall
Empirical quantile mapping of daily basin forecast rainfall to MERGE, one map per model and lead (all basins pooled),
99 percentiles, linear interpolation, constant correction beyond the fitted range. Fitted on 2024-03-01 → 2024-12-31,
tested on 2025 with the §9.5 chain. Primary: paired TSS difference (corrected − raw) against official records, leads
1–3, 2025. Adopted in operation only if the whole 95 % CI lies above 0; secondary: ETS ≥ 20 mm/day and 3-day rainfall
ratio on flood-record days (§9.4 definitions).

### 9.7 Ensemble probabilities (prospective)
No historical ensemble archive exists (Open-Meteo keeps about three months). From the registration date the daily
workflow archives the 12 UTC ECMWF ENS (51 members) and GEFS (31 members) basin rainfall; the frozen rule is applied to
every member, giving P(Watch or above) and P(Warning) per municipality and lead. The available past months are
back-filled once. Verification: Brier score and Brier skill score against the deterministic forecast of the same model
(as 0/1), reliability diagram (10 bins), outcome = the rule on observed rainfall and, separately, official records.
First evaluation after one full year of archive; nothing is fitted before it.

> **Correction, 2026-11-27 (the registered text above is kept as written).** No back-fill took place: Open-Meteo
> serves no past ensemble runs at all, only the latest one (decision log 2026-11-24), so "the available past months are
> back-filled once" could not be done. The archive starts with the daily run of 25 November 2026 (ensemble
> initialisation 24 November 18 UTC). The run archived is the latest available at workflow time, not necessarily
> 12 UTC (its initialisation is stored). The one-year evaluation therefore starts from 25 November 2026.

> **Dashboard display and continuous-monitoring rule, 2026-11-27 (not part of the evaluation above).** The ensemble
> forecast level of a municipality-day is the highest level reached with probability ≥ 0.5, i.e. by at least half of
> the members (`ENSEMBLE_P` in `floodwatch/verification_summary.py`): P(Watch or above) = `p_watch` and P(Warning) =
> `p_warning` for the EDI rule, `p_watch_api` / `p_warning_api` for the API rule. 0.5 is fixed, not fitted, and will not
> be tuned on results. With that level, the ensembles are verified exactly like the deterministic forecasts (the same
> verified days, the same observed level = the frozen rule on MERGE rainfall, the same `lead_days`, each day scored with
> the latest forecast issued before it); ensemble rain = member mean (`rain_mean`). The dashboard also shows the Brier
> score of P(Watch) and P(Warning). All of this is continuous monitoring, like the deterministic verification; the
> registered evaluation (Brier skill score, reliability, after one full year) is unchanged.

> **Grid check, 2026-11-28 (decision log 2026-11-28; criterion stated before computing).** The ensembles use the 0.5°
> forecast points (180), the deterministic forecasts the 0.25° points (632). Same ECMWF IFS and GFS runs (Open-Meteo
> previous-runs API) on both grids, 4–27 Nov 2026, 86 municipalities, D+1–D+3 (6,192 municipality-day-leads per model;
> levels for the 22 issuances 4–25 Nov, the last with all three days in the period: 5,676). 0.5° minus 0.25° basin rain:
> ECMWF +0.27 mm (+3.3 %), mean absolute difference 1.1 mm, 95th percentile 5.0 mm, r = 0.98; GFS +0.17 mm (+2.7 %),
> 0.9 mm, 3.7 mm, r = 0.98. Same level on both grids: API 97.9 % (ECMWF) and 98.4 % (GFS), EDI 98.4 % and 98.8 %.
> **The criterion is met for all four (agreement ≥ 90 %, |relative bias| ≤ 10 %): the 0.5° grid is acceptable for the
> ensemble display.** Descriptive: on days at Watch or above on either grid the agreement is 91–95 %; every
> disagreement is one level apart (never Normal vs Warning); the smallest basins (275–3,063 km²) have the largest
> rain differences (95th percentile 7.3 mm ECMWF, 5.7 mm GFS, against 2.1–2.2 mm for the largest), but their level
> agreement (97.7–98.4 %) is close to the others. One month of data; the grid is not the only difference between
> ensemble and deterministic levels (member spread, the P ≥ 0.5 rule). `data/processed/study/grid_check.json`.

### 9.8 GloFAS benchmark
GloFAS v4 reanalysis daily river discharge (Open-Meteo flood API). For each municipality, the GloFAS cell (0.05°)
inside the municipality with the largest mean discharge 1999–2012 (its main river). Predictor: discharge ÷ the
cell's median annual maximum 1999–2012 (the EDI calibration years), max of d−1 and d. Threshold fitted exactly as §7
(LOYO, TSS-max), on the same samples. Primary: paired TSS difference API dashboard rule − GloFAS rule (LOYO);
secondary: holdout, 2025 test, gauged river floods (§8.2). GloFAS reanalysis is forced by reanalysed weather, so it is
compared with the observed-rainfall study, not with the forecast levels.

### 9.9 Independent ground truth (descriptive, frozen rules)
- PRF accident records (datatran, 2013–2025) on BR-116, BR-386 and BR-290 in RS whose cause is water on the road. The
  cause categories are fixed by reading the category list only, before any link to rainfall or levels, and recorded
  in the decision log. Unit: municipality-day from the record's municipality. Reported: share of such days at Watch or
  above on D, rate ratio vs all days, by index. Water on the road also follows ordinary heavy rain, so this measures
  road impact, not flooding.
- Corridor display rule (§10, 20 %): corridor-days with ≥ 1 such accident vs corridor level; the first test of that
  rule.
- Copernicus EMS rapid mapping of the April–May 2024 floods: municipalities with mapped flood extent vs the level on
  the image dates.
- Cemaden occurrences: no open data was found; requested through the access-to-information law, used if received.

### 9.10 Statistical additions (no decision changes)
- SEDI (Ferro & Stephenson, 2011) reported next to every out-of-sample TSS of §7, §8 and §9 (same predictions and
  bootstrap).
- Relative economic value V(C/L) (Richardson, 2000) of the frozen dashboard rules, LOYO predictions, C/L 0.01–0.99.
- Minimum detectable paired difference at 80 % power ≈ 2.8 × bootstrap SD of the paired TSS difference, for each
  comparison reported as "not proven".

### 9.11 Soil moisture as antecedent state
ERA5-Land soil moisture 0–100 cm (Open-Meteo archive, daily mean), basin means with the MERGE cell weights (nearest
ERA5-Land point), standardised per calendar day on 1999–2012. (i) SM anomaly alone as an index, §7 procedure, paired
vs API; (ii) rule "API dashboard rule OR (SM anomaly ≥ s AND P1 ≥ q)", s and q fitted in each training fold on grids of
their training quantiles (0.80–0.995). Improvement only if the paired LOYO CI lies above 0. The idea came from the June
2025 case, so 2025 is descriptive and confirmation is prospective (records from 2026, §10).

### 9.12 Reproducibility
Versioned releases archived on Zenodo (DOI) with the derived study tables; `CITATION.cff`; a preprint once §§9.5–9.11
are reported, including negative results.

## 10. Operational rule and forecast application

For each index (`floodwatch/rules.py`):

| Level | Condition |
|---|---|
| Warning | index ≥ Warning threshold |
| Watch | index ≥ Watch threshold, **or** P3 (3-day basin rainfall) ≥ frozen trigger b |
| Normal | otherwise |
| No data | index missing (never shown as Normal) |

- Corridor level (display rule, not validated): the highest level present in ≥ 20 % of the corridor's municipalities
  on that day.
- Risk multiplier per level: event rate at that level ÷ rate over all municipality-days 2013–2024, with the final rule
  (in-sample by construction; the out-of-sample metrics are those of §7).
- Forecast: observed MERGE rainfall up to the last published day, then ECMWF or GFS deterministic 12 UTC runs on a
  0.25° grid covering every upstream basin (each 0.1° MERGE cell takes the nearest forecast point), summed over the same
  12–12 UTC window. The rules were validated with observed rainfall; in the forecast they inherit the weather model's
  error. Every forecast run is archived (SQLite) with the rule it used, so that forecast levels can be verified
  prospectively against observed rainfall and official records.
- The predictors take the maximum over days d−1 and d (§5), so the archive also stores `rain_mm`, the basin rainfall of
  the day itself; the daily-rainfall verification and the briefing's day-by-day table use it.

## 11. Decision log

| Date | Decision | Taken |
|---|---|---|
| 2026-11-03 | Protocol registered (§§1–8.1 for the EDI). | before any metric |
| 2026-11-03 | Code review corrections: planned SNV segments out, ≥ 0.5 km rule (89 → 86 municipalities); event chaining on the previous record; whole-episode sensitivity; 2,000 replicates for every CI; risk multiplier over all municipality-days; missing index shown as "no data". The study was re-run and only the re-run numbers are published. | after a first run |
| 2026-11-03 | Corridor display rule (20 %). | display only, not validated |
| 2026-11-04 | 2025 independent test registered (§8.1). | before running |
| 2026-11-04 | Forecast-rainfall verification registered (§9.4); model list reduced to ECMWF and GFS before evaluation; the archived GFS D+5 series (≈ half the rain of D+1..D+4 in every box) is reported but not interpreted. | before results |
| 2026-11-04 | **API added as a second index**, evaluated with exactly the EDI procedure. | after the EDI results and an exploratory test of FI, API and FI events (not deployed) |
| 2026-11-04 | Upstream-basin (§9.1) and river-level (§8.2) analyses registered. The coastal-code condition of the Pfafstetter rule (§3) was added when inspection of the basin areas (5.8 million km² for lagoon municipalities) revealed the omission, before any performance result. | before results |
| 2026-11-04 | **Basin rainfall adopted as the study and forecast input** (equivalent on the primary criterion, slightly better on secondary tests and on gauged floods; presented as equivalent, not as a proven gain). | after §9.1 / §8.2 results |
| 2026-11-04 | River-state predictor (§9.2) and second trigger (§9.3) registered. | before running |
| 2026-11-04 | **Second trigger adopted in the dashboard rule for both indices** (§10). | after §9.3 results |
| 2026-11-04 | Dashboard rule scored against gauged river floods (§8.2), frozen thresholds, descriptive. Forecast archive gains `rain_mm` (daily rainfall of the day; `P1` is the two-day maximum). | after §9.3 results |
| 2026-11-05 | Prospective forecast verification shown on the forecast page (`verification.json`): each forecast level vs the same rule on later MERGE rainfall, by model and lead; descriptive, nothing is fitted on it. | before results accumulate |
| 2026-11-05 | Reported floods added to the prospective verification: official S2iD records where a release covers the date, preliminary reports (alagamento, enxurrada, inundação only) after that; automatic weekly check for new releases. Missing issuances reconstructed from past 12 UTC runs (`backfill`). | before results accumulate |
| 2026-11-05 | Recent official records added: daily headless export of the public S2iD report "Danos informados" (RS, COBRADE 12100/12200/12300/13214, last 60 days of registrations), loaded into the same `events` table as the Atlas (protocol as key; date and IBGE code read from the protocol). All statuses count (registered, recognised, not recognised), as in the Atlas. Preliminary reports now count only when no official record exists in the same municipality within ±1 day, instead of only after the Atlas coverage end. | before results accumulate |
| 2026-11-24 | §§9.5–9.12 registered: forecast-level hindcast, bias correction, ensemble probabilities (prospective), GloFAS benchmark, independent ground truth (PRF, Copernicus EMS, Cemaden), SEDI / economic value / detectable effect, soil moisture, reproducibility. | before running any of them |
| 2026-11-24 | Implementation changes, before any result: (a) §9.7 — Open-Meteo serves no past ensemble run at all (single-runs: "not available" even for three days ago), so nothing is back-filled; the ensemble API serves only the latest run, so the run archived is the latest at workflow time (its initialisation is stored), not necessarily 12 UTC; the 0.5° forecast grid (155 points) is used because 51 + 31 members on the 0.25° grid exceed the free hourly quota. The member API is computed from 1 January of the previous year (identical to 1e-9 on the forecast days, `tests/test_ensemble.py`). The latest ensemble run usually starts at 00/06 UTC: the hours of the first 12–12 UTC window before it are taken from the first hours of earlier runs of the same ensemble (as served by the API), so the window is complete; small negative hourly values of ECMWF ENS members are set to 0 (counted in the log). (b) §9.5 — the 0.5° grid is used for the same quota reason (0.25° ≈ six days of downloads); the basin-rainfall difference between grids is reported on the overlap with the operational archive. §9.5 text "X … X+5" corrected to X … X+4 (leads 1–5, as stated). | before results |
| 2026-11-24 | §9.9 PRF cause categories, fixed from the category list and per-year counts only (no rainfall or level seen): primary = "Acumulo de água sobre o pavimento"; sensitivity = primary + "Chuva". Excluded: "Pista Escorregadia" (also oil, sand), "Fenômenos da Natureza" / "Demais Fenômenos da natureza" (wind, fog). Both categories exist only from 2021 (PRF taxonomy), so the PRF test covers 2021–2025 (BR-116/386/290 in RS: 154 primary records, 301 with sensitivity), not 2013–2025. | before results |
| 2026-11-24 | §9.11 soil moisture from the Copernicus Climate Data Store (`derived-era5-land-daily-statistics`, the same ERA5-Land, daily means of layers 1–3 combined as the 0–100 cm mean) instead of the Open-Meteo archive, whose free quota cannot serve 27 years over the upstream basins; nearest ERA5-Land point per MERGE cell (ties to the north/east); Feb 29 uses Feb 28's climatology. §9.8 GloFAS from the CEMS Early Warning Data Store (`cems-glofas-historical`, v4.0 consolidated) for the same reason. | before results |
| 2026-11-26 | §9.11 source changed again, before any soil-moisture value was analysed: the daily-statistics dataset allows ~4 months per request and its global queue held each request ~6 h (3 months in 24 h, ~80 days for 1999–2025). Now `reanalysis-era5-land` (same ERA5-Land fields) at 00, 06, 12 and 18 UTC, one request per year, daily value = mean of the four hours instead of the 24-hour mean. The difference is reported on the months downloaded both ways (Jan–Mar 1999, `python -m floodwatch.soil_moisture check`). | before results |
| 2026-11-26 | §9.11 4-hour vs 24-hour mean on Jan–Mar 1999: mean difference < 0.0001 m³/m³, 99th percentile of the absolute difference 0.002–0.004 m³/m³ (spatial SD 0.08). **After the first evaluation**, a defect was found: 15 basins have 0.01–20 % of their MERGE cells over lagoons or sea, where ERA5-Land has no soil value, and the rule "all cells valid" dropped them entirely (63,274 rows, 83 of 471 events missing). Fixed mechanically by averaging over land cells only; no threshold or grid changed. First run (incomplete sample): (i) SM − API −0.16 (−0.27 to −0.09), (ii) −0.0002 (−0.006 to +0.010); corrected run reported in README. Both negative. | after first run (defect fix) |
| 2026-11-27 | §9.7: dated correction (no back-fill possible; the archive starts on 25 Nov 2026) and the dashboard display / continuous-monitoring rule for the ensembles (level = highest level with P ≥ 0.5, fixed, never tuned; same verification as the deterministic forecasts; Brier score as monitoring). The registered one-year evaluation is unchanged. | before the §9.7 evaluation |
| 2026-11-28 | §9.8 implementation fixes, found when the first evaluation run stopped with no rows (no result was produced): (a) the EWDS serves longitudes 0–360, so no GloFAS cell matched a municipality; converted to −180–180; (b) the variable is the mean discharge of the 24 h before the valid time, so the value valid at d+1 00 UTC is assigned to day d (the requested days 1 Jan 1999 – 31 Dec 2025), making the window the registered max of d−1 and d. As registered, Esteio (27 km²), which contains no 0.05° cell centre, has no GloFAS value (4,147 rows, 8 events left out of both rules). 31 Dec 2024 is missing from the v4.0 consolidated dataset (the year file has 365 days; a request for that day is rejected as invalid): 84 rows without events left out. No threshold, window or sample rule changed. | before results |
| 2026-11-28 | §9.7 / §9.5 grid check (promised in the 2026-11-24 row), criterion stated before any value is computed. Data: Open-Meteo previous-runs API, ECMWF IFS 0.25 and GFS, `precipitation_previous_day1..3`, at the union of the 0.25° (632) and 0.5° (180) forecast points, days 3 Nov 2026 → 27 Nov 2026 (the same runs on both grids; the operational archive holds only the 0.25° grid). Basin rain of every municipality-day computed with the operational weights on each grid (`upstream.forecast_grid`); levels with the frozen rules, observed MERGE rainfall through X−1 and forecast X … X+2 (issuances 4 Nov → last MERGE day + 1). Reported: bias, mean absolute difference, correlation, 95th percentile of the absolute difference, level agreement and confusion tables, also by upstream-basin size (terciles of area). **Criterion:** for each model (ECMWF, GFS) and index (API, EDI), pooled over D+1–D+3, level agreement ≥ 90 % and |relative bias of basin rain| ≤ 10 % (Σ 0.5° − Σ 0.25°, ÷ Σ 0.25°) → the 0.5° grid is acceptable for the ensemble display; all four must pass. Agreement on days at Watch or above on either grid and the size split are descriptive, not part of the criterion. | before results |

## 12. Known limitations

- An S2iD record depends on the municipality requesting it, often to obtain federal funds: no record does not prove
  no flood, and coverage varies by year.
- The unit is the municipality, not the highway kilometre.
- Basin rainfall counts on the day it falls: no travel time, no reservoir operation.
- The EDI calibration covers 14 years (MERGE starts in 1998), shorter than the 30-year WMO standard.
- Out-of-sample TSS intervals resample test days with each fold's thresholds fixed; threshold uncertainty is shown
  separately (the threshold CI).
- The `climate-indices` flood module (EDI, API) was released in October 2026 and has no external numerical validation.
- The 2025 Atlas may still be incomplete (late registrations); 2025 rainfall is the preliminary MERGE version.
- River floods are defined statistically (median annual maximum), not by official flood stages; conventional readings
  (07:00 / 17:00) can miss the peak.
- The skill of the levels computed with forecast rainfall has not been measured yet (prospective archive, §10).
