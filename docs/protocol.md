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
