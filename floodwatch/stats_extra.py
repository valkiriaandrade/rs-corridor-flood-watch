"""Statistical additions registered in docs/protocol.md §9.10 (no decision changes).

- SEDI (Ferro & Stephenson 2011, symmetric extremal dependence index), next to the TSS, for the same leave-one-year-out
  predictions and block bootstrap as the study (§7). SEDI does not degenerate for rare events as the TSS can.
- Relative economic value V(C/L) (Richardson 2000) of the frozen dashboard rules, LOYO predictions, C/L 0.01-0.99.
- Minimum detectable paired TSS difference at 80 % power (two-sided 5 %): 2.8 x the bootstrap SD of the paired
  difference, for the comparisons the study reports as "not proven".
    python -m floodwatch.stats_extra   -> data/processed/study/stats_extra.json
"""

import json

import numpy as np
import pandas as pd

from . import study
from .paths import STUDY
from .second_trigger import oos
from .stats import BlockBootstrap, ci, oos_alert, oos_predictions, score, year_folds


def sedi(pod, pofd):
    """SEDI from hit rate H and false-alarm rate F; undefined (nan) at 0 or 1."""
    h, f = float(pod), float(pofd)
    if not (0 < h < 1 and 0 < f < 1):
        return np.nan
    lf, lh, l1f, l1h = np.log(f), np.log(h), np.log(1 - f), np.log(1 - h)
    return (lf - lh - l1f + l1h) / (lf + lh + l1f + l1h)


def with_ci(pred, y, boot):
    point = score(pred, y)
    reps = [score(pred, y, boot[b]) for b in range(boot.n)]
    out = {
        'POD': float(point['POD']),
        'POFD': float(point['POFD']),
        'TSS': float(point['TSS']),
        'SEDI': float(sedi(point['POD'], point['POFD'])),
    }
    out['TSS_CI95'] = ci([r['TSS'] for r in reps])
    out['SEDI_CI95'] = ci([sedi(r['POD'], r['POFD']) for r in reps])
    return out


def economic_value(pod, pofd, base_rate, ratios):
    """Richardson (2000): V = (min(a, s) - F a (1 - s) + H s (1 - a) - s) / (min(a, s) - s a), a = C/L, s = base rate."""
    a, s, h, f = np.asarray(ratios), base_rate, pod, pofd
    return (np.minimum(a, s) - f * a * (1 - s) + h * s * (1 - a) - s) / (np.minimum(a, s) - s * a)


def detectable(pred_a, pred_b, y, boot):
    """Paired TSS difference a - b, its bootstrap SD, CI and the minimum detectable difference at 80 % power."""
    reps = np.array([score(pred_a, y, boot[b])['TSS'] - score(pred_b, y, boot[b])['TSS'] for b in range(boot.n)])
    sd = float(np.nanstd(reps, ddof=1))
    return {
        'diff': float(score(pred_a, y)['TSS'] - score(pred_b, y)['TSS']),
        'CI95': ci(reps),
        'boot_SD': sd,
        'min_detectable_80pct_power': 2.8 * sd,
    }


def run():
    df = pd.read_csv(STUDY / 'samples.csv.gz', parse_dates=['date'], dtype={'codarea': str})
    df = df.dropna(subset=study.PREDICTORS).reset_index(drop=True)
    y = df.label.to_numpy()
    W = BlockBootstrap(df)
    folds = year_folds(df)
    preds = {}
    for ix in ('EDI', 'API'):
        alone, rule, _ = oos(df, ix, folds)
        preds[f'{ix} alone'], preds[f'{ix} dashboard rule'] = alone, rule
    for ix in ('EDI', 'API'):  # Warning level of the dashboard rule (threshold with POFD <= 2 % in each training fold)
        preds[f'{ix} Warning level'], _ = oos_alert(df, ix, folds)
    for col in ('P30', 'P3'):
        preds[f'{col} alone'], _ = oos_predictions(df, col, folds)
    out = {
        'design': 'leave-one-year-out 2013-2024, same samples and block bootstrap as the study (§7)',
        'rows': int(len(df)),
        'positives': int((y == 1).sum()),
        'base_rate': float(y.mean()),
        'scores': {},
    }
    for name, p in preds.items():
        out['scores'][name] = with_ci(p, y, W)
        print(name, {k: round(v, 3) for k, v in out['scores'][name].items() if not k.endswith('CI95')})
    ratios = np.unique(np.round(np.concatenate([np.geomspace(1e-4, 0.01, 41), np.arange(0.01, 1.0, 0.01)]), 6))
    out['economic_value'] = {'cost_loss_ratio': ratios.tolist()}
    for name in ('API dashboard rule', 'EDI dashboard rule', 'API Warning level', 'EDI Warning level', 'P30 alone'):
        s = out['scores'][name]
        v = economic_value(s['POD'], s['POFD'], out['base_rate'], ratios)
        out['economic_value'][name] = {
            'V': [float(x) for x in v],
            'V_max': float(np.nanmax(v)),
            'C/L_at_V_max': float(ratios[int(np.nanargmax(v))]),
            'C/L_with_V_above_0': [float(ratios[v > 0].min()), float(ratios[v > 0].max())] if (v > 0).any() else None,
        }
    out['detectable_differences'] = {
        'API rule - EDI rule': detectable(preds['API dashboard rule'], preds['EDI dashboard rule'], y, W),
        'API alone - P30 alone': detectable(preds['API alone'], preds['P30 alone'], y, W),
        'EDI alone - P30 alone': detectable(preds['EDI alone'], preds['P30 alone'], y, W),
    }
    for k, d in out['detectable_differences'].items():
        print(k, round(d['diff'], 3), d['CI95'], 'MDE', round(d['min_detectable_80pct_power'], 3))
    (STUDY / 'stats_extra.json').write_text(json.dumps(out, indent=1, default=float), encoding='utf-8')
    return out


if __name__ == '__main__':
    run()
