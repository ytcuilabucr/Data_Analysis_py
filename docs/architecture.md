# Architecture

- `rogi/core.py`: datasets, text imports, fits, and CSV exports without a GUI dependency.
- `rogi/project.py` and `rogi/hdf5.py`: validation, format dispatch, JSON compatibility, and atomic HDF5 persistence.
- `rogi/ui.py`: MainWindow composition and compatibility methods.
- `rogi/plot_windows.py`: line plot (with its plot controls) and 2D map as floatable docks in a nested main window above the data table; tab-like current-view tracking, layout persistence in QSettings.
- `rogi/browser_panel.py`, `rogi/plot_controls_panel.py`, `rogi/fitting_panel.py`: dataset browser, channel/plot controls, fitting controls and FitWorker.
- `rogi/dialogs.py`: import and metadata dialogs.
- `rogi/project_actions.py`, `rogi/dataset_actions.py`, `rogi/table_actions.py`, `rogi/plot_actions.py`: window workflows.
- `rogi/operations.py` and `rogi/canvas.py`: worker adapter, shared editing lock, detached Agg rendering.
- `tests/`: numerical, persistence, failure-path and offscreen desktop checks.

This version targets moderate in-memory datasets. Import parsing, folder conversion, project loading/saving, image preparation, and main line/image display rendering run in workers with a busy indicator and the same editing lock as fitting. Display rendering uses a detached Agg figure; Qt widgets stay on the UI thread. Read/import operations can discard cancelled results, and conversion checks cancellation between files and before saving. Atomic saves are not interrupted. See [measured timings, UI timer gaps, and memory use](performance.md). For outstanding functionality and validation, see [limitations](limitations.md). Project files preserve full source text and can be larger than the original data. Plot zoom, pan, history navigation, and applied presentation changes mark the project as modified and participate in save prompts.
