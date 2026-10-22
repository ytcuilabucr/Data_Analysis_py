Rogi development progress report — October 14, 2026

Rogi 0.1.0 is a working local desktop application for importing numeric data, inspecting and editing derived copies, plotting multiple datasets, and saving portable projects. The current interface prioritizes data inspection and plotting. Fitting is available as an optional view and is hidden by default.

**Completed UI features**

| Area | Current behavior |
| --- | --- |
| Workspace | Resizable dataset browser on the left, plot and data table in the center, and channel/plot controls on the right. |
| Import | CSV, TSV, and text-file selection; comma, tab, or semicolon delimiter; optional header row; first 100 rows preview; numeric column selection; full import validation. |
| Dataset browser | Select datasets and check/uncheck visibility to overlay multiple datasets. Raw and derived datasets are labeled. |
| Data table | Imported raw data is read-only. Editable copy creates a derived dataset with editable numeric cells, parent provenance, and edit history. Blank cells represent missing values. |
| Channel selection | Separate X and Y channel dropdowns for the selected dataset. Channel choices are saved in projects. |
| Plot controls | Line/scatter style, custom plot title and axis labels, automatic channel labels, legends, grid, and Matplotlib pan, zoom, home, and navigation history. |
| Dataset information | Row count, channel count, missing-cell count, and raw/editable revision status. |
| Project actions | Open, Save, and Save as; HDF5 is the default format, with JSON compatibility. Unsaved data/settings changes prompt before closing or replacing a project. |
| Export | Dataset CSV and plot PNG/SVG. Plot export reflects the currently visible panels. |
| Optional fitting | View → Show fitting reveals Linear/Gaussian models, numeric or draggable fit ranges, explicit missing-value exclusion, fit results, fit curves, residuals, and fit CSV export. Fits run in a background worker. |

**Latest change: simplified default interface**

Fitting controls, fit export, fitted curves, and the residual panel are hidden at startup. The main plot uses the available plotting area. View → Show fitting restores the fitting interface; hiding it also disables drag-range selection. Existing fit results remain stored in the dataset and project. This visibility choice currently applies to the running window; it is not saved as a preference.

**Storage and implementation**

The application separates numerical/data operations, project validation, HDF5 storage, and Qt presentation. HDF5 projects retain numeric arrays, source text, column names, raw/derived relationships, edit history, completed fit results, plot labels, channel/style/visibility choices, and main-axis limits. Numeric arrays use compression; saves use temporary-file replacement. Existing JSON projects can be reopened and saved as HDF5.

**Installed environment and packages**

The following inventory was read directly from the project's `.venv`; it describes installed versions, not minimum requirements. No packages were installed or changed while preparing this report.

Environment: macOS, arm64, Python 3.13.16. Local editable package: `rogi-analysis==0.1.0`.

| Main package | Installed version | Purpose |
| --- | --- | --- |
| PySide6 | 6.12.0 | Desktop windows, controls, dialogs, tables, and worker threads |
| NumPy | 2.5.4 | Numeric arrays and data operations |
| SciPy | 1.18.1 | Numerical optimization for fitting |
| Matplotlib | 3.11.2 | Embedded plots, navigation, and image export |
| h5py | 3.16.0 | HDF5 project storage |
| pytest | 9.1.1 | Automated tests |

Complete installed inventory:

| Package | Version |
| --- | --- |
| contourpy | 1.4.0 |
| cycler | 0.12.1 |
| fonttools | 4.67.0 |
| h5py | 3.16.0 |
| iniconfig | 2.3.1 |
| kiwisolver | 1.5.1 |
| matplotlib | 3.11.2 |
| numpy | 2.5.4 |
| packaging | 26.3 |
| pillow | 12.3.0 |
| pip | 26.2.1 |
| pluggy | 1.6.0 |
| Pygments | 2.21.0 |
| pyparsing | 3.3.3 |
| PySide6 | 6.12.0 |
| PySide6_Addons | 6.12.0 |
| PySide6_Essentials | 6.12.0 |
| PySide6_Pdf | 6.12.0.140 |
| PySide6_WebEngine | 6.12.0.140 |
| pytest | 9.1.1 |
| python-dateutil | 2.9.0.post0 |
| rogi-analysis | 0.1.0 |
| rogi-analysis | 0.1.0 |
| scipy | 1.18.1 |
| shiboken6 | 6.12.0 |
| six | 1.17.0 |

**Validation status**

The latest test run completed with **35 passed** and 16 upstream Matplotlib/Qt deprecation warnings. Coverage includes numeric fits and failure cases, imports, raw/derived behavior, project round trips, HDF5 persistence, CSV/image exports, application entry points, channel selection, and offscreen UI workflows.

An additional offscreen smoke check verified that fitting is initially hidden, the View toggle restores and hides the relevant controls and curves, the main plot switches layout, hiding fitting disables range selection, and saved fit data remains intact. The latest visibility change has not received a full native manual click-through. The older PLAN.md and VALIDATION.md documents still report the earlier 22-test checkpoint; this report records the more recent result.

**Remaining work and limitations**

- Validate native dialogs, keyboard editing, pan/zoom, and image appearance with representative user datasets.
- Large-file responsiveness measured and addressed (2026-10-21): import parsing, conversion, project I/O, image preparation, and detached Agg main line/image display rendering now use workers. Editing is locked during work; eligible operations support cooperative cancellation. Projects still load into memory and are rewritten atomically on save. The offscreen 10 ms timer benchmark and before/after timing/memory results are in [docs/performance.md](docs/performance.md).
- Undo/redo, fit cancellation, multiple plot windows, advanced signal processing, and arbitrary third-party HDF5 layouts are not implemented.
- Windows/Linux native behavior and agreement with Igor Pro have not been established.
- Zoom-only changes do not trigger an unsaved-change warning; explicitly saving preserves the current view.
