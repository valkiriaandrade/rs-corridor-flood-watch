"""Operational flood-potential rules: one place that turns an index value into Normal / Watch / Warning.

Rule for each index (EDI, API), all values frozen from the 2013-2024 study (docs/protocol.md):
    Warning  if index >= alert threshold (lowest value with <= 2 % of event-free days above it)
    Watch    if index >= attention threshold (maximum Peirce skill), OR 3-day basin rainfall P3 >= trigger
    Normal   otherwise; 'no data' (-1) when the index is missing (never shown as Normal)
Sources: results.json (thresholds) and second_trigger.json (P3 trigger, refit on 2013-2024 and frozen).
"""
from dataclasses import asdict, dataclass
import json

import numpy as np

from .paths import STUDY

INDICES = ('EDI', 'API')
UNITS = {'EDI': '', 'API': 'mm'}
NO_DATA, NORMAL, WATCH, WARNING = -1, 0, 1, 2


@dataclass(frozen=True)
class Rule:
    index: str
    attention: float
    alert: float
    trigger_p3_mm: float | None = None

    def as_dict(self):
        return asdict(self)


def load_rules(study_dir=STUDY):
    """Frozen rules per index; the P3 trigger is omitted if second_trigger.json has not been produced yet."""
    final = json.loads((study_dir / 'results.json').read_text(encoding='utf-8'))['final_thresholds_all_years']
    trig_path = study_dir / 'second_trigger.json'
    trig = json.loads(trig_path.read_text(encoding='utf-8'))['final_frozen'] if trig_path.exists() else {}
    return {ix: Rule(ix, float(final[ix]['attention']), float(final[ix]['alert_pofd2pct']),
                     float(trig[ix]['P3_mm']) if ix in trig else None)
            for ix in INDICES if ix in final}


def classify(index_values, p3, rule, use_trigger=True):
    """Level per row: -1 no data, 0 Normal, 1 Watch, 2 Warning."""
    v = np.asarray(index_values, float)
    level = np.where(v >= rule.alert, WARNING, np.where(v >= rule.attention, WATCH, NORMAL))
    if use_trigger and rule.trigger_p3_mm is not None:
        rain = np.asarray(p3, float)
        level = np.where((level == NORMAL) & (rain >= rule.trigger_p3_mm), WATCH, level)
    return np.where(np.isnan(v), NO_DATA, level)


def run_rules(meta):
    """Rules stored in a forecast run's metadata: {'EDI': {...}, 'API': {...}}.

    Runs made before this module existed stored 'thresholds' (EDI) and 'thresholds_api' instead."""
    if 'rules' in meta:
        return meta['rules']
    old = {'EDI': {**meta['thresholds'], 'index': 'EDI'}}
    if meta.get('thresholds_api'):
        old['API'] = {**meta['thresholds_api'], 'index': 'API'}
    return old
