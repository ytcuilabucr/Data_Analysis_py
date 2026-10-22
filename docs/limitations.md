# Validation scope and limitations

[Current test results](../VALIDATION.md) · [User guide](user-guide/index.md) ·
[Windows readiness checklist](windows-readiness.md)

## Native and cross-platform checks remain outstanding

Windows compatibility has not been verified. Windows/Linux native behavior and
agreement with Igor Pro have not been established. Current automated UI tests
run offscreen; native file/modal dialogs are substituted where needed. They do
not establish native dialog behavior, external clipboard interoperability, or
exhaustive menu/state coverage.

The historical macOS native launch/render check was not a complete manual
click-through. There was no new native desktop or native-dialog validation in
this documentation update. Native keyboard editing and shortcuts, mouse range
handles, pan/zoom, display scaling, and exported image appearance still need
platform-specific checks with representative user data.

Run the app in PyCharm and repeat the guide with your own CSV/TSV. Check native file dialogs, keyboard editing, pan/zoom, range handles, overlays with your units, and exported image appearance. Compare real fits with Igor Pro using identical model definitions, range, weighting, and missing-value treatment. Automated tests do not establish agreement with Igor Pro or cross-platform native UI behavior.

## Large-file validation is limited to the recorded workloads

Earlier validation entries explicitly did not establish large-file performance;
those statements remain in the [dated validation history](../VALIDATION.md).
The later [performance report](performance.md) records offscreen timing, timer
gaps and peak memory on the supplied projects and a synthetic multichannel scan.
Those results are not native large-file acceptance, a Windows result, or evidence
for arbitrary input sizes. No new performance benchmark was run for this
documentation-only update. Representative native large-file validation remains
outstanding. Very large timestamp streams may affect responsiveness.

Projects remain in memory: opening loads all datasets and saving rewrites the
project. There is no lazy/out-of-core editing, concurrent-writer support, or
arbitrary third-party HDF5 layout support. Full source text can make project
files larger than the source data. Detached rendering uses transient copies;
see the measured memory tradeoff in the performance report.

## Functional and scientific limits

There is no fit cancellation, multiple plot-window management, scripting, or
plugin system. Signal processing is limited to the documented
[analysis operations](user-guide/analysis-pipelines.md) and
[presets](user-guide/presets.md); advanced processing beyond them is not provided.
Instrument support is limited to the documented
[import formats](user-guide/import-and-projects.md). Bruker signals are raw ADC
counts; arbitrary layouts, force-volume files, and Nanonis grids are unsupported.
Keep original binary instrument files: their bytes are not embedded in projects.

Undo history is session-only and retains removed data and fit snapshots in memory.
Plot presentation and fit execution are not undo commands. Statistics are
temporary and apply to the active signal. Missing metadata units, timestamp
epochs and timezones are not inferred. Scientific assumptions and limits remain
with the relevant [fitting](user-guide/fitting.md),
[statistics](user-guide/statistics.md), and [map](user-guide/maps.md) workflows.
Numerical fit convergence does not validate the scientific model.

The [historical progress report](history/2026-10-14-progress.md) preserves earlier
limitations verbatim, including statements superseded by subsequent commits.
