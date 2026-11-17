"""Build example-data/AOTF_power.h5: the 30 raw AOTF voltage scans plus 30 power results.

Each result is a Rogi photodiode_power analysis (Newport 2107) whose dark_v is that
scan's median voltage over the off-peak band 860-900 nm. The receiver was on gain
setting 1x1, which the 2107 manual (Rev A, p. 9) gives as 626 V/A.

Usage: .venv/bin/python outputs/aotf_power/build_project.py
"""
from pathlib import Path
import numpy as np
from rogi.analysis import analyze
from rogi.project import load_project, save_project

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'example-data' / 'AOTF.h5'
TARGET = ROOT / 'example-data' / 'AOTF_power.h5'
BASELINE_NM = (860., 900.)
GAIN_SETTING = 1.0

datasets, settings = load_project(SOURCE)
raw = [d for d in datasets if d.raw]
assert len(raw) == 30

results = []
for d in raw:
    wl, v = d.values[:, d.xcol], d.values[:, d.ycol]
    off = (wl >= BASELINE_NM[0]) & (wl <= BASELINE_NM[1])
    dark_v = float(np.median(v[off]))
    step = dict(operation='photodiode_power',
                parameters=dict(detector='newport_2107', gain_setting=GAIN_SETTING, dark_v=dark_v))
    result = analyze(d, [step], name=f'{d.name} (power)')
    result.group, result.group_path = d.group, list(d.group_path)
    result.comments = (f'Dark offset {dark_v * 1e3:.4f} mV = median of {off.sum()} points at '
                       f'{BASELINE_NM[0]:g}-{BASELINE_NM[1]:g} nm (off-peak). Gain setting 1×1 = 626 V/A (2107 manual Rev A).')
    results.append(result)

settings = dict(settings, selected_dataset_id=raw[0].id, saved_views={})
save_project(TARGET, raw + results, settings)
print(f'wrote {len(raw)} raw + {len(results)} derived to {TARGET}')
