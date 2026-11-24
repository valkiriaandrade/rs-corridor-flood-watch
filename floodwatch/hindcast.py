"""Hindcast of the forecast levels (docs/protocol.md §9.5): how much of the observed-rainfall skill survives on forecast
rainfall, by lead.

Rainfall: Open-Meteo previous-runs API (as §9.4), hourly precipitation_previous_day1..5 of ECMWF IFS 0.25 and GFS, on the
0.5-degree forecast grid (155 points; the 0.25-degree grid would take about six days of the free quota, decision log
2026-11-24), basin means with the operational weights, 12-12 UTC days. Lead L of day D = previous_day{L} over D's window.
Chain: issuance day X, observed basin rainfall through X-1, forecast rainfall for X .. X+4 (lead D - X + 1 = 1..5),
operational indices and frozen rules. Nothing is fitted.
    python -m floodwatch.hindcast download   # resumable; paced under the free-tier limits
"""
import json
import sys
import time
from datetime import datetime, timezone

import pandas as pd
import requests

from . import upstream
from .forecast_skill import API, UA, Budget, weight
from .paths import RAW

ARCHIVE = RAW / 'hindcast'
MODELS = {'ECMWF': 'ecmwf_ifs025', 'GFS': 'gfs_global'}
LEADS = [1, 2, 3, 4, 5]
START, END = pd.Timestamp('2024-03-01'), pd.Timestamp('2025-12-31')
STEP = 0.5
CHUNK_DAYS = 92
BATCH = 20


def download():
    points, _ = upstream.forecast_grid(step=STEP)
    budget = Budget()
    hourly = ','.join(f'precipitation_previous_day{n}' for n in LEADS)
    chunks = pd.date_range(START - pd.Timedelta(days=1), END, freq=f'{CHUNK_DAYS}D')  # day D's window starts D-1 13 UTC
    for name, code in MODELS.items():
        folder = ARCHIVE / code
        folder.mkdir(parents=True, exist_ok=True)
        for c0 in chunks:
            c1 = min(c0 + pd.Timedelta(days=CHUNK_DAYS - 1), END)
            for off in range(0, len(points), BATCH):
                b = points.iloc[off:off + BATCH]
                path = folder / f'{c0:%Y%m%d}_{c1:%Y%m%d}_{off:03d}.json'
                if path.exists():
                    continue
                params = {'latitude': ','.join(f'{x:.2f}' for x in b.lat), 'longitude': ','.join(f'{x:.2f}' for x in b.lon),
                          'hourly': hourly, 'models': code, 'start_date': f'{c0:%Y-%m-%d}', 'end_date': f'{c1:%Y-%m-%d}',
                          'timezone': 'UTC'}
                for attempt in range(6):
                    budget.wait(weight(len(b), (c1 - c0).days + 1, len(LEADS)))
                    r = requests.get(API, params=params, headers=UA, timeout=300)
                    if r.status_code == 429:
                        pause = int(r.headers.get('Retry-After', 0)) or 900 * (attempt + 1)
                        print(f'  429 {r.text[:120]} -> waiting {pause}s', flush=True)
                        time.sleep(pause)
                        continue
                    r.raise_for_status()
                    break
                else:
                    raise RuntimeError('rate limited repeatedly; stopping (run again later, it resumes)')
                path.write_text(r.text, encoding='utf-8')
                path.with_suffix('.http.json').write_text(json.dumps({
                    'url': r.url, 'time_utc': datetime.now(timezone.utc).isoformat(), 'bytes': len(r.content),
                    'points': b.point.tolist()}), encoding='utf-8')
                print(f'{name} {c0:%Y-%m-%d}..{c1:%Y-%m-%d} points {off}-{off + len(b) - 1} ok', flush=True)


if __name__ == '__main__':
    if sys.argv[1:] == ['download']:
        download()
