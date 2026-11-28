# Changelog

All notable changes to this project. Versions are archived on Zenodo under the concept DOI
[10.5281/zenodo.24508671](https://doi.org/10.5281/zenodo.24508671), which always resolves to the latest version.

## [1.1.0] — 2026-11-28 (not yet released)

### Results of the registered supplementary analyses

The rules, thresholds and samples of v1.0 are unchanged. The analyses below were registered in docs/protocol.md on
2026-11-24, before they were run.

- **§9.5 Forecast-level hindcast.** The frozen rules on archived ECMWF IFS and GFS runs, March 2024 – December 2025,
  170 events. With the API rule:
  - observed rain: TSS 0.60;
  - ECMWF: 0.47 / 0.46 / 0.52 at D+1 / D+3 / D+5;
  - GFS: 0.40 / 0.27 / 0.25.

  Skill loss over D+1–D+3: ECMWF −0.13 (95 % CI −0.21 to −0.05), GFS −0.28.
- **§9.6 Bias correction.** Quantile mapping does not help (TSS change −0.006 to −0.025). Not adopted.
- **§9.7 Forecast grid check, 0.5° vs 0.25°.** Basin rainfall on the 0.5° forecast points (ensembles and hindcast)
  against the 0.25° points (deterministic forecasts), same ECMWF and GFS runs, November 2026. The criterion was stated
  in the decision log before computing (level agreement ≥ 90 % and |relative bias| ≤ 10 %) and is met for both
  models and both indices: bias +3 %, levels agree on 98–99 % of municipality-days. The 0.5° grid is acceptable for
  the ensemble display.
- **§9.8 GloFAS benchmark.** River discharge does not beat the rainfall rule. Leave-one-year-out TSS is 0.51 for
  GloFAS and 0.56 for the API rule; the API − GloFAS difference is +0.05 (−0.01 to +0.10). On 2025: 0.33 vs 0.56.
- **§9.11 Soil moisture.** ERA5-Land soil moisture is worse than the API alone (−0.18, −0.29 to −0.10). Adding it to
  the rule changes nothing (−0.003). Negative result.

### Dashboard

- **Model accuracy first.**
  - Five accuracy cards: ECMWF, GFS, Consensus, ECMWF ENS and GEFS. Each shows the event hit rate (CSI) at D+1–D+3
    over the last 30 days, a sparkline, and a detection / false-alarm line.
  - A single filter bar for index, model and day. The API is the default index.
  - The map and the corridor status are on the first screen.
- **Ensembles selectable.** The ECMWF ENS and GEFS level is the highest level with P ≥ 0.5. This is a fixed display
  rule, never tuned.
- **"Acerto dos modelos em detalhe" / model accuracy in detail.**
  - Full table and highlighted trend chart, with 30-day, common-period and all windows.
  - Brier scores of the ensembles.
  - How the scores are computed.
  - The last verified day.
- **Official records section.**
  - S2iD flood records since the forecast archive started, and the registration lag.
  - For every corridor record: the rule level with observed rain, and the archived forecasts of each model at
    D+1–D+3.
  - Alarms without an official record, kept apart from the false-alarm rate.
- **PDF briefing.** Includes the current accuracy of the models.

### Pipeline and data

- Continuous verification of all five models, exported for the deployed app:
  - `verification.json`;
  - `verification_daily.csv`;
  - `ensemble_levels.csv` per run.
- Official records summary `official_records.json`, built from the weekly S2iD export and the rule on observed rain.
- Copernicus downloads, one request at a time with patient retries:
  - ERA5-Land soil moisture: hourly, at 00/06/12/18 UTC;
  - GloFAS v4.0 reanalysis.

### Protocol and decision log

- §9.7 dated correction: the ensemble archive starts on 25 Nov 2026, with no back-fill, because Open-Meteo serves no past
  ensemble runs. The registered text is kept.
- Ensemble display and continuous-monitoring rule.
- Decision-log rows for the soil-moisture source change, and two defect fixes found after a first run:
  - soil moisture: basins partly over water;
  - GloFAS: longitudes 0–360 and the day of the 24-hour mean.

  Both runs are reported.

### Fixed

- Soil moisture: basin means over land cells only. Basins partly over lagoons or sea had been dropped.
- GloFAS: longitudes converted from 0–360; each 24-hour mean assigned to its own day.

### CI, tests and dependencies

- Tests workflow on every push and pull request, with least-privilege permissions.
  - The tests block the network.
  - They cover the daily job (run fallback, catch-up dates, archive writes and check, verification pairing), both
    dashboard pages in Portuguese and English, the continuous verification, the S2iD records, the GloFAS file
    alignment and the grid check.
  - 58 tests in total.
- Lint and format with ruff 0.17.6, also in pre-commit. Formatting-only commit listed in `.git-blame-ignore-revs`.
  Error and log messages in English; the dashboard stays bilingual.
- Dependabot for GitHub Actions. Bumps:
  - actions/checkout 4 → 7;
  - actions/setup-python 5 → 7;
  - actions/cache 4 → 6;
  - actions/upload-artifact 4 → 7.

### Docs

- README:
  - dashboard link and badge;
  - results of §§9.5, 9.6, 9.8 and 9.11;
  - dashboard section in the new order;
  - module table and data layout.
- Runbook and data sources brought up to date.

## [1.0.0] — 2026-11-24

First archived version ([10.5281/zenodo.24508672](https://doi.org/10.5281/zenodo.24508672)).

- **Thresholds.** Flood-potential thresholds (EDI, API) for the BR-116, BR-386 and BR-290 corridors:
  - calibrated and validated out of sample against S2iD records (2013–2024);
  - tested on 2025, on gauged river floods and on road impacts.
- **Protocol.** Pre-registered protocol with the decision log, including §§9.5–9.12, registered before they were run.
- **Supplementary checks:**
  - SEDI, relative economic value and minimum detectable effect (§9.10);
  - PRF water-on-road accidents, the corridor display rule and Copernicus EMS (§9.9).
- **Forecasts.** Daily ECMWF/GFS forecast pipeline, a prospective verification archive, and ensemble probabilities
  (§9.7, prospective).
