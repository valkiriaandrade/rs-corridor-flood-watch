"""Verification statistics shared by every analysis: contingency scores, AUC, thresholds, block bootstrap.

TSS (Peirce skill score) = POD - POFD. Thresholds: Watch = maximum TSS, Warning = lowest value with POFD <= 2 %.
Block bootstrap (2,000 replicates, seed 20261103): positives resampled by flood episode, negatives by year-month,
so one storm with dozens of records never counts as dozens of independent cases.
"""
import numpy as np
import pandas as pd

N_BOOT = 2000
SEED = 20261103


# ---------------------------------------------------------------- scores and thresholds
def candidates(values, n=400):
    """Threshold grid: quantiles 0.50-0.9995 of the finite values."""
    finite = values[np.isfinite(values)]
    return np.unique(np.quantile(finite, np.linspace(0.5, 0.9995, n)))


def frac_at_or_above(values, weights, thr):
    """Weighted fraction of values >= thr (thr scalar or array), via sorting: O((n+k) log n)."""
    order = np.argsort(values)
    v, w = values[order], weights[order]
    cum = np.concatenate([[0], np.cumsum(w)])
    below = cum[np.searchsorted(v, thr, 'left')]
    return (cum[-1] - below) / cum[-1]


def contingency(pos, neg, thr, wpos=None, wneg=None):
    """(POD, POFD) at each threshold, optionally weighted."""
    wpos = np.ones(len(pos)) if wpos is None else wpos
    wneg = np.ones(len(neg)) if wneg is None else wneg
    return frac_at_or_above(pos, wpos, thr), frac_at_or_above(neg, wneg, thr)


def best_tss(pos, neg, grid):
    """(threshold, POD, POFD) with the maximum TSS on the grid."""
    pod, pofd = contingency(pos, neg, grid)
    i = int(np.argmax(pod - pofd))
    return grid[i], pod[i], pofd[i]


def alert_threshold(neg, grid, max_pofd=0.02):
    """Lowest grid value with at most `max_pofd` of event-free days at or above it."""
    pofd = frac_at_or_above(neg, np.ones(len(neg)), grid)
    ok = np.where(pofd <= max_pofd)[0]
    return grid[ok[0]] if len(ok) else np.nan


def auc(pos, neg, wpos=None, wneg=None):
    """Area under the ROC curve (Mann-Whitney, ties count 1/2), optionally weighted."""
    wpos = np.ones(len(pos)) if wpos is None else wpos
    wneg = np.ones(len(neg)) if wneg is None else wneg
    order = np.argsort(neg)
    v, w = neg[order], wneg[order]
    cum = np.concatenate([[0], np.cumsum(w)])
    lo = np.searchsorted(v, pos, 'left')
    hi = np.searchsorted(v, pos, 'right')
    below = cum[lo] + 0.5 * (cum[hi] - cum[lo])
    return float((wpos * below).sum() / (wpos.sum() * w.sum()))


def score(pred, y, w=None):
    """POD, POFD, TSS and FAR of binary predictions against labels (optionally weighted)."""
    w = np.ones(len(y)) if w is None else w
    pos, neg = y == 1, y == 0
    hits = (w[pos] * pred[pos]).sum()
    fas = (w[neg] * pred[neg]).sum()
    pod, pofd = hits / w[pos].sum(), fas / w[neg].sum()
    far = fas / (hits + fas) if hits + fas else np.nan
    return {'POD': pod, 'POFD': pofd, 'TSS': pod - pofd, 'FAR': far}


# ---------------------------------------------------------------- out-of-sample designs
def year_folds(df):
    """Leave-one-year-out folds: [(year, test mask)]."""
    return [(str(yr), (df.year == yr).to_numpy()) for yr in sorted(df.year.unique())]


def holdout_folds(df, first_test_year=2021):
    """Temporal holdout: train 2013-2020, test 2021-2024."""
    return [(f'{first_test_year}-2024', (df.year >= first_test_year).to_numpy())]


def oos_predictions(df, col, folds):
    """Watch threshold (maximum TSS) chosen on the training rows of each fold; binary predictions for test rows."""
    pred = np.full(len(df), np.nan)
    thresholds = {}
    for name, test in folds:
        train = ~test
        pos = df.loc[train & (df.label == 1), col].to_numpy()
        neg = df.loc[train & (df.label == 0), col].to_numpy()
        thr = best_tss(pos, neg, candidates(np.concatenate([pos, neg])))[0]
        thresholds[name] = float(thr)
        pred[test] = (df.loc[test, col].to_numpy() >= thr).astype(float)
    return pred, thresholds


def oos_alert(df, col, folds, max_pofd=0.02):
    """Warning threshold (POFD <= 2 % on training negatives) chosen per fold; binary predictions for test rows."""
    pred = np.full(len(df), np.nan)
    thresholds = {}
    for name, test in folds:
        train = ~test
        neg = df.loc[train & (df.label == 0), col].to_numpy()
        pos = df.loc[train & (df.label == 1), col].to_numpy()
        thr = alert_threshold(neg, candidates(np.concatenate([pos, neg])), max_pofd)
        thresholds[name] = float(thr)
        pred[test] = (df.loc[test, col].to_numpy() >= thr).astype(float)
    return pred, thresholds


# ---------------------------------------------------------------- block bootstrap
class BlockBootstrap:
    """Replicate weights: positives resampled by block (episode), negatives by block (year-month).

    `W[b]` gives the weight of every row in replicate b; `W[b, mask]` the weights of a subset of rows.
    The multinomial counts are drawn once (positives, then negatives), so every analysis using the same
    sample and seed sees the same replicates."""

    def __init__(self, df, seed=SEED, n=N_BOOT):
        self.pos = df.label.to_numpy() == 1
        pos_blocks, neg_blocks = df.block[self.pos].unique(), df.block[~self.pos].unique()
        self._pc = pd.Categorical(df.block[self.pos], categories=pos_blocks).codes
        self._nc = pd.Categorical(df.block[~self.pos], categories=neg_blocks).codes
        rng = np.random.default_rng(seed)
        self._cp = rng.multinomial(len(pos_blocks), np.full(len(pos_blocks), 1 / len(pos_blocks)), size=n)
        self._cn = rng.multinomial(len(neg_blocks), np.full(len(neg_blocks), 1 / len(neg_blocks)), size=n)
        self.n, self.rows, self.n_pos_blocks = n, len(df), len(pos_blocks)

    def __getitem__(self, key):
        b, rows = key if isinstance(key, tuple) else (key, slice(None))
        w = np.empty(self.rows)
        w[self.pos] = self._cp[b][self._pc]
        w[~self.pos] = self._cn[b][self._nc]
        return w[rows]

    def subset(self, mask):
        """View restricted to the rows in `mask` (same replicates)."""
        return _Subset(self, mask)


class _Subset:
    def __init__(self, boot, mask):
        self.boot, self.mask, self.n = boot, mask, boot.n

    def __getitem__(self, b):
        return self.boot[b, self.mask]


def ci(values):
    """Percentile 95 % interval of the finite replicate values."""
    v = np.asarray(values, float)
    v = v[np.isfinite(v)]
    return [float(np.quantile(v, .025)), float(np.quantile(v, .975))] if len(v) else [None, None]


def scores(pred, y, boot):
    """Point POD/POFD/TSS with bootstrap 95 % CIs."""
    point = score(pred, y)
    reps = [score(pred, y, boot[b]) for b in range(boot.n)]
    out = {k: float(point[k]) for k in ('POD', 'POFD', 'TSS')}
    out.update({k + '_CI95': ci([x[k] for x in reps]) for k in ('POD', 'POFD', 'TSS')})
    return out


def paired(pred_a, pred_b, y, boot):
    """Paired TSS difference a - b with a bootstrap 95 % CI; 'improves' only if the whole CI is above 0."""
    reps = [score(pred_a, y, boot[b])['TSS'] - score(pred_b, y, boot[b])['TSS'] for b in range(boot.n)]
    c = ci(reps)
    return {'diff': float(score(pred_a, y)['TSS'] - score(pred_b, y)['TSS']), 'CI95': c,
            'improves': bool(c[0] is not None and c[0] > 0)}
