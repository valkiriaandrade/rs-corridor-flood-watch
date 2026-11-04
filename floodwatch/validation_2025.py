"""Independent 2025 test with frozen 2013-2024 thresholds (pre-registered in docs/protocol.md).

2025 was not used by any stage of the study. Rainfall: MERGE IMERG late/early (the V07B final version is not yet
published), over the same upstream basins; events: Atlas Digital BD v1.1 records of 2025, same rules.
Run: python -m floodwatch.validation_2025
"""
import json

import pandas as pd

from . import indices, study
from .paths import STUDY
from .stats import BlockBootstrap, paired, scores
from .upstream import compute_rain

YEAR = 2025
START, END = pd.Timestamp(f'{YEAR}-01-01'), pd.Timestamp(f'{YEAR}-12-31')


def events_2025(units):
    atlas = pd.read_csv(study.RAW / 'atlas/BD_Atlas_1991_2025_v1.1.csv', sep=';', encoding='latin1', low_memory=False)
    atlas = atlas[(atlas.Sigla_UF == 'RS') & atlas.Cod_Cobrade.isin(study.CODES)].copy()
    atlas['date'] = pd.to_datetime(atlas.Data_Evento, dayfirst=True)
    atlas['codarea'] = atlas.Cod_IBGE_Mun.astype(str)
    atlas = atlas[atlas.codarea.isin(units.codarea) & atlas.date.between(START, END)]
    return study.chain_events(atlas), atlas


def rain_through_2025(hist=None, recent=None):
    """Study rainfall 1998-2024 followed by 2025 (basin by default); raises if any 2025 day is missing."""
    hist = study.study_rain('2024-12-31') if hist is None else hist
    states = None
    if recent is None:
        recent, states = compute_rain(str(START.date()), str(END.date()))
    rain = pd.concat([hist, recent.loc[:END, hist.columns]])
    if rain.loc[START:END].isna().any().any():
        raise ValueError('Chuva de 2025 incompleta: rode python -m floodwatch.fetch merge-recent')
    return rain, states


def predictor_table(rain):
    """Windowed predictors (P1..P30, PE, EDI, API) from 1998-2025 rainfall, study calibration."""
    pe, edi, api = {}, {}, {}
    for code in rain.columns:
        r, _ = indices.compute(rain[code], study.CAL[0], study.CAL[1], END + pd.Timedelta(days=1))
        pe[code], edi[code], api[code] = r.pe_mm.to_numpy(), r.edi.to_numpy(), indices.api(rain[code])
    frame = lambda d: pd.DataFrame(d, index=rain.index)
    return study.predictors(rain, frame(pe), frame(edi), frame(api))


def sample_2025(table):
    """2025 case-control sample with the study rules (events, episodes, ±15-day exclusion)."""
    units = pd.read_csv(STUDY / 'units.csv', dtype={'codarea': str})
    events, records = events_2025(units)
    return study.samples(table, events, records, START, END), events, records


def run():
    fin = json.loads((STUDY / 'results.json').read_text(encoding='utf-8'))['final_thresholds_all_years']
    frozen = {'EDI_attention': fin['EDI']['attention'], 'EDI_alert': fin['EDI']['alert_pofd2pct'],
              'API_attention': fin['API']['attention'], 'API_alert': fin['API']['alert_pofd2pct'],
              'P30': fin['P30']['attention']}
    rain, states = rain_through_2025()
    sample, events, records = sample_2025(predictor_table(rain))
    y = sample.label.to_numpy()
    W = BlockBootstrap(sample)
    column = {'EDI_attention': 'EDI', 'EDI_alert': 'EDI', 'API_attention': 'API', 'API_alert': 'API', 'P30': 'P30'}
    preds = {k: (sample[column[k]] >= thr).to_numpy(float) for k, thr in frozen.items()}
    out = {'year': YEAR, 'frozen_thresholds': frozen,
           'rain_product_states': pd.Series(states).loc[str(START.date()):str(END.date())].value_counts().to_dict(),
           'records': int(len(records)), 'events': int(W.pos.sum()), 'episodes': int(W.n_pos_blocks),
           'negatives': int((~W.pos).sum()), 'events_by_month': events.date.dt.month.value_counts().sort_index().to_dict(),
           'episodes_list': events.groupby('episode_id').size().to_dict()}
    out.update({k: scores(p, y, W) for k, p in preds.items()})
    out['EDI_minus_P30_TSS'] = paired(preds['EDI_attention'], preds['P30'], y, W)
    out['API_minus_EDI_TSS'] = paired(preds['API_attention'], preds['EDI_attention'], y, W)
    out['confirmed_2025'] = bool(out['EDI_attention']['TSS_CI95'][0] > 0.2)       # pre-registered criterion
    out['confirmed_2025_API'] = bool(out['API_attention']['TSS_CI95'][0] > 0.2)
    pos = sample[W.pos]  # diagnostics shown on the study page (descriptive)
    out['by_episode'] = {str(k): {'events': int(len(g)), 'start': str(pd.Timestamp(g.date.min()).date()),
                                  'EDI_median': float(g.EDI.median()),
                                  'share_at_attention': float((g.EDI >= frozen['EDI_attention']).mean()),
                                  'API_median': float(g.API.median()),
                                  'API_share_at_attention': float((g.API >= frozen['API_attention']).mean())}
                         for k, g in pos.groupby('block')}
    hist_pos = pd.read_csv(STUDY / 'samples.csv.gz', usecols=['label', 'EDI', 'API'])
    for ix in ('EDI', 'API'):
        out[f'{ix}_median_events_2013_2024'] = float(hist_pos.loc[hist_pos.label == 1, ix].median())
        out[f'{ix}_median_events_2025'] = float(pos[ix].median())
    (STUDY / 'validation_2025.json').write_text(json.dumps(out, indent=1, default=str), encoding='utf-8')
    events.to_csv(STUDY / 'events_2025.csv', index=False)
    print(json.dumps({k: out[k] for k in ('events', 'episodes', 'EDI_attention', 'API_attention')}, indent=1))


if __name__ == '__main__':
    run()
