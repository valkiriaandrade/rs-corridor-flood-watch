# Data sources and attribution

| Data | Provider | Use | Access / licence |
|---|---|---|---|
| MERGE daily rainfall (GPM-IMERG V07B final 1998–2024; IMERG late/early 2025–) | CPTEC/INPE | rainfall, PE, EDI | https://ftp.cptec.inpe.br/modelos/tempo/MERGE/GPM/DAILY/ (public; cite Rozante et al. 2010, CPTEC/INPE) |
| Atlas Digital de Desastres no Brasil, BD v1.1 (06/08/2026) | MIDR / Defesa Civil Nacional, CEPED-UFSC (S2iD records) | flood events 2013–2025 | https://atlasdigital.mdr.gov.br (public download) |
| Municipal boundaries (2022 mesh, intermediate quality) and names | IBGE | spatial unit | https://servicodados.ibge.gov.br (public) |
| SNV 202404A federal road network (BR-116, BR-386, BR-290) | DNIT | corridor municipalities, map | https://servicos.dnit.gov.br/dnitgeo (WFS, public) |
| Base Hidrográfica Ottocodificada Multiescalas 2017 5k, Ottobacias nível 6 | ANA | upstream basin of each municipality | https://metadados.snirh.gov.br (public; `geoft_bho_ach_otto_nivel_06.gpkg`) |
| HidroWeb river stage series (HidroInventario, HidroSerieHistorica) | ANA | river-level validation (extra) | http://telemetriaws1.ana.gov.br/ServiceANA.asmx (public web service) |
| ECMWF IFS and NOAA GFS deterministic forecasts | ECMWF, NOAA via Open-Meteo | forecast rainfall | https://open-meteo.com (CC BY 4.0; ECMWF open data licence) |
| Documented road impacts (2016–2024) | DNIT/PRF bulletins and Defesa Civil compiled in the preceding project | independent check only | `data/raw/road_impacts/` (source URLs inside) |
| ECMWF ENS (51 members) and NOAA GEFS (31 members) ensemble forecasts | ECMWF, NOAA via Open-Meteo | ensemble probabilities (§9.7), past runs for the hindcast (§9.5) | https://open-meteo.com (CC BY 4.0) |
| S2iD report "Danos informados" (RS, flood COBRADEs, last 60 days) | MIDR / Defesa Civil Nacional | recent flood records for forecast verification | https://s2id.mi.gov.br/paginas/relatorios/ (public; blocks IPs outside Brazil) |
| Traffic accidents 2021–2025 (`datatran`), weather = water on the road | Polícia Rodoviária Federal | independent check (§9.9) | https://www.gov.br/prf/pt-br/acesso-a-informacao/dados-abertos/dados-abertos-da-prf (public; SHA-256 in `data/raw/prf/provenance.json`) |
| Rapid mapping activation EMSR720 (May 2024) | Copernicus Emergency Management Service | independent check (§9.9) | https://rapidmapping.emergency.copernicus.eu/EMSR720 (free, attribution required) |
| GloFAS v4.0 consolidated reanalysis, daily river discharge 1999–2025 | Copernicus EMS / ECMWF (EWDS dataset `cems-glofas-historical`) | benchmark (§9.8) | https://ewds.climate.copernicus.eu (free account; CEMS-FLOODS licence) |
| ERA5-Land daily statistics, volumetric soil water layers 1–3, 1999–2025 | Copernicus Climate Change Service / ECMWF (CDS dataset `derived-era5-land-daily-statistics`) | soil-moisture predictor (§9.11) | https://cds.climate.copernicus.eu (free account; CC BY 4.0) |
| Basemap | CARTO Positron, © OpenStreetMap contributors | map background | https://carto.com/basemaps (attribution shown on map) |
| PE / EDI / API implementation | `climate-indices` 3.0.0 (J. Adams) | indices | https://github.com/monocongo/climate_indices (BSD-3) |

Every downloaded file has a sibling `.http.json` with URL, download time, size and SHA-256.

## References
1. Byun, H.-R.; Wilhite, D. A. (1999). Objective Quantification of Drought Severity and Duration. *Journal of Climate* 12(9):2747–2756. https://doi.org/10.1175/1520-0442(1999)012%3C2747:OQODSA%3E2.0.CO;2
2. Deo, R. C.; Byun, H.-R.; Adamowski, J. F.; Kim, D.-W. (2015). A Real-time Flood Monitoring Index Based on Daily Effective Precipitation… *Water Resources Management* 29(11):4075–4093. https://doi.org/10.1007/s11269-015-1046-3
3. Ramos Filho, G. M. et al. (2021). An improved rainfall-threshold approach for robust prediction and warning of flood and flash flood hazards. *Natural Hazards* 105(3):2409–2429. https://doi.org/10.1007/s11069-020-04405-x
4. Silva, J. R.; Nunes, A. B. (2012). Análise quantitativa de eventos extremos de precipitação para Bagé e sua relação com o El Niño. ENPOS/UFPel.
5. Casa Civil/PR (2025). Nota Técnica nº 1/2025 – Cadastro de municípios suscetíveis a enxurradas e inundações.
6. Collischonn, W. et al. (2025). The exceptional hydrological disaster of April–May 2024 in southern Brazil. *RBRH* 30. https://doi.org/10.1590/2318-0331.302520240119
7. Medeiros, M. S.; Fan, F. M.; Paiva, R. C. D. (2025). Emergency forecasts for water levels in the Guaíba River during the 2024 flood. *RBRH* 30. https://doi.org/10.1590/2318-0331.302520250025
8. Kohler, M. A.; Linsley, R. K. (1951). Predicting the runoff from storm rainfall. Research Paper 34, U.S. Weather Bureau.
9. ANA (2017). Base Hidrográfica Ottocodificada Multiescalas 2017 5k (BHO 2017 5k). Agência Nacional de Águas e Saneamento Básico.
10. Ferro, C. A. T.; Stephenson, D. B. (2011). Extremal Dependence Indices: Improved Verification Measures for Deterministic Forecasts of Rare Binary Events. *Weather and Forecasting* 26(5):699–713. https://doi.org/10.1175/WAF-D-10-05030.1
11. Richardson, D. S. (2000). Skill and relative economic value of the ECMWF ensemble prediction system. *Quarterly Journal of the Royal Meteorological Society* 126(563):649–667. https://doi.org/10.1002/qj.49712656313
12. Muñoz-Sabater, J. et al. (2021). ERA5-Land: a state-of-the-art global reanalysis dataset for land applications. *Earth System Science Data* 13:4349–4383. https://doi.org/10.5194/essd-13-4349-2021
13. Copernicus Emergency Management Service (2019, updated). River discharge and related historical data from the Global Flood Awareness System (GloFAS), v4.0. Early Warning Data Store. https://doi.org/10.24381/cds.a4fdd6b9
