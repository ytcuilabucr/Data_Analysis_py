# Rogi scientific analysis

A small local desktop application for importing, inspecting, plotting, fitting, and preserving numeric data. Python 3.11+; tested here with Python 3.13 on macOS ARM64. Uses PySide6 widgets, NumPy arrays, SciPy optimization, and Matplotlib Qt plots. No service, account, or database is required.

## Setup in PyCharm

1. Open this folder as a project.
2. Select the existing interpreter `.venv/bin/python` in Settings → Project → Python Interpreter. On Windows, use `.venv\Scripts\python.exe`.
3. If creating a fresh environment, run `python -m venv .venv`, activate it, then `python -m pip install -e ".[test]"`.
4. Create a Python run configuration with **Module name** `rogi`, the project folder as working directory, and the selected virtual environment. Run it.

From this folder on macOS/Linux:

```sh
.venv/bin/python -m rogi
.venv/bin/python -m pytest -q
```

Dependencies and supported version ranges are in `pyproject.toml`. `requirements-tested.txt` records the exact dependency versions installed during validation; it is a reproducibility snapshot, not a cross-platform lockfile. For that environment, install it before `pip install -e .`.

## Short user guide

1. Click **Import…** and try `examples/gaussian.csv` or `examples/linear.tsv`. Set delimiter and header mode, inspect the first 100 rows, and check at least two numeric columns. Full import validates every row. UTF-8/UTF-8 BOM files are supported; decimal commas and arbitrary text in selected columns are not.
2. Select a dataset in the left browser. Its table is below the plot. Imported data is read-only. Click **Editable copy** and double-click cells to change numbers; a blank cell means missing. Copies retain parent IDs and an edit history in the project. Editing invalidates the copy's previous fit.
3. Choose X/Y columns and Line or Scatter. Check/uncheck datasets in the browser to overlay/hide them. Enter title and axis labels, then press Enter or leave the field. The Matplotlib toolbar offers zoom, pan, home, and history. Lines follow original row order. Missing values appear as blank cells and gaps in lines; they remain in stored/exported data.
4. Choose a model and enter inclusive minimum/maximum X bounds. Alternatively, disable toolbar pan/zoom, check **Drag to select range**, and drag horizontally over the plot; drag the range handles to adjust. Numerical bounds are authoritative. The fit applies only to the selected dataset, even if others are overlaid.
5. If X/Y contain missing values, fitting stops unless **Exclude rows with missing X/Y** is checked. The fit reports the total missing X/Y rows excluded across the dataset (even when outside the range). Range selection separately excludes finite rows outside the bounds.
6. Click **Fit selected dataset**. Parameters, approximate standard errors, sample count, degrees of freedom, and RMSE appear on the right. Residuals (`observed - fitted`) appear below the main plot. Fits run in a background thread; editing is temporarily disabled for consistency. One latest fit is retained per dataset; make copies to retain competing fits. Changing X/Y preserves the fit's provenance and hides its curve if the columns differ.
7. **Export data…** writes selected dataset columns to CSV, leaving missing cells blank. **Export fit…** writes CSV sections for metadata, parameters/standard errors, and per-row predictions/residuals. Source row numbers in that export count data rows, excluding the header. **Export plot…** writes both plot and residual panels as PNG or SVG.
8. **Save / Save as…** writes a portable `.rogi.json` file. **Open project…** restores datasets, edit history, fit results, column/style/visibility choices, labels, and main plot axis limits. Imported source text (including unselected columns) is embedded so the original file is not needed. Pending, unexecuted range/model choices are temporary; completed fit ranges are retained. Closing/opening another project prompts to save modified data/results.

## Models and uncertainty assumptions

**Linear:** `y = slope*x + intercept`. Slope has Y/X units; intercept has Y units. Solved by ordinary least squares. More than two distinct X values are required so residual variance can be estimated.

**Gaussian:** `y = baseline + amplitude * exp(-0.5*((x-center)/sigma)^2)`. Baseline is the constant background, amplitude is peak height relative to baseline (negative peaks allowed), center is in X units, and sigma is positive width in X units. FWHM = `2*sqrt(2*ln(2))*sigma`. More than four distinct X values are required. Initial guesses use median background, strongest deviation, and range/6 width. Select a single peak with both tails; local optimization can fail or converge to an unsuitable peak. Inspect residuals and physical plausibility; convergence alone is not validation.

Both models minimize unweighted squared Y residuals. X is treated as exact. Errors are assumed independent with equal unknown variance; residual variance is estimated as SSE/(N-p). Reported ± values are approximate one-standard-deviation parameter standard errors from covariance, not confidence intervals or measurement uncertainties. Gaussian covariance is a local linear approximation. Unavailable/nonfinite or severely ill-conditioned covariance is reported explicitly. Exact synthetic fits can have zero estimated errors; that does not establish zero experimental uncertainty. No weighting, X-error treatment, robust loss, or parameter constraints beyond positive Gaussian sigma are provided yet.

## Architecture and limits

- `rogi/core.py`: datasets, imports, fits, CSV exports; no GUI dependency.
- `rogi/project.py`: versioned JSON, validation, atomic save replacement.
- `rogi/ui.py`: desktop widgets, plot interactions, background fit worker.
- `tests/`: synthetic numerical checks, invalid imports/fits, project round trips, offscreen desktop integration.

This version targets moderate in-memory datasets. Import, project JSON serialization, and plot drawing run on the UI thread and can pause with large files; only fitting is threaded. There is no undo, fit cancellation, multiple plot-window management, scripting, plugins, advanced signal processing, or specialized format support yet. Project files preserve full source text and can be larger than the original data. Unsaved plot zoom alone does not trigger a close warning; explicitly save after adjusting a view you want to retain.

## Manual acceptance check

Run the app in PyCharm and repeat the guide with your own CSV/TSV. Check native file dialogs, keyboard editing, pan/zoom, range handles, overlays with your units, and exported image appearance. Compare real fits with Igor Pro using identical model definitions, range, weighting, and missing-value treatment. Automated tests do not establish agreement with Igor Pro or cross-platform native UI behavior.
