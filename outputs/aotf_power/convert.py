"""Convert the 30 raw AOTF voltage scans to optical power.

P [mW] = (V - V_dark) * factor(lambda) / G, with factor = 1000 / R(lambda) from
outputs/aotf_response_factors.csv (Newport 2107 datasheet curve, mW/V at G = 1 V/A).
V_dark is each scan's median voltage over the off-peak band 860-900 nm.
The receiver label reads Output = G R Volts/mW, so 2107 gain setting 1 is 1000 V/A.

Usage: .venv/bin/python outputs/aotf_power/convert.py [gain_v_per_a]   (default 1000)
"""
import sys
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from rogi.project import load_project

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
BASELINE_NM = (860., 900.)
GAIN = float(sys.argv[1]) if len(sys.argv) > 1 else 1000.0

factors = np.loadtxt(ROOT / 'outputs' / 'aotf_response_factors.csv', delimiter=',', skiprows=1)
wl, factor = factors[:, 0], factors[:, 2]
scans = [d for d in load_project(ROOT / 'example-data' / 'AOTF.h5')[0] if d.raw]
assert len(scans) == 30

names, dark, power = [], [], []
for d in scans:
    assert np.array_equal(d.values[:, 0], wl), d.name
    v = d.values[:, 1]
    off = (wl >= BASELINE_NM[0]) & (wl <= BASELINE_NM[1])
    v_dark = np.median(v[off])
    names.append(d.name.replace('YSL AOTF - 1.', ''))
    dark.append((v_dark, v[off].std(ddof=1)))
    power.append((v - v_dark) * factor / GAIN)
power = np.column_stack(power)

tag = f'G{GAIN:g}VperA'
header = 'wavelength_nm,' + ','.join(f'"{n}"' for n in names)
np.savetxt(OUT / f'aotf_power_mW_{tag}.csv', np.column_stack((wl, power)), delimiter=',',
           fmt='%.6g', header=header, comments='')
with open(OUT / 'dark_offsets.csv', 'w') as f:
    f.write('scan,dark_offset_mV,baseline_noise_std_mV,peak_wavelength_nm,peak_power_mW_' + tag + '\n')
    for n, (v0, s), p in zip(names, dark, power.T):
        i = np.argmax(p[1:]) + 1  # skip the 430 nm first point, which spikes in some scans
        f.write(f'"{n}",{v0 * 1e3:.4f},{s * 1e3:.4f},{wl[i]:.0f},{p[i]:.6g}\n')

rates = list(dict.fromkeys(n.split(',')[0] for n in names))
fig, axes = plt.subplots(2, 5, figsize=(18, 7), sharex=True)
for ax, rate in zip(axes.flat, rates):
    for n, p in zip(names, power.T):
        if n.split(',')[0] == rate:
            ax.plot(wl, p, label=n.split('= ')[-1])
    ax.axvspan(*BASELINE_NM, color='0.9')
    ax.axhline(0, color='0.5', lw=0.5)
    ax.set_title(rate)
    ax.legend(title='power', fontsize=8)
for ax in axes[1]:
    ax.set_xlabel('Wavelength (nm)')
for ax in axes[:, 0]:
    ax.set_ylabel(f'Power (mW, G = {GAIN:g} V/A)')
fig.suptitle('AOTF output power, dark offset from 860–900 nm (shaded) subtracted')
fig.tight_layout()
fig.savefig(OUT / f'aotf_power_{tag}.png', dpi=120)
print(f'wrote {len(names)} scans to {OUT}')
