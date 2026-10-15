# Rogi: first desktop workflow

A local Python scientific analysis application, developed in PyCharm. Target moderate numeric CSV/TSV datasets that fit in memory. UTF-8 input, decimal point numbers, unweighted fits, one plot with multiple overlays, and one active fit per dataset are initial assumptions.

Workflow: preview/import selected columns → inspect immutable raw data → optionally make and edit a derived copy → choose X/Y and line/scatter overlays → set inclusive numerical range or drag a range selector → fit linear/Gaussian → inspect parameters and residuals → export → save/reopen.

Architecture: `core.py` owns numeric datasets, imports, fit models, and CSV exports without Qt; `project.py` owns versioned JSON persistence and validation; `ui.py` owns Qt widgets and Matplotlib presentation. Fitting runs in a worker thread. JSON stores all data, provenance, fits, and plot settings, with atomic replacement on save. No pickle or external data references required to reopen.

Raw source text, including unselected columns, is retained even when only a subset is parsed as numeric data. Derived copies record edits and invalidate their fit. Missing cells are NaN in memory and null in project JSON. Invalid numeric tokens and malformed rows fail import with row/column context. No implicit sorting or mutation of stored data.

Deferred: scripting, plugins, signal processing, specialized formats, weighted fits, multiple plot windows, huge/out-of-core tables, undo/redo, packaging into installers.
