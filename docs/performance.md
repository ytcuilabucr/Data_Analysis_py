# Measured desktop performance

Measured on **2026-10-21**, before changing execution paths and again after the
changes. Baseline code: `b538da9`. These are actual local measurements, not
estimates. All final measured UI timer gaps are below the **200 ms** criterion.
Raw observations: [before](performance-before.json), [after](performance-after.json).

## Environment and reproduction

- Apple M5, 32 GiB RAM; macOS 26.6, arm64.
- Python 3.13.16, Clang 21.0.0, project `.venv`.
- Qt offscreen platform; a precise QTimer ticks every 10 ms.
- No CPU affinity/frequency pinning or filesystem-cache clearing. One observation
  per operation/input in a fresh subprocess. These are desktop regression
  measurements, not statistical latency percentiles or cold-disk throughput.

| Package | Version |
|---|---|
| numpy | 2.5.4 |
| scipy | 1.18.1 |
| h5py | 3.16.0 |
| matplotlib | 3.11.2 |
| PySide6 | 6.12.0 |
| pytest | 9.1.1 |

```sh
QT_QPA_PLATFORM=offscreen .venv/bin/python scripts/benchmark.py --output /tmp/performance.json
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q
# Optional focused run:
QT_QPA_PLATFORM=offscreen .venv/bin/python scripts/benchmark.py --only synthetic
```

The benchmark generates a deterministic **1024 × 1024, eight-channel Nanonis SXM
scan** (32 MiB binary payload; 11 numeric columns after bundling) and its HDF5
project in a temporary directory. It also uses all six `example-data/260813*.h5`
projects (approximately 17–30 MB). These local instrument files are not tracked
in Git. HDF5 inputs are projects, not raw import formats: the import case uses
the largest SPM file in their original `example-data/260813` source tree, and the
conversion case processes that entire tree. Synthetic import/conversion use the
generated SXM scan. No original inputs are overwritten.

Wall time measures the operation callback with `perf_counter`. Open includes
validation, legacy consolidation and widget population; first plot preloads data
outside timing, then populates the browser and forces a line-canvas draw. Import
includes scan reading, preview construction and channel bundling; insertion into
the main plot is measured separately. Conversion excludes reopening the result
(to avoid counting open twice); the responsiveness test also exercises the real
GUI conversion action including its automatic open. Save preloads the datasets outside timing and uses the window’s default
presentation settings; it includes validation, encoding, fsync and atomic replace. File pickers/user think time are excluded.

The timer runs on the **GUI thread**, starts before the callback and continues
for 100 ms after it returns to catch deferred draws. A nested worker event loop
keeps the same timer running during operations. The callback starts only once
any initial pending render has released the editing lock. Widgets are built
and canvases explicitly rendered offscreen; no human interaction is simulated.
Peak RSS uses `resource.getrusage(RUSAGE_SELF).ru_maxrss` in each isolated child,
converted to MiB. It includes imports, preloaded inputs and transient copies,
not just incremental allocations during the timed callback.

## Before / after

Seconds are callback wall time; gap is the longest observed interval between
10 ms GUI timer ticks. RSS is peak resident memory, in MiB.

| Input | Operation | Before s | After s | Before gap ms | After gap ms | Before RSS MiB | After RSS MiB |
|---|---|---:|---:|---:|---:|---:|---:|
| `260813.files.rogi.h5` | open | 6.845 | 0.481 | 6867.9 | 53.0 | 762.2 | 726.5 |
| `260813.files.rogi.h5` | save | 0.643 | 0.644 | 643.8 | 18.0 | 415.8 | 417.0 |
| `260813.files.rogi.h5` | first_plot | 0.148 | 0.088 | 167.7 | 31.1 | 544.2 | 546.9 |
| `260813.rogi.h5` | open | 7.580 | 1.102 | 7603.8 | 41.0 | 863.7 | 850.4 |
| `260813.rogi.h5` | save | 1.494 | 1.468 | 1495.0 | 18.0 | 780.6 | 779.7 |
| `260813.rogi.h5` | first_plot | 0.536 | 0.066 | 561.8 | 25.2 | 775.4 | 775.5 |
| `260813A.h5` | open | 6.878 | 0.483 | 6907.7 | 38.8 | 759.4 | 726.2 |
| `260813A.h5` | save | 0.645 | 0.643 | 644.8 | 16.8 | 416.6 | 417.5 |
| `260813A.h5` | first_plot | 0.151 | 0.090 | 170.6 | 35.5 | 543.9 | 548.6 |
| `260813B.h5` | open | 6.842 | 0.487 | 6864.9 | 44.2 | 759.3 | 725.9 |
| `260813B.h5` | save | 0.645 | 0.641 | 645.1 | 16.8 | 416.7 | 417.1 |
| `260813B.h5` | first_plot | 0.151 | 0.090 | 169.6 | 32.5 | 544.5 | 546.7 |
| `260813C.h5` | open | 6.910 | 0.478 | 6961.2 | 51.9 | 800.4 | 729.5 |
| `260813C.h5` | save | 0.650 | 0.641 | 651.3 | 19.5 | 415.9 | 416.4 |
| `260813C.h5` | first_plot | 0.134 | 0.075 | 151.0 | 29.9 | 543.2 | 546.2 |
| `260813D.h5` | open | 6.945 | 0.497 | 7008.9 | 45.8 | 761.2 | 731.2 |
| `260813D.h5` | save | 0.649 | 0.652 | 650.6 | 18.0 | 416.0 | 417.0 |
| `260813D.h5` | first_plot | 0.149 | 0.089 | 169.1 | 31.5 | 543.9 | 546.1 |
| `synthetic.h5` | open | 1.524 | 1.113 | 2165.6 | 119.9 | 1068.8 | 1103.5 |
| `synthetic.h5` | save | 0.540 | 0.540 | 548.0 | 12.1 | 442.9 | 444.9 |
| `synthetic.h5` | first_plot | 0.674 | 0.691 | 1265.7 | 36.4 | 776.5 | 874.2 |
| `08151451.0_00001.spm` | import | 0.019 | 0.018 | 26.5 | 12.1 | 222.4 | 224.2 |
| `260813` | conversion | 1.630 | 1.611 | 1629.7 | 36.5 | 376.9 | 378.6 |
| `large.sxm` | import | 0.193 | 0.185 | 192.7 | 12.0 | 821.3 | 821.7 |
| `synthetic` | conversion | 0.738 | 0.716 | 738.8 | 12.1 | 844.1 | 846.3 |

## What the measurements changed

- Project loading previously rebuilt selection, image context and plots after
  **every added dataset**. Loading/validation/consolidation now run in a worker,
  and the loaded dataset collection is attached with one history-view refresh.
- Project save and folder conversion run in `OperationWorker`, using the same
  codecs and atomic fsync/replace writers. No data formats or compression
  settings changed. Existing raw arrays remain read-only.
- Import parsing/bundling runs in a worker. Profiling the synthetic open
  identified repeated million-pixel raster validation for cursor profiles. Image channel views are reused rather than duplicated for the current
  file. Four million-pixel uniqueness checks measured 407 ms with
  `np.unique` versus 10 ms counting bounded pixel hits; raster validation now
  uses the equivalent count check, tested against shuffled and duplicate grids.
- A second full benchmark exposed a remaining legacy first-plot pause. Profiling
  found metadata search-text construction for 488 datasets, twice per dataset,
  even with empty filters. Empty filters now skip that construction, and active
  metadata filtering reuses cached search text. Dataset ID lookup also reads the Qt item
  once rather than on every iteration of its dataset lookup.

Workers share the fit editing lock (central widgets, project/edit/view actions,
clipboard and undo/redo), show a busy indicator, and prevent closing while work
is running. A local Qt event loop preserves existing synchronous method return
values and exceptions while dispatching timer/paint events. Read/import Cancel
requests discard results when the worker returns; conversion checks cancellation
between files and immediately before saving; its Cancel button is removed at
the atomic-write boundary. Native reads cannot be forcibly
interrupted. Once atomic writing begins it finishes; saves have no Cancel button.
Errors still reach the existing GUI error handlers. No worker is terminated.

## Revision 2026-10-22: interactive paths back on the GUI thread

The first version also routed plot rendering, browser filtering and image
channel/raster/profile preparation through `run_operation`. Those run on almost
every click or keystroke, and each call took the editing lock: the whole window
was disabled and re-enabled (6 lock toggles per dataset click, 6 per search
keystroke), which flashed the UI and swallowed input during a nested event loop.
The benchmark did not catch this because it measured timer gaps, not lock churn.

Those paths are synchronous again; workers are kept for file reads, imports,
conversion and saves. A test now asserts that dataset clicks and filtering never
toggle the lock. The underlying costs were reduced instead: legend placement
`'best'` falls back to the upper right above 100 000 plotted points (it scanned
every point, ~0.5 s per draw on the synthetic scan), metadata search text is
cached per dataset, and opening a project redraws once instead of six times.
A dataset click with redraw on the synthetic scan measures ~85 ms. Opening the
synthetic scan after conversion still blocked the GUI thread for ~240 ms once,
above the 200 ms criterion.

Image channel views, raster/contrast preparation and cursor profiles (~90 ms of
that open) now run through `run_in_background`: a worker with a local event
loop that takes no editing lock and shows no dialog, so it cannot flash the
window. Calls back into the image viewer that arrive during the wait are
deferred and replayed (latest per method). All canvas draws are held during the
wait and issued once afterwards; without this, every wait rendered the queued
plot and the next change rendered it again (55 draws instead of 2 in one test).
The conversion-and-open gap now measures ~120 ms; the remainder is mostly
Matplotlib drawing the million-pixel image on the GUI thread.

## Verification and limits

The suite has **327 tests**, all passing. Offscreen tests bound
real synthetic import, conversion-and-open, save, open and redraw timer gaps below 200 ms; a
local legacy-project test covers first plot and metadata search. Additional
checks compare imported/loaded/saved values and metadata to synchronous paths,
check raw immutability, compare rendered RGBA pixels with the original synchronous
Qt/Agg path at 1× and 2× pixel ratios, verify GUI-thread draw callbacks, exercise
cancellation and editing/close locks, and inject atomic
replace failures for **both HDF5 and JSON** while checking that the original file
and dirty state survive and temporary files are removed.

Responsiveness is the primary improvement: worker execution does not make every
operation faster. Projects remain fully in memory.
The measured bound is a regression criterion on these workloads and this machine,
not a guarantee for arbitrary input sizes or overloaded hardware. Qt widget and
artist assembly still run on the GUI thread; other analysis dialogs and plot-file
export are outside this benchmark. The core Python I/O functions remain
synchronous for scripts; the desktop calls them through the worker adapter.
