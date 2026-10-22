# Current-status roadmap

Status follows the committed implementation; test evidence and environment belong
in [VALIDATION.md](VALIDATION.md), not a duplicated test count here.

## Done

- Import, immutable raw/derived data, fitting, exports and portable HDF5/JSON projects.
- Metadata grouping, clipboard, undo/redo, plot controls, statistics and saved views.
- Images and profiles, spectrum maps, analysis pipelines and reusable presets.
- MainWindow decomposition into panels, dialogs and workflow modules, preserving compatibility methods.
- Measured offscreen responsiveness improvements, worker execution and regression tests;
  see [performance evidence and its scope](docs/performance.md).
- Documentation separated into a quick start, user guide, validation record and Git changelog.

## In progress

- Validation coverage: automated/offscreen evidence is recorded, while native manual
  acceptance and broader input-scale coverage remain open. This does not imply a
  native or cross-platform validation run is currently underway.

## Deferred / not yet verified

- Native dialogs, external clipboard exchange, platform-specific shortcuts and mouse interaction.
- Native large-file acceptance, Windows/Linux validation and Igor Pro comparison.
- Windows packaging and clean-machine release acceptance; see the [readiness checklist](docs/windows-readiness.md).
- Out-of-core editing, concurrent writers, arbitrary HDF5 layouts, fit cancellation,
  multiple plot windows, scripting/plugins and processing beyond the documented operations.

See [limitations](docs/limitations.md) for the full scope and
[CHANGELOG.md](CHANGELOG.md) for completed development history.
