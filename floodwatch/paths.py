"""All file locations of the project in one place."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'data' / 'raw'
MERGE = RAW / 'merge'                 # MERGE/CPTEC daily GRIB2 + CTL (downloaded by floodwatch.fetch)
ATLAS = RAW / 'atlas'                 # Atlas Digital de Desastres no Brasil (BD v1.1)
SPATIAL = RAW / 'spatial'             # IBGE municipalities, DNIT SNV corridors
ROAD_IMPACTS = RAW / 'road_impacts'   # documented road impacts (independent check only)
FORECAST_RAW = RAW / 'forecast_api'   # raw Open-Meteo responses
STUDY = ROOT / 'data' / 'processed' / 'study'
FORECAST = ROOT / 'data' / 'processed' / 'forecast'
