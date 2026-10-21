# Validation — 2026-10-14

## Full UI and combined-workflow regression — 2026-10-21

Current full-suite result: **292 passed in 30.76 seconds**, with no failures or
skips reported. Command:
`QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q --junitxml=/tmp/rogi-test-results.xml`.
The original 288 tests passed before adding four integration cases in
`tests/test_combined_workflows.py`; those four also passed independently.

The added workflows run against both HDF5 and JSON projects:

- Text import preview → editable copy → rectangular clipboard paste → undo/redo
  → analysis dialog → region statistics → threaded linear fit → multiple panels
  → named-view restore → save/reopen → data, fit, and SVG exports. Checks include
  independently expected signal values, slope/intercept, source revision,
  preserved analysis/fit records, raw immutability, and exported CSV contents.
- Scan image → transpose and cursor placement → named view → profile extraction
  → analysis dialog → derived-cell edit and undo/redo → restore image view →
  save/reopen. Checks include profile values, chained parent IDs, extraction and
  analysis provenance, unchanged source data, and restored cursor/transpose state.

The existing suite additionally exercises grouping and annotations, metadata and
instrument imports, folder conversion, missing-data/error handling, multi-spectrum
analysis, spectrum maps, statistics, plotting, clipboard shortcuts, history,
saved views, and persistence. These are automated numerical and offscreen Qt
checks, with native file/modal dialogs substituted where needed. They do not
establish exhaustive menu/state coverage, native macOS/Windows dialog behavior,
external clipboard interoperability, or large-file performance. No application
code changes were needed for this run. `git diff --check` passed.

Environment: macOS ARM64, Python 3.13.16. Exact installed packages are recorded in requirements-tested.txt.

Command: `.venv/bin/python -m pytest -q`

Result: **22 passed**. Eight upstream Matplotlib/Qt deprecation warnings concern `AA_UseHighDpiPixmaps`; no test failures.

Covered:
- Linear recovery with seeded noise, covariance comparison against NumPy polyfit, and residual identity.
- Positive/negative Gaussian peak recovery and noisy Gaussian standard errors.
- Inclusive fit range, explicit missing-row exclusion, invalid bounds/insufficient data/constant Gaussian failure.
- CSV/TSV, headerless input, selected numeric columns, preserved source text, empty/header-only/malformed/nonnumeric/infinite imports.
- Immutable raw arrays, independent derived edits, edit history, and fit invalidation.
- Project save/reopen with missing values, provenance, fit outputs, plot settings; unknown version and malformed axis/parameter/row/column rejection; preservation of previous file on serialization failure.
- Data CSV reimport and fit CSV output.
- Offscreen Qt integration: import preview, editable copy, cell edit, threaded fit, overlay/residual rendering, PNG/SVG generation, save and GUI project reopening.

Native check: launched the macOS Qt window with the sample Gaussian dataset and fitted residuals, captured the window, inspected the layout, and closed it through the event loop. No native startup error. This was an automated launch/render check, not a complete manual click-through.

Still manual: native file dialogs, mouse range handles, toolbar pan/zoom, platform-specific keyboard behavior, your actual input formats and scales, Igor Pro comparison, Windows/Linux testing, large-file performance. Numerical fit convergence does not validate the scientific model.

## Dataset organization validation

The organization update passes the full 54-test suite using
`QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q`.
Added coverage includes JSON/HDF5 organization round trips and legacy files without
group metadata; stable IDs, parent links, source text, raw read-only arrays, missing
values, edits and fits; selection versus visibility; filtered bulk actions; group
assignment and rename cancellation; removal cancellation, retained descendants,
empty projects, and survivor-to-browser mapping. An offscreen window rendering was
also inspected. Matplotlib emits existing Qt high-DPI deprecation warnings.

Native Cmd/Ctrl/Shift mouse and keyboard behavior and confirmation-dialog appearance
still warrant manual checks on each supported platform. Groups are flat labels;
selection and search/filter state are temporary. Removal now supports session undo (see below).

## Plot presentation validation

The complete suite now passes 73 tests with
`QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q`.
New checks cover display-only logarithmic masking (including all-invalid data),
preserved raw arrays and fits, atomic axis-input validation, automatic rescaling,
manual zoom preservation, toolbar history, dirty tracking, coordinate readouts,
JSON/HDF5 presentation round trips, legacy defaults, and malformed presentation
metadata. Only existing Matplotlib/Qt high-DPI deprecation warnings remain.
The expanded controls were rendered offscreen and visually inspected; the right
panel scrolls when fitting and plot controls exceed the available height.
Native mouse pan/zoom, color dialogs, and cursor performance on large datasets
still warrant platform-specific manual checks.

## Region statistics validation

Added nine tests covering inclusive/unsorted/duplicate observations, missing-value
counts, sample/population formulas, empty and singleton regions, invalid bounds,
raw immutability, edit refresh, context changes, logarithmic display independence,
mutually exclusive drag tools, actual Matplotlib mouse events for both region
modes, and stable automatic/manual axis views. The statistics panel and highlighted
region were rendered and visually inspected. Results are temporary and apply to
one active Y channel; native mouse interactions still warrant manual checks.

Full-suite result after this update: **82 passed** using
`QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q`; only existing
Matplotlib/Qt high-DPI deprecation warnings remain. `git diff --check` passes.

## Undo/redo validation

Full suite: **93 passed** with
`QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q`.
Added eleven tests cover cell values, missing values, revision/edit-history and fit
restoration, stale-fit rejection, discarded redo branches, raw immutability,
rename/group/bulk and checkbox visibility, implicit visibility after channel changes,
lineage and order restoration, save-point dirty tracking, unrelated unsaved views,
JSON/HDF5 reopen behavior, failed saves/opens, standard shortcut events, and the
background-fit undo lock. Existing Matplotlib/Qt high-DPI deprecation warnings
remain. `git diff --check` passes.

History is session-only and retains removed data/fit snapshots in memory. Plot
presentation and fit execution are tracked as changes but are not undo commands.
Platform-specific native menu/shortcut behavior still warrants manual checks.

## Shortcuts and rectangular clipboard validation

Full suite: **114 passed** with
`QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q`.
Added 21 cases cover copy with headers/missing values, TSV/CSV/header-aware paste,
numeric-looking headers, copy from raw data and rejection of raw paste, complete
validation of malformed/irregular/out-of-bounds/nonfinite blocks, error locations,
no-op and invalid-paste history preservation, single-operation undo/redo with
revision/provenance and fit restoration, actual keyboard shortcut dispatch for
copy/paste/undo/redo/import/open/save/save-as, project persistence, and fitting locks.
Only existing Matplotlib/Qt high-DPI deprecation warnings remain; whitespace checks
pass. Native clipboard exchange with external spreadsheet apps remains a manual
cross-platform check. Block paste targets existing cells and does not grow datasets;
active text editors retain native text copy/paste behavior.

## Spectrum metadata validation

Full suite: **122 passed** with
`QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q`.
New coverage checks all 48 supplied Spectrum examples, repeated/empty sections,
duplicate keys, explicit versus unspecified units, source line provenance,
missing/invalid timestamps, exact source text including CRLF/BOM, selected-column
imports, immutable raw values, independent derived acquisition snapshots,
JSON/HDF5 round trips, legacy defaults, malformed metadata rejection,
metadata-aware search, and undoable grouping that skips missing fields.
Instrument metadata and timestamp tabs were rendered offscreen and visually
inspected. Only existing Matplotlib/Qt high-DPI deprecation warnings remain.

No timezone, numeric timestamp epoch, or units absent from the source are inferred.
Older projects are readable but are not silently reparsed. Search/viewer data is
in memory; very large timestamp streams may affect responsiveness. Native dialog
behavior remains a platform-specific manual check.

## Dataset checkbox/channel regression

Fixed history refresh replacing browser items during a checkbox mouse event, which
could clear the active dataset and X/Y controls. Nonstructural changes now update
rows in place. Added an actual mouse-click regression across three datasets,
including initially hidden runs, followed by channel changes. Full suite:
**123 passed**; `git diff --check` passes.

## Channel changes and default overlays

Changing a hidden dataset's channels now switches visibility to that dataset alone,
so the initially visible first dataset does not remain as an unintended overlay.
Already checked comparisons are preserved when changing a visible dataset's
channels. The visibility switch is one undoable action. Updated the Spectrum
integration test and added coverage for later datasets, unchanged first-dataset
channels, undo/redo, and explicit overlays. All 124 tests pass across the full run
and corrected focused regression rerun; whitespace checks pass.

## Active dataset after checking later files

Reproduced: check a later dataset, uncheck the first, change a channel. The old
checkbox path left the first dataset active, and Qt could clear the intended
selection at mouse-release completion. Checkbox clicks now have explicit event
handling; checking activates that dataset, while unchecking another does not
steal the channel target. The active name is shown under the axis controls.
An actual mouse-event regression repeats channel changes across later files and
asserts that the first remains hidden and unchanged. Full suite: **125 passed**;
whitespace checks pass. Native platform event handling remains a manual check.

## HDF5 lock-in channel audit

Compared every numeric source column in all 48 Spectrum files with the converted
HDF5 matrices. All match. The 38 files with lock-in measurements retain X, Y, R,
and Theta; Sweeptheta01 through Sweeptheta10 contain no lock-in data columns.
An offscreen integration test now checks both axis dropdowns for every file and
plots Lockin1_R for every file recording it.

The preparation helper now shares the app's DAT parser instead of the storage
experiment's first-column-dropping parser. Regression coverage includes numeric
Time, text Time in another position, repeated lock-in names, missing readings,
exact source text, immutable raw values, derived lineage, and overwrite refusal.
Also fixed detection of a BOM immediately before [Data]. Existing artifacts were
not regenerated. Full suite: **128 passed** with the existing Qt deprecation
warnings; `git diff --check` passes. No supplied lock-in loss was reproduced;
investigating another affected project requires its filename/source.
