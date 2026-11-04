"""Second short-term heavy-rain trigger: Watch if index >= threshold OR P3 >= b (docs/protocol.md §9.3).

Pre-registered before running. In every fold the index threshold is the one of the index alone (maximum TSS on the
training years) and b maximises the TSS of the OR rule on the same training years. The final b is refit on
2013-2024 and frozen; it is part of the dashboard rule (floodwatch.rules). 2025 is descriptive only (the hypothesis
came from the 2025 test); confirmation is prospective (records from 2026 onwards, forecast archive).
    python -m floodwatch.second_trigger   -> data/processed/study/second_trigger.json
"""
import json

import numpy as np
import pandas as pd

from . import study
from .paths import STUDY
from .stats import BlockBootstrap, best_tss, candidates, holdout_folds, paired, score, scores, year_folds

INDICES = ['EDI', 'API']
DESIGNS = {'LOYO': year_folds, 'holdout_2013-2020_vs_2021-2024': holdout_folds}


def p3_grid(values):
    finite = values[np.isfinite(values)]
    return np.unique(np.quantile(finite, np.linspace(0.90, 0.9995, 120)))


def best_or(index_hit, p3, y, grid):
    """b maximising TSS of (index_hit OR p3 >= b)."""
    pos, neg = y == 1, y == 0
    tss = [((index_hit | (p3 >= b))[pos].mean() - (index_hit | (p3 >= b))[neg].mean()) for b in grid]
    return float(grid[int(np.argmax(tss))])


def fit_rule(df, ix, train):
    """Index threshold (index alone) and b (OR rule), both from the training rows only."""
    tr = df[train]
    pos, neg = tr.loc[tr.label == 1, ix].to_numpy(), tr.loc[tr.label == 0, ix].to_numpy()
    thr = float(best_tss(pos, neg, candidates(np.concatenate([pos, neg])))[0])
    b = best_or((tr[ix] >= thr).to_numpy(), tr.P3.to_numpy(), tr.label.to_numpy(), p3_grid(tr.P3.to_numpy()))
    return thr, b


def oos(df, ix, folds):
    """Out-of-sample predictions of the index alone and of the OR rule, plus the per-fold parameters."""
    alone, both, params = np.full(len(df), np.nan), np.full(len(df), np.nan), {}
    for name, test in folds:
        thr, b = fit_rule(df, ix, ~test)
        params[name] = {'index': thr, 'P3': b}
        te = df[test]
        alone[test] = (te[ix] >= thr).to_numpy(float)
        both[test] = ((te[ix] >= thr) | (te.P3 >= b)).to_numpy(float)
    return alone, both, params


def run():
    df = pd.read_csv(STUDY / 'samples.csv.gz', parse_dates=['date'], dtype={'codarea': str})
    df = df.dropna(subset=study.PREDICTORS).reset_index(drop=True)
    y = df.label.to_numpy()
    W = BlockBootstrap(df)
    big24, _ = study.big_episode_mask(df)
    out = {'rule': 'index >= threshold OR P3 >= b', 'rows': int(len(df)), 'positives': int(W.pos.sum()), 'designs': {}}
    for dn, make_folds in DESIGNS.items():
        folds = make_folds(df)
        m = np.zeros(len(df), bool)
        for _, t in folds:
            m |= t
        sub, no24 = W.subset(m), m & ~big24
        out['designs'][dn] = {}
        for ix in INDICES:
            alone, both, params = oos(df, ix, folds)
            res = {'alone': scores(alone[m], y[m], sub), 'with_P3': scores(both[m], y[m], sub),
                   'paired_with_minus_alone': paired(both[m], alone[m], y[m], sub),
                   'P3_fold_range': [min(p['P3'] for p in params.values()), max(p['P3'] for p in params.values())]}
            res['alone']['TSS_without_AprMay2024'] = float(score(alone[no24], y[no24])['TSS'])
            res['with_P3']['TSS_without_AprMay2024'] = float(score(both[no24], y[no24])['TSS'])
            out['designs'][dn][ix] = res
    everything = np.ones(len(df), bool)
    out['final_frozen'] = {ix: dict(zip(('index_attention', 'P3_mm'), fit_rule(df, ix, everything))) for ix in INDICES}
    try:
        out['test_2025_descriptive'] = test_2025(out['final_frozen'])
    except Exception as error:  # keep the 2013-2024 results if 2025 rainfall is incomplete
        out['test_2025_descriptive'] = {'error': f'{type(error).__name__}: {error}'}
    (STUDY / 'second_trigger.json').write_text(json.dumps(out, indent=1, default=float), encoding='utf-8')
    for dn, d in out['designs'].items():
        for ix, r in d.items():
            print(dn, ix, 'alone', round(r['alone']['TSS'], 3), 'with P3', round(r['with_P3']['TSS'], 3),
                  'diff', round(r['paired_with_minus_alone']['diff'], 3), r['paired_with_minus_alone']['CI95'])
    print(json.dumps(out['final_frozen'], indent=1))
    return out


def test_2025(final):
    from . import validation_2025 as V
    rain, _ = V.rain_through_2025()
    sample, _, _ = V.sample_2025(V.predictor_table(rain))
    sample = sample.dropna(subset=['EDI', 'API', 'P3']).reset_index(drop=True)
    y = sample.label.to_numpy()
    W = BlockBootstrap(sample)
    june = (sample.block == 'EP-20250614').to_numpy() & W.pos
    res = {'events': int(W.pos.sum())}
    for ix, f in final.items():
        alone = (sample[ix] >= f['index_attention']).to_numpy(float)
        both = ((sample[ix] >= f['index_attention']) | (sample.P3 >= f['P3_mm'])).to_numpy(float)
        res[ix] = {'alone': scores(alone, y, W), 'with_P3': scores(both, y, W), 'paired': paired(both, alone, y, W),
                   'june_share_alone': float(alone[june].mean()) if june.any() else None,
                   'june_share_with_P3': float(both[june].mean()) if june.any() else None}
    return res


if __name__ == '__main__':
    run()
