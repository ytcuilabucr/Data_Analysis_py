# Rogi scientific analysis

A small local desktop application for importing, inspecting, plotting, fitting, and preserving numeric data. Python 3.11+; tested here with Python 3.13 on macOS ARM64. Uses PySide6 widgets, NumPy arrays, SciPy optimization, Matplotlib Qt plots, and h5py for HDF5 storage. No service, account, or database is required.

## Setup in PyCharm

1. Open this folder as a project.
2. Select the existing interpreter `.venv/bin/python` in Settings → Project → Python Interpreter. On Windows, use `.venv\Scripts\python.exe`.
3. If creating a fresh environment, run `python -m venv .venv`, activate it, then `python -m pip install -e ".[test]"`.
4. Create a Python run configuration with **Module name** `rogi`, the project folder as working directory, and the selected virtual environment. Run it.

You can also run `rogi/ui.py` or `rogi/__main__.py` directly from PyCharm with the same interpreter.

From this folder on macOS/Linux:

```sh
.venv/bin/python -m rogi
.venv/bin/python -m pytest -q
```

Dependencies and supported version ranges are in `pyproject.toml`. `requirements-tested.txt` records the exact dependency versions installed during validation; it is a reproducibility snapshot, not a cross-platform lockfile. For that environment, install it before `pip install -e .`.

## Example data

`example-data/` (raw instrument files plus converted `.h5` projects, about 150 MB) and `artifacts/` (generated analysis and HDF5-trial outputs) are not stored in git; both are listed in `.gitignore`. Get the `260813` measurement folder from the project maintainer and place it at `example-data/260813/` with its `Spectrum/`, `spm/`, and `sxm/` subfolders. Several tests read files from `example-data/260813/Spectrum/` and `example-data/260813/spm/`, so they need this folder to run. `scripts/hdf5_trial.py` regenerates `artifacts/hdf5-trial/`.

## Short user guide

1. Click **Import…** to open a `.csv`, `.tsv`, `.txt`, or `.dat` text file; try `examples/gaussian.csv` or `examples/linear.tsv`. Plain DAT files default to the Tab delimiter; select Comma or Semicolon if needed. Spectrum instrument DAT files are detected automatically: import reads the tab-separated `[Data]` section, uses its channel headers, and adds suffixes to duplicate names. When `Time_Timestamp` is present, a text `Time` column is omitted regardless of its position; numeric `Time` columns are retained. Whitespace around channel names is ignored. Instrument metadata and timestamps are parsed into structured fields; complete original text is preserved. Set delimiter and header mode, inspect the first 100 rows, and check at least two numeric columns. Full import validates every row. UTF-8/UTF-8 BOM files are supported; decimal commas and arbitrary text in selected columns are not.
   To batch convert a folder, click **Convert folder…**, select the folder, and choose an output `.h5` file. This creates one HDF5 project containing one raw dataset per CSV, TSV, TXT, or DAT file, and one dataset per SPM/SXM file containing all selected channels, including files in subfolders. Relative subfolder paths become dataset groups (for example, Spectrum, spm, sxm, or spm/day2); root-level files remain ungrouped. Other file types and directory symlinks are excluded. Plain tables must have headers and numeric columns; comma, tab, and semicolon delimiters are detected automatically. Spectrum DAT metadata and timestamps are preserved in source text. If a supported file is invalid, conversion stops with its relative path and leaves any existing output untouched. The converted project opens automatically; only the first dataset is initially visible. Unsaved changes in the current workspace can be saved, discarded, or cancelled before conversion.

   To add a file to an existing HDF5 project, use **Open project…**, select the `.h5` or `.hdf5` file, then click **Import…**. After the data preview, choose a destination subgroup (including parent groups or the project root), or enter a new subgroup name beneath that destination. The dialog suggests a subgroup from the imported metadata: explicit metadata group levels must match; manually named groups use metadata shared by their members that varies across the project. Matching uses original trimmed values and units, without unit conversion. The strongest unique match is preselected and its matching fields are shown; ties or absent matches leave the file ungrouped for you to choose. You can override any suggestion. Click **Save** to store the addition alongside existing datasets and analysis. Cancelling the subgroup dialog adds nothing; imports support Undo/Redo. This workflow supports Rogi HDF5 projects and their logical subgroup hierarchy, not arbitrary third-party HDF5 layouts.

2. Select a dataset in the left browser. Its table is below the plot. Imported data is read-only. Click **Editable copy** and double-click cells to change numbers; a blank cell means missing. Copies retain parent IDs and an edit history in the project. Editing invalidates the copy's previous fit.
3. Use the **Axis channels** panel to choose an **X axis channel** and **Y axis channel** for the selected dataset, then choose Line or Scatter. Changing a channel for a hidden dataset shows that dataset alone, replacing the previous plot. Changing channels for an already visible dataset preserves checked overlays; use checkboxes to explicitly compare datasets. Plot labels follow the channels unless you enter custom labels; overlays list the distinct visible channel names in dataset order. Clear a custom label to restore automatic channel names. Check/uncheck datasets in the browser to overlay/hide them. Checking a dataset also activates its X/Y controls; unchecking another dataset does not change the active target. The active dataset name appears under the channel controls. Enter title and axis labels, then press Enter or leave the field. The Matplotlib toolbar offers zoom, pan, home, and history. Lines follow original row order. Missing values appear as blank cells and gaps in lines; they remain in stored/exported data.

   Channel lists belong to each file. Spectrum conversion retains all numeric `[Data]` columns, including every recorded lock-in signal and repeated columns (with numbered suffixes). Of the 48 supplied examples, 38 record `Lockin1_X`, `Lockin1_Y`, `Lockin1_R`, and `Lockin1_Theta`; 10 contain no lock-in measurement columns. Conversion does not generate signals absent from the source. Check **Organize → View metadata… → Original source text** against the `[Data]` header when investigating a missing channel. The `scripts/prepare_spectrum.py` helper uses the same parser as folder conversion and refuses to overwrite an existing project.
4. Fitting is hidden by default. Enable **View → Show fitting** to reveal fit controls, curves, residuals, and fit export. Choose a model and enter inclusive minimum/maximum X bounds. Alternatively, disable toolbar pan/zoom, check **Drag to select range**, and drag horizontally over the plot; drag the range handles to adjust. Numerical bounds are authoritative. The fit applies only to the selected dataset, even if others are overlaid.
5. If X/Y contain missing values, fitting stops unless **Exclude rows with missing X/Y** is checked. The fit reports the total missing X/Y rows excluded across the dataset (even when outside the range). Range selection separately excludes finite rows outside the bounds.
6. Click **Fit selected dataset**. Parameters, approximate standard errors, sample count, degrees of freedom, and RMSE appear on the right. Residuals (`observed - fitted`) appear below the main plot. Fits run in a background thread; editing is temporarily disabled for consistency. One latest fit is retained per dataset; make copies to retain competing fits. Changing X/Y preserves the fit's provenance and hides its curve if the columns differ.
7. **Export data…** writes selected dataset columns to CSV, leaving missing cells blank. **Export fit…** writes CSV sections for metadata, parameters/standard errors, and per-row predictions/residuals. Source row numbers in that export count data rows, excluding the header. **Export plot…** writes the visible plot panels as PNG or SVG.
8. **Save / Save as…** defaults to a portable `.rogi.h5` HDF5 file. JSON projects can still be opened and saved; use **Save as…** to convert an existing JSON project to HDF5. **Open project…** restores datasets, edit history, fit results, column/style/visibility choices, labels, and main plot axis limits. Imported source text (including unselected columns) is embedded so the original file is not needed. Pending, unexecuted range/model choices are temporary; completed fit ranges are retained. Closing/opening another project prompts to save modified data/results.

## Spectrum metadata and timestamps

Spectrum DAT import preserves the complete decoded UTF-8 source text, including original line endings and any BOM, and populates two optional dataset fields:

- **instrument_metadata** stores ordered sections and entries, occurrence numbers, original values, parsed numeric/text values, explicitly written units, and source line numbers. Empty sections and repeated sections/keys remain separate; unknown header lines are retained. Empty values remain missing. A value such as `100 ms` exposes `100` and `ms`; bare numeric OscFreq values have **no assigned unit**.
- **timestamps** stores each original Time / Time_Timestamp column independently, including its original column number, row-aligned original strings, parsed values, and unrecognized row numbers. Observed text dates use `YYYY/MM/DD_HH:MM:SS` and parse to timezone-free ISO text. Numeric timestamps remain numbers; no epoch, unit, or timezone is inferred. Missing timestamps stay missing; unrecognized dates retain their original text and a diagnostic.

These rules come from the 48 supplied files, including repeated Lockin1/K2401_source blocks. Filename fragments are not interpreted as metadata or units. See [the schema notes](docs/spectrum-metadata.md).

Select a dataset and choose **Organize → View metadata…** to inspect instrument fields, per-row timestamps, and source text. Metadata and timestamps remain available even when their numeric channels were omitted during import.

Browser search matches metadata names, original and parsed values, and original/ISO timestamps. Try `SR830`, `2026-08-14`, or `TimeConstant[1]=100 ms`.

**Organize → Group by metadata…** supports nested groups:

- Choose **Selected files** or **All project files**, with file counts shown for each scope.
- **Add subgroup within existing groups** is the default: grouping `spm` files by scan size keeps `spm` as the parent and adds scan-size children. Choose **Replace grouping** explicitly only to discard the existing hierarchy.
- Choose the first metadata field, then **Add subgroup level** for each additional subdivision. Each level offers fields with at least two distinct nonblank values within at least one parent group. Remove a level to simplify the hierarchy.
- Set ascending or descending order independently at each level. Numeric values sort numerically, text alphabetically; units are not converted. Original trimmed values remain distinct.
- Inspect the expandable preview: each parent and subgroup shows its file count. The summary counts final groups and files. Missing values form explicit **Missing value** subgroups, sorted last in either direction.
- Apply to assign groups and order the scoped files in their existing browser slots. Files outside the scope stay unchanged. Grouping and ordering are one undoable action.

The collapsible **Groups** navigator above the file list filters by parent or subgroup; a parent includes all its descendants. **All groups** restores the full list. Group paths store each field and value separately, so slashes in labels do not create unintended subgroups. Group labels show only the effective metadata name and value (for example, `Scan Size = 10000 nm`). Fields with colliding short names receive distinct numbered suffixes across the grouping; hover to see the original field. Full field identities remain stored and control filtering, so simplifying names never merges distinct fields. JSON and HDF5 preserve paths, editable copies inherit independent paths, and older group labels remain a single parent level. Manual **Assign group** replaces a hierarchy with a plain label; **Ungroup selected** clears it. Both can be undone.

Repeated sections/keys have distinct occurrence numbers, such as `Lockin1[1].TimeConstant[1]`. First/last timestamps and a date from the first source row, when parseable, are also offered. Dataset IDs and lineage are preserved.

JSON and HDF5 retain this structure. Older projects remain readable with empty metadata; reopening does not silently reparse embedded source. Reimport the original DAT to populate structured fields. Editable copies inherit independent acquisition snapshots and the originating dataset ID: editing a numeric timestamp channel does not rewrite original timestamps or metadata.

## Keyboard shortcuts and table clipboard

The File menu and toolbar share these shortcuts (use **Cmd** on macOS and **Ctrl** elsewhere):

| Action | Shortcut |
| --- | --- |
| Import text data | Cmd/Ctrl+I |
| Open project | Cmd/Ctrl+O |
| Save | Cmd/Ctrl+S |
| Save as | Cmd/Ctrl+Shift+S |
| Copy table selection with headers | Cmd/Ctrl+C |
| Paste numeric block | Cmd/Ctrl+V |
| Undo | Cmd/Ctrl+Z |
| Redo | Cmd+Shift+Z on macOS; platform-standard Ctrl+Y / Ctrl+Shift+Z elsewhere |

Select a complete rectangular block of table cells, then copy. The clipboard contains tab-separated values with column headers; missing values are blank. You can copy raw datasets. Nonrectangular selections are rejected rather than filling gaps with unselected data.

To paste, select a destination cell or rectangle in an **editable copy**, then paste. The block starts at the selection's top-left; the selection size does not resize, repeat, or tile the pasted block. Tab-separated and comma-separated numeric tables are accepted, including blank/NA/NaN/N/A for missing values. Data copied by Rogi includes recognized headers; external text may include a header row that exactly matches the destination columns and contains nonnumeric labels. Numeric-looking external headers are treated as data to avoid silently discarding a row. No rows or columns are added.

The entire block is validated before anything changes. Irregular row widths, invalid numeric cells, infinity, and out-of-bounds blocks are rejected. Errors identify clipboard and destination row/column locations (the first ten errors are shown, with the total count). A successful paste is one undoable operation; each changed cell retains its own edit-history entry and revision increment. Undo restores all prior cells, revisions, and a matching fit; a no-op paste leaves history and fits unchanged.

Copy/paste shortcuts apply while the table has focus. Finish an active cell editor before pasting a block; text fields retain their normal text-editing copy/paste behavior. File actions and table paste are disabled during fitting.

## Undo and redo

Use **Edit → Undo / Redo**, **Cmd+Z / Cmd+Shift+Z** on macOS, or the platform's standard **Ctrl+Z / Ctrl+Y** (and supported Ctrl+Shift+Z) shortcuts. Menu labels describe the next action, such as a cell's dataset, row and channel, a rename, or a bulk group/visibility change. A text field that is still being edited retains its normal text-editing shortcuts; committed table edits enter the project history.

History covers editable-cell changes and rectangular pastes, dataset rename, grouping, removal, visibility (including automatic showing after a channel change), imports, and editable-copy creation. A bulk action is one undo step. New undoable changes after Undo discard the old redo branch. No-op edits and canceled/invalid operations do not add history. Dataset IDs, source text, parent links, and raw read-only values are preserved. Undo removal restores dataset order, values, edits and fits; the original lineage safeguards still apply.

Undoing a cell edit restores the previous value, revision, and edit history. A fit is restored only if its revision and fitted observations match the restored data and its dataset provenance is unchanged. Redo restores that edit's revision/history and a matching fit, if one was calculated for that state; otherwise the fit stays invalidated. Fits from discarded redo branches are not reused. Undo/redo is disabled during background fitting.

Saving retains session history and marks its current position as clean. Undoing back to that position clears the modified marker unless there are other unsaved changes. Plot presentation changes and fitting are not undo commands; they remain tracked as unsaved changes until saved. Opening a project clears history, while persisted data revisions and edit provenance remain. Removed datasets and saved fit snapshots occupy memory until their history is discarded or the project closes; history itself is not written to JSON/HDF5.

## Region statistics

Enable **View → Show statistics**, highlight a dataset, and check **Drag on plot to select**. Choose **X range** to select a horizontal interval, or **Rectangle** to restrict both X and Y. Drag on the main plot; handles let you adjust the region. Enabling selection turns off toolbar pan/zoom and fitting-range selection. You can also enter bounds and click **Calculate statistics**. Bounds are inclusive and may be equal to select an exact coordinate.

Results summarize the active dataset's selected **Y channel**: count, minimum, maximum, mean, median, standard deviation, variance, standard error of the mean, sum, RMS, and 25th/75th percentiles. Duplicate X values are separate observations; values are neither interpolated nor weighted. Choose **Sample (N − 1)** or **Population (N)** for standard deviation and variance. Standard error is the chosen standard deviation divided by √N; interpreting it as uncertainty assumes independent observations. Percentiles use linear interpolation.

Missing X values are excluded and counted across the whole dataset because their region cannot be determined. Missing Y values are counted within the X interval before optional Y filtering. Empty regions report count zero and N/A statistics; sample standard deviation, variance, and standard error need at least two observations. N/A also denotes numerical overflow.

Statistics use stored values, including nonpositive values hidden by a log scale if they fall inside the specified bounds. They do not summarize fit curves or all overlaid datasets. Check the active dataset's visibility box to see its curve while selecting. Results refresh after edits; changing dataset or X/Y channels clears the selection. The region survives unrelated redraws without changing zoom.

Statistics are a temporary inspection tool: regions/results are not saved in projects and do not mark the project modified. You can select and copy text from the results box. Source data, provenance, and saved fits are unaffected.

## Plot controls

Enable **View → Show plot controls** for advanced presentation options; the default interface stays compact.

- Choose linear or base-10 logarithmic X/Y scales. Leave **Automatic limits** checked to fit visible data, or uncheck it and enter finite minimum/maximum values. Click **Apply axes** to commit both axes together. Log limits must be positive, and minimum must be below maximum. Invalid input leaves the current plot unchanged.
- Zooming or panning with the toolbar switches the affected axes to manual mode. Manual limits survive selection, renaming, colors, labels, overlays, and fitting-panel changes. To fit the data again, enable automatic limits and apply. Applying axes also resets the residual Y view to automatic. Home/Back/Forward retain the toolbar's normal navigation history; applying axes or opening a project resets that history.
- Dataset color and marker controls affect the current highlighted dataset. Automatic markers mean no marker for lines and circles for scatter; None suppresses markers. **Reset color** restores the automatic palette. Fits and residuals use the dataset color. Editable copies inherit color and marker choices.
- Choose a legend position or **hidden**. **Coordinate cursor** displays crosshairs and X/Y coordinates in the status bar, including actual data coordinates on logarithmic axes. It does not snap to samples; residual-panel coordinates are labeled Residual.
- Log axes cannot display zero or negative coordinates. Rogi masks affected display rows, leaving line gaps, and reports counts for data and fit points. Missing values also remain gaps. Stored arrays, source text, fits, exports, and fitting calculations are unchanged. Empty logarithmic views use a positive fallback range. Residual Y is always linear.

JSON and HDF5 projects retain scales, automatic/manual modes, limits (including residual Y zoom), colors, markers, legend position, cursor toggle, and fitting visibility. View changes trigger unsaved-change prompts; moving the cursor does not. Older projects default to linear scales and automatic styles; saved legacy limits restore as manual views. Pending axis entries are not saved until applied. Opening the controls panel itself is temporary.

## Dataset organization

The browser keeps highlighting (selection) separate from checkboxes (plot visibility). Click a row to inspect it; use Cmd/Ctrl-click or Shift-click for multiple selection. The current highlighted dataset supplies the table, axis controls, editable-copy, fitting, and export actions. Changing its X/Y channels checks its visibility box so the edited curve appears. Projects restore the saved active dataset; projects without a saved selection select the first visible dataset. **Organize → Show selected / Hide selected** changes plot visibility for highlighted rows together.

Search matches dataset names, group names, and source paths, ignoring case. The group filter offers All groups, Ungrouped, and each assigned group. Filtering only changes the browser; already visible curves remain plotted. Rows hidden by a filter are deselected so bulk actions cannot unexpectedly affect hidden rows. **Select all shown** selects matching rows; **Clear selection** clears highlights.

Use **Organize → Rename…** for a single selected dataset, **Assign group…** to create or choose a group for selected datasets, or **Ungroup selected** to clear membership. Groups are flat labels, with one group per dataset; empty groups disappear. Editable copies inherit their parent's group. Names and groups do not change IDs, numeric values, source text, edit history, or fits.

**Remove selected…** confirms removal from the project, including the selected datasets' edits and fits. Source files are untouched. Removal is blocked if a remaining derived copy references a selected dataset: keep the parent (you can hide it), or explicitly select the dependent copies too. This also protects chains of copies. Use **Edit → Undo** to restore removed datasets during the current session.

Names, group membership, and plot visibility persist in both JSON and HDF5 projects. Search text, the group filter, and row selection are temporary and reset when a project is opened. Older projects without groups open as ungrouped; existing provenance and missing values are preserved. Previously missing parent references in legacy files are retained as recorded; organization does not reconstruct unavailable ancestors.

## Models and uncertainty assumptions

**Linear:** `y = slope*x + intercept`. Slope has Y/X units; intercept has Y units. Solved by ordinary least squares. More than two distinct X values are required so residual variance can be estimated.

**Gaussian:** `y = baseline + amplitude * exp(-0.5*((x-center)/sigma)^2)`. Baseline is the constant background, amplitude is peak height relative to baseline (negative peaks allowed), center is in X units, and sigma is positive width in X units. FWHM = `2*sqrt(2*ln(2))*sigma`. More than four distinct X values are required. Initial guesses use median background, strongest deviation, and range/6 width. Select a single peak with both tails; local optimization can fail or converge to an unsuitable peak. Inspect residuals and physical plausibility; convergence alone is not validation.

Both models minimize unweighted squared Y residuals. X is treated as exact. Errors are assumed independent with equal unknown variance; residual variance is estimated as SSE/(N-p). Reported ± values are approximate one-standard-deviation parameter standard errors from covariance, not confidence intervals or measurement uncertainties. Gaussian covariance is a local linear approximation. Unavailable/nonfinite or severely ill-conditioned covariance is reported explicitly. Exact synthetic fits can have zero estimated errors; that does not establish zero experimental uncertainty. No weighting, X-error treatment, robust loss, or parameter constraints beyond positive Gaussian sigma are provided yet.

## Architecture and limits

- `rogi/core.py`: datasets, imports, fits, CSV exports; no GUI dependency.
- `rogi/project.py`: shared project validation, JSON compatibility, and format dispatch.
- `rogi/hdf5.py`: versioned HDF5 encoding with compressed numeric datasets and atomic save replacement.
- `rogi/ui.py`: desktop widgets, plot interactions, background fit worker.
- `tests/`: synthetic numerical checks, invalid imports/fits, project round trips, offscreen desktop integration.

This version targets moderate in-memory datasets. Import, project loading/saving, and plot drawing run on the UI thread and can pause with large files; only fitting is threaded. There is no fit cancellation, multiple plot-window management, scripting, plugins, advanced signal processing, or specialized format support yet. Project files preserve full source text and can be larger than the original data. Plot zoom, pan, history navigation, and applied presentation changes mark the project as modified and participate in save prompts.

## Manual acceptance check

Run the app in PyCharm and repeat the guide with your own CSV/TSV. Check native file dialogs, keyboard editing, pan/zoom, range handles, overlays with your units, and exported image appearance. Compare real fits with Igor Pro using identical model definitions, range, weighting, and missing-value treatment. Automated tests do not establish agreement with Igor Pro or cross-platform native UI behavior.

## HDF5 storage and editing

Install or update dependencies with `python -m pip install -e ".[test]"`; h5py is a required dependency. New projects default to HDF5 (`.h5` or `.hdf5`). Open a project, select a raw dataset, click **Editable copy**, edit its table cells, and save. Editable datasets remain editable after reopening; raw data stays read-only. Editing invalidates the affected dataset's saved fit.

HDF5 stores values and per-row fit results as compressed typed arrays. Dataset IDs, column labels, source text, edit history, fit metadata, and plot settings are retained. Saves write a temporary file, close and sync it, then replace the destination. Existing version-1 JSON and HDF5 projects remain readable; datasets without group metadata open as ungrouped. New files include group metadata and may require this version of Rogi.

This is an in-memory editor with HDF5 persistence: opening still loads all datasets, and saving rewrites the project. It does not yet support lazy/out-of-core editing, concurrent writers, or arbitrary third-party HDF5 layouts. The earlier `artifacts/hdf5-trial/*.h5` benchmarks use a separate experimental schema and cannot be opened as Rogi projects.

### Bruker/NanoScope SPM import

Use **Import…** to select a `.spm` file, preview its image or force-curve channels, and check the channels to import. Each imported file appears once in the dataset list. Its read-only table contains coordinates and one signal column per selected channel. Force curves use Segment and Sample in segment coordinates, retaining stored segment order without inferring approach/retract direction. Channels with different sampling grids retain separate coordinate columns and their original row counts. The default plot shows signal versus sample index. **Convert folder…** also includes `.spm` files (case-insensitive).

This importer supports NanoScope raster images and single force curves with explicit dimensions and signed little-endian 16-bit or 32-bit samples. Signals are **raw ADC counts**, not calibrated heights or other physical units. Pixel coordinates are zero-based and preserve storage order; scan orientation and physical coordinates are not inferred. Complete header text and structured metadata survive JSON/HDF5 project saves; original binary source bytes are not embedded. Keep the original `.spm` files for calibrated analysis.

Unrecognized SPM formats, force-volume files, and interleaved layouts are rejected with an explanatory error. Truncated data and inconsistent dimensions also stop import or folder conversion. File structure follows the [NanoScope file-format documentation](https://www.nanoqam.ca/help/Multimode/Content/SoftwareGuide/FileFormats/Parameters.htm).

### Nanonis scans and spectra

**Import…** and **Convert folder…** also accept Nanonis `.sxm` scans, including SXM content saved with a `.spm` extension. Each file is imported once, retaining all forward/backward channels as separate signal columns with their declared units and stored floating-point values. Pixel coordinates retain acquisition order, without rotation or reversal. Headers are retained in the project. Both big- and little-endian FLOAT scans are supported; incomplete payloads are rejected. Nanonis-style `[Data]` spectroscopy tables continue to use the existing `.dat` importer. Nanonis `.3ds` grids are not supported. SXM decoding follows the [Nanonis reader format reference](https://github.com/ethz-micro/matlab_nanonis/blob/master/Manual/sxm.tex).

### Interactive 2D image viewer

Select an imported scan file in the dataset list, click **2D Map** above the plot, and use **Channel** to switch signals or scan directions. This also works with previously saved Rogi projects containing the SPM pixel-coordinate columns; no reimport is needed. The map follows the active dataset, independently of the checkboxes used for line plots. Maps are centered and use the available plot area. The data table is hidden by default in 2D Map; enable **Show data table** to bring it back. Switching to Line plot restores the table. Spectra and force curves remain available in **Line plot**.

- **Colors** selects the color palette. The color bar retains the channel's units (raw counts for Bruker).
- **Full range** displays the finite minimum and maximum. **Percentile** starts at 2–98%; enter Low/High percentiles and press **Apply**. **Manual** accepts explicit signal limits, including scientific notation. Missing pixels are masked and excluded from contrast calculations.
- Hover over a pixel for its X/Y indices and original signal value. Use the text buttons **Reset view**, **Pan**, and **Zoom** to navigate. Use **Export plot…** to save the figure. Palette and contrast changes preserve the current zoom.
- **Compare with** lists only matching channels from the same source file type (.spm or .sxm) and instrument format. Channel name, scan direction, and units must match; the active channel itself is excluded. It is disabled when no match exists. Full-range/percentile scaling is calculated separately for each channel; manual limits apply to both. Read the individual color bars when comparing automatically scaled maps.
- **Export plot…** exports the active tab, including both maps and color bars when comparing, as PNG or SVG.

Maps preserve stored pixel order and use physical X/Y scan dimensions from the Bruker Scan Size or Nanonis SCAN_RANGE headers when available. A 256 × 64 scan over 20 × 20 µm therefore displays as a square with rectangular sampling cells. This changes the displayed pixel spacing without adding or interpolating measurements. Axes fall back to pixel indices when dimensions or units cannot be resolved. Cursor readout includes both pixel indices and physical pixel-center coordinates. Scan rotation and laboratory position are not applied. Contrast changes never modify measurements. Editable copies update after edits and undo/redo; invalid or duplicate pixel coordinates produce an explanatory message. Palette, contrast, comparison, and map zoom are session display controls and are not saved in project files.

To combine the example measurement collections, select `example-data/260813` in **Convert folder…** and save as `example-data/260813.rogi.h5`. Use **Open project…** to open the result and the dataset group filter to switch between Spectrum, spm, and sxm. Binary instrument source files and unsupported Igor/thumbnail files are not embedded; retain the original folder as the source archive.

### File-based channel organization

SPM and SXM imports and folder conversions now create one dataset per source file. The **2D Map → Channel** selector switches among its image channels; the table and line-plot channel selectors expose the same signals. Map selection is remembered per file during the session. Selecting channels in the import preview includes only those channels in the file dataset.

Older projects containing untouched channel-by-channel imports are consolidated in memory when opened in Rogi. Files with edited or fitted channels, dependent copies, or ambiguous repeated imports remain separate to preserve their analysis history. The original project on disk changes only when saved. Use **Save as…** to keep a separate updated project.

### Named saved views

Use **View → Saved views → Save current view…** to name the current presentation.
Each named view has **Restore**, **Rename…**, and **Delete** actions in that menu.
Names must be nonempty and unique. Save the project after changing saved views.

Views preserve dataset visibility, the active dataset, each dataset's X/Y channels,
the Line plot / 2D Map tab, plot title and axis labels, axis scales and automatic or
manual limits (including line-plot zoom), legend and cursor settings, and fitting
panel visibility. Image settings include the palette, contrast mode and limits,
per-file map channel choices, comparison channel, and each displayed map's zoom.
Restoring a view changes presentation only; it does not copy or revert data or fits.

Views are stored in the optional `settings.saved_views` field in both HDF5 and JSON
projects. Older projects without that field open with no saved views. Restoration
uses stable dataset IDs, so renamed or reordered datasets still match. Missing
datasets are skipped with a status message; if the active dataset is missing,
Rogi selects an available visible dataset, or the first remaining dataset. A missing
comparison becomes “None.” Datasets added after a view was saved retain their
current visibility and channels; unavailable channel indices retain their current
selection. Restoration clears browser filters to reveal the active dataset.

### Image cross-section profiles

The **2D Map** tab shows two crosshair cursors marked by a cyan square and an
orange circle. Drag either marker with the left mouse button to move both X and
Y simultaneously, or drag a crosshair line to move one axis. Toolbar pan/zoom
must be off. The horizontal cut sits below the image and the vertical cut sits
to its right, with spatial axes aligned and linked to image zoom. Both cursor
profiles appear in matching colors. Profiles
snap to pixel centers and retain missing signal values as gaps. Coordinates use
scan dimensions and units when available, otherwise zero-based pixel indices.
The comparison map remains available alongside the selected map.

Choose **Cursor 1** or **Cursor 2** and **X profile** or **Y profile**, then **Export profile CSV…** to save the
coordinate and signal columns (missing values are blank), or **Create profile
dataset** to add an editable derived dataset. The derived dataset records its
parent, source channel, source revision, original extraction axis, pixel index,
and coordinate position with units in its instrument metadata. Creation supports
undo/redo, and provenance is retained in saved projects.

**Transpose display** swaps the displayed image axes and labels without changing
source values or calibration. X and Y profile names and extraction positions
always refer to the original data axes. View snapshots retain transpose and
cursor positions.

Enable **Select rectangle between cursors** to highlight all pixels between the
cursor positions, including both boundary pixels. The selection shows pixel and
missing-value counts and the mean of finite values. **Create region dataset**
creates an editable coordinate table for further analysis, preserving original
X/Y coordinates, signal values, missing pixels, source channel/revision, and
inclusive region bounds. Region creation supports undo/redo and project saving.
Transpose swaps the displayed horizontal/vertical cuts while preserving original
X/Y meaning for exports. View snapshots retain both cursors and region selection.


Rogi remembers the ten most recently opened or saved projects on this computer.
At startup, choose a recent project from the suggestion dialog, or cancel to start
with an empty workspace. **File → Recent projects** also opens them later. Missing
files are omitted, and successfully opened or saved projects move to the top.

### Multiple line-plot panels

Use **Add panel with selected channels** in the axis-channel controls to create
another panel, then choose its X and Y channels. The **Active panel** selector
chooses which panel the channel controls, axis limits, statistics selection, and
fitting tools operate on. Each panel can overlay datasets: select a dataset and
use **Assign selected channels to active panel**. Use the corresponding remove
button to remove that dataset's assignment without deleting its data. Changing
channels updates only its assignment in the active panel. Existing single-panel
projects continue to overlay visible datasets as before.

Y scales, limits, and custom labels are independent for each panel. Enable
**Synchronize X limits** to use the active panel's X range and scale throughout
the layout; subsequent X zooms propagate across panels. Disable it to zoom each
panel independently. **Coordinate cursor** shows a common X guide across visible
panels and the hovered position's coordinates in the status bar. Fitting and its
residual panel follow the active panel; the existing per-dataset fit storage is
unchanged.

Named views and project saves preserve channel assignments, panel axes, the
active panel, and X synchronization. PNG and SVG figure export include the full
visible layout, including the active residual panel when fitting is shown.

### Non-destructive analysis pipelines

Select a dataset and click **Analysis pipeline…**. Choose distinct X and Y input
channels and check their units (units in trailing parentheses are suggested;
blank means unknown, `1` means dimensionless). Add operations, select each step
to configure its normalization method or smoothing window, and use **Move up** /
**Move down** to change execution order. Repeated operations are allowed.
**Preview** shows input and output on separate axes so differing units are clear.
Changing any configuration clears the preview and disables saving until another
successful preview. **Save as derived dataset** adds an independent editable
snapshot to the workspace and supports Undo/Redo. Use project **Save** to persist
it. Cancelling creates nothing. Source data, fits, and revisions remain unchanged.

The initial operations use these explicit rules:

- **Subtract mean:** subtract the arithmetic mean of finite X/Y pairs.
- **Normalize:** divide by the maximum absolute value, or subtract the minimum
  and divide by the range for `[0, 1]`. Zero scales (including constant signals
  with minimum–maximum normalization) are rejected. Output is dimensionless.
- **Moving average:** centered, positive odd window measured in samples; clip
  the window at each contiguous valid segment's boundaries and divide by the
  actual sample count. Samples have equal weight even on irregular X grids.
- **Differentiate:** use actual X spacing and three-point nonuniform central
  differences in segment interiors; use two-point one-sided slopes at endpoints.
  Two-sample segments use their secant slope at both rows; singletons yield
  missing values. Finite X coordinates must be strictly increasing or decreasing
  across the entire input, including across gaps. Duplicates and reversals are
  rejected. No sorting, resampling, or interpolation occurs.

All operations preserve row count and X values. Rows missing X or Y have missing
output; smoothing and differentiation never cross those gaps. Mean and
normalization exclude those rows. An operation with no valid input pairs is
rejected; a final differentiation may yield only missing values for singletons.
Numeric overflow is rejected. Mean subtraction and smoothing retain signal units;
differentiation records signal/X units, or unknown if either unit is unknown.
Units are labels, with no conversion or dimensional simplification.

Each result stores versioned `analysis` provenance: source dataset ID and exact
revision, X/Y channel indices, names and input units, ordered operations with
parameters, output units, and numerical policies. `column_units` stores units
for the two output columns. JSON and HDF5 retain both fields; older projects
without them remain readable. Chained analyses refer to their immediate parent.
Results are snapshots and do not recompute after source edits; their provenance
continues to describe their creation, while subsequent result edits have their
own revision and edit history. An editable copy retains an independent copy of
this provenance. Unsaved pipeline configurations are temporary.

### Spectrum maps

Select spectra in the dataset browser and choose **2D spectrum map…**. Choose an
X channel, signal channel, and an explicit numeric metadata sweep field (for
example temperature or magnetic field). Rogi never infers sweep coordinates from
file order or filenames. Additional metadata selectors fix other sweep dimensions;
a combination without measurements is reported instead of synthesized.

Channel and sweep units must be known and identical across the selected slice.
There is no automatic unit conversion; `1` denotes dimensionless quantities.
Repeated sweep values are rejected: select another dimension or distinct spectra.
Missing/nonfinite sweep coordinates, missing channels, and duplicate or missing
X coordinates are rejected. Missing signals can either fail validation or remain
visible as gaps, selected explicitly.

Choose an alignment even when the grids match:

- **Identical measured X grids** accepts the same coordinates in any row order.
- **Union of measured X coordinates** preserves every measured X value and leaves
  unmeasured cells empty.
- **Reference interpolation** uses the chosen spectrum's measured X coordinates
  and piecewise linear interpolation. It never extrapolates or bridges missing
  samples. The reference must belong to the selected slice.

The plot uses physical coordinate spacing, including irregular sweeps. Cross-section
selectors choose actual plotted coordinates. Named map views save source identities,
channel/metadata choices, filters, alignment, and cross-section selection in the
project's existing saved-view menu. Restoring a view rebuilds from current source
values and validates again; missing sources cause an error.

Export the map as CSV (plotted X/sweep/signal coordinates) or NPZ (plotted arrays,
units, recipe, source IDs, and each spectrum's original X and signal samples).
Cross-sections export to CSV; figures export to PNG, PDF, or SVG. Map assembly and
sorting never modify the source datasets. NPZ is the export to use when the original
measured grids must accompany an interpolated map.

### Analysis across selected spectra

Select two or more datasets in the browser, then choose **Analysis pipeline…**.
The dialog uses each dataset’s selected X and Y channels and requires identical
channel names and units (including unknown units); it does not convert units.
Choose a mean spectrum, subtraction of a chosen reference from every other
selected dataset, or explicitly add **left − right** pairs. Pairing is never
inferred from selection order or dataset names. Results are editable snapshots
and can be used as inputs to subsequent analysis pipelines.

Exact X-coordinate matching is the default, with no rounding tolerance. To
resample, explicitly choose linear interpolation and a selected dataset’s grid.
Interpolation requires finite, strictly monotonic X coordinates, supports either
direction, and leaves out-of-range samples and missing-data gaps empty. There is
no extrapolation. Exact alignment also requires finite X coordinates.

Mean results contain X, mean, sample standard deviation (SD, denominator n−1),
standard error of the mean (SEM = SD/√n), and the finite contributing sample
count at every X. The preview plots counts separately; the saved dataset table
retains their exact values. SD and SEM are missing when n < 2; the mean is
missing when n = 0. Shaded bands in the preview and main plot show **±1 sample
SD**, not SEM. Subtraction results contain the difference and contributing
operand count (0–2); a difference requires both operands.

Project saves preserve all selected input IDs, names, revisions, channels and
units, explicit subtraction pairs, grid identity, alignment mode, and numerical
policies. Input datasets are never modified.

### Reusable pipeline presets

In the single-dataset **Analysis pipeline…** editor, **Save/update preset…** names
and stores the ordered operations and parameters. Entering an existing name
replaces that preset. **Load preset** restores a saved recipe for editing;
changes affect the preset only when saved again. Presets are data-independent:
input channels and units are chosen for each application, not copied from the
original dataset. The preset includes its version and numerical policies.

Presets persist in JSON and HDF5 project settings. **Export…** writes the selected
saved preset to a standalone JSON file; **Import…** adds presets from such a file
so they can be used in another project. Imported name collisions receive numbered
suffixes. Explicitly saved/imported presets stay in the workspace even if you
cancel result creation; use project **Save** to persist them. Unsaved editor
changes remain temporary. Presets support the four single-signal operations;
multi-dataset subtraction and ensemble statistics retain their existing dialog.

Select a derived pipeline result and click **Reopen analysis recipe…** to restore
its operation order, parameters, source channels, and unit labels. Preview uses
the source dataset's current values; a message identifies changed revisions.
The new result receives new provenance and an independent ID. The previous
result remains unchanged. You can also save the reopened recipe as a preset.

To reuse a preset across files, highlight datasets in the browser and click
**Apply pipeline preset…**. Choose X/Y channels for each input in the table; the
channel labels show the units that will be recorded. **Preview all** computes
independent outputs and lets you inspect each result using the result selector.
No channel matching or unit conversion is inferred. If any input fails, no
results can be created. **Create all derived datasets** adds the entire batch as
one undoable action. Changing a channel or preset invalidates the preview. Raw
inputs remain unchanged, and each result retains its own source ID/revision and
full executed recipe regardless of later edits to the preset.

### One-click temporary image previews

Select an image file and channel in **2D Map**, then click a named preset under
**Temporary image preview**. The preset runs immediately and opens the input and
processed image side by side. No derived dataset is added, no processed values
are written to disk or included in project saves, and the project is not marked
modified. **Close preview** discards the temporary result. Presets themselves
remain saved recipes. Create/import presets in **Analysis pipeline…**; their
buttons also appear when reopening a project containing presets.

For image previews, mean subtraction and normalization use all finite pixels in
the image. Smoothing and differentiation operate independently along the original
**X rows** by default; choose **Y columns** in the preview to recalculate. Local
operations never cross row/column boundaries or missing-value gaps. Smoothing
uses the preset's centered sample window, clipped at boundaries. Differentiation
uses calibrated pixel spacing when available, otherwise pixel units, and the
same one-sided endpoint and singleton rules as the line pipeline. These are
axis-wise operations, not an isotropic 2D smoothing kernel or gradient magnitude.
Operation order and parameters are preserved. Each map has an independent
full-range color scale and a labeled color bar. Display transpose affects
presentation only; the processing axes always refer to the original image.

The preview is a snapshot of the selected channel at its current revision. It
has no save or derived-data creation action; its toolbar provides reset, pan,
and zoom.
