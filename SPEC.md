# Rogi: first desktop workflow

A local Python scientific analysis application, developed in PyCharm. Target moderate numeric CSV/TSV datasets that fit in memory. UTF-8 input, decimal point numbers, unweighted fits, one plot with multiple overlays, and one active fit per dataset are initial assumptions.

Workflow: preview/import selected columns → inspect immutable raw data → optionally make and edit a derived copy → choose X/Y and line/scatter overlays → set inclusive numerical range or drag a range selector → fit linear/Gaussian → inspect parameters and residuals → export → save/reopen.

Architecture: `core.py` owns numeric datasets, imports, fit models, and CSV exports without Qt; `project.py` owns versioned JSON persistence and validation; `ui.py` owns Qt widgets and Matplotlib presentation. Fitting runs in a worker thread. JSON stores all data, provenance, fits, and plot settings, with atomic replacement on save. No pickle or external data references required to reopen.

Raw source text, including unselected columns, is retained even when only a subset is parsed as numeric data. Derived copies record edits and invalidate their fit. Missing cells are NaN in memory and null in project JSON. Invalid numeric tokens and malformed rows fail import with row/column context. No implicit sorting or mutation of stored data.

Deferred: scripting, plugins, signal processing, specialized formats, weighted fits, multiple plot windows, huge/out-of-core tables, packaging into installers.


Dataset organization: the browser supports case-insensitive name/group/source search, flat group membership, rename, extended row selection, and bulk visibility. Row selection is independent of plot visibility. Organization is presentation metadata; IDs, raw values, source text, edits, and fits stay intact. Removal refuses to orphan retained derived copies and requires confirmation. Optional group metadata is persisted in both project formats; older files default to ungrouped. Search/filter/selection state is temporary.


Plot presentation: optional advanced controls provide linear/logarithmic scales, automatic or explicit limits, dataset colors/markers, legend placement and a coordinate cursor. Nonpositive logarithmic coordinates are masked only in display copies, with visible diagnostics; residual Y remains linear. Manual views survive unrelated redraws. Navigation changes are tracked as unsaved changes, and all applied presentation settings persist in JSON/HDF5 with legacy defaults.

Region statistics: optional X-interval or rectangular plot selection summarizes
stored Y observations of the active dataset using inclusive numeric bounds.
Missing observations are explicitly counted and excluded. Sample/population
standard deviation and variance are selectable; results include count, extrema,
mean, median, SEM, sum, RMS and quartiles. Statistics are temporary, refresh after
edits, clear on dataset/channel changes, and never modify data or saved fits.


Undo/redo: session commands cover editable-cell changes and dataset rename,
grouping, visibility, removal, import and copy creation. Bulk changes are atomic
history steps. Cell commands restore revisions/edit provenance and only matching
fit snapshots. Raw arrays are never unlocked. Save marks a clean history position;
opening clears the stack. Other unsaved view/fit changes remain independently dirty.


Table clipboard: standard project and table shortcuts are exposed by menus.
Rectangular copies include column headers and blank missing values. Numeric
TSV/CSV pastes are validated in full before mutation, target existing cells only,
and reject raw datasets. Each paste is one undo step with per-cell provenance;
invalid/no-op pastes do not change values, fits, or history.


Spectrum metadata: section/key occurrences, lexical values, explicit units and source
line provenance accompany typed values. Original Time/Time_Timestamp streams are
row-aligned acquisition snapshots with raw and parsed values; no timezone, epoch,
unit inference or filename-derived fields. Optional metadata round-trips in both
formats and defaults empty in legacy projects. A read-only viewer, metadata search
and undoable exact-field grouping expose the data.
