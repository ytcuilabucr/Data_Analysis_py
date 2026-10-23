# Import, editing, fitting, and projects

[User guide](index.md) · [Validation and limitations](../limitations.md)

## Bringing data in

There are two ways to bring data in. **Open…** (Cmd/Ctrl+O) opens one Rogi project (`.h5`, `.hdf5`, `.json`) or loads data files into the current project. The **Files** panel, left of the dataset list, lists a data folder so you can load files from it as an experiment produces them. Click **Show files** / **Hide files** to toggle the panel; Rogi remembers the choice. You can also drop files on the window to load them, drop a project to open it, or drop a folder to list it in the Files panel.

### Files panel

- **Folder**: type a path or click **Browse…**. Rogi reopens the last folder used with each project. **Refresh** lists files written since the last refresh.
- **Type filters**: Projects, DAT, CSV/TSV/TXT, SPM and SXM. Check **Subfolders** to include nested folders. **Filter files** matches words in the file name.
- **File list**: sorted in natural order, so `sweep_2` comes before `sweep_10`. Files already in the project appear dimmed with a check mark (**Hide loaded** removes them from the list). Files that appear after you open the folder are shown in bold. Select several files with Shift or Cmd/Ctrl, then click **Load N files**. Double-click a data file to load it, or a project to open it. You can drag files from the list onto the window.
- **Preview**: the size, modification time and readable header of the highlighted file.
- **Name**: an optional pattern for dataset names. `{stem}` is the file name, `{n}` a running number starting at **from**, `{num}` the last number in the file name and `{folder}` the parent folder. For example, `Scan_{n}` gives `Scan_0`, `Scan_1`, …, and **from** advances after each load. Grouping by title fields (such as `power100`) reads the dataset name, so keep those parts when renaming.
- **Group**: **Choose once** asks for one destination subgroup for the whole batch, with a suggestion based on metadata (see below). **Subfolder names** groups files by their folder relative to the panel folder, as folder conversion does. **Project root** leaves them ungrouped.
- **Sort rows by X** orders text data by its X channel, for example sweeps recorded from high to low. The dataset comments record the sort. Scans keep their pixel order.
- **Choose columns on first file** shows the import preview for the first file and applies its columns (text) or channels (SPM/SXM) to the rest by name. A file that lacks a chosen column is skipped. Without it, files load with every column and an automatically detected delimiter, as in folder conversion.
- **Auto-load new files** watches the folder. A new file loads once its size stops changing, so files the instrument is still writing are not read early. Auto-load never stops to ask: with **Choose once** it uses the last destination you chose, otherwise the project root.
- **New project from folder…** converts the folder and all its subfolders into a new HDF5 project (see below).

A batch of files is one Undo step. If some files fail to load, the others still load and a message lists the failures. The first loaded dataset is shown in the plot; check the others to overlay them.

### Open…

Choose one project to open it; unsaved changes can first be saved, discarded or cancelled. Choose one or more data files to load them into the current project. Open… always shows the import preview for the first file and applies its choices to the rest, then uses the Files panel's name, group and sort options. In the preview, set the delimiter and header mode, inspect the first 100 rows and check at least two numeric columns; try `examples/gaussian.csv` or `examples/linear.tsv`.

Plain DAT files default to the Tab delimiter; select Comma or Semicolon if needed. Spectrum instrument DAT files are detected automatically: import reads the tab-separated `[Data]` section, uses its channel headers, and adds suffixes to duplicate names. When `Time_Timestamp` is present, a text `Time` column is omitted regardless of its position; numeric `Time` columns are retained. Whitespace around channel names is ignored. Instrument metadata and timestamps are parsed into structured fields; complete original text is preserved. Full import validates every row. UTF-8/UTF-8 BOM files are supported; decimal commas and arbitrary text in selected columns are not.

### Adding files to an existing project

Open the project, then load files from the Files panel or with Open…. With **Group → Choose once**, choose a destination subgroup (including parent groups or the project root), or enter a new subgroup name beneath it. The dialog suggests a subgroup from the first file's metadata: explicit metadata group levels must match; manually named groups use metadata shared by their members that varies across the project. Matching uses original trimmed values and units, without unit conversion. The strongest unique match is preselected and its matching fields are shown; ties or no match leave the files ungrouped for you to choose. You can override any suggestion. Cancelling the subgroup dialog adds nothing. Click **Save** to store the additions alongside existing datasets and analysis. This supports Rogi HDF5 projects and their logical subgroup hierarchy, not arbitrary third-party HDF5 layouts.

### New project from folder

**File → New project from folder…** (or the button in the Files panel) converts a folder into a new HDF5 project. You choose an output `.h5` file. The project contains one raw dataset per CSV, TSV, TXT or DAT file, and one dataset per SPM/SXM file containing all its channels, including files in subfolders. Relative subfolder paths become dataset groups (for example, Spectrum, spm, sxm, or spm/day2); root-level files remain ungrouped. Other file types and directory symlinks are excluded. Plain tables must have headers and numeric columns; comma, tab and semicolon delimiters are detected automatically. Spectrum DAT metadata and timestamps are preserved in source text. If a supported file is invalid, conversion stops with its relative path and leaves any existing output untouched. The new project opens automatically, with only the first dataset visible. Unsaved changes in the current workspace can be saved, discarded or cancelled first. To add a folder to the project that is open instead, list it in the Files panel, check **Subfolders**, select all files (Cmd/Ctrl+A) and load them with **Group → Subfolder names**.

## Short user guide

2. Select a dataset in the dataset list. Click **Open plot window**, or double-click a dataset, to see it plotted in the [plot window](plot-controls.md#plot-window); click **Show data table** to see its values beside the list. Imported data is read-only. Click **Editable copy**, show the data table, and double-click cells to change numbers; a blank cell means missing. Copies retain parent IDs and an edit history in the project. Editing invalidates the copy's previous fit.
3. Use the **Axis channels** panel to choose an **X axis channel** and **Y axis channel** for the selected dataset, then choose Line or Scatter. Changing a channel for a hidden dataset shows that dataset alone, replacing the previous plot. Changing channels for an already visible dataset preserves checked overlays; use checkboxes to explicitly compare datasets. Plot labels follow the channels unless you enter custom labels; overlays list the distinct visible channel names in dataset order. Clear a custom label to restore automatic channel names. Check/uncheck datasets in the browser to overlay/hide them. Checking a dataset also activates its X/Y controls; unchecking another dataset does not change the active target. The active dataset name appears under the channel controls. Enter title and axis labels, then press Enter or leave the field. The Matplotlib toolbar offers zoom, pan, home, and history. Lines follow original row order. Missing values appear as blank cells and gaps in lines; they remain in stored/exported data.

   Channel lists belong to each file. Spectrum conversion retains all numeric `[Data]` columns, including every recorded lock-in signal and repeated columns (with numbered suffixes). Of the 48 supplied examples, 38 record `Lockin1_X`, `Lockin1_Y`, `Lockin1_R`, and `Lockin1_Theta`; 10 contain no lock-in measurement columns. Conversion does not generate signals absent from the source. Check **Organize → View metadata… → Original source text** against the `[Data]` header when investigating a missing channel. The `scripts/prepare_spectrum.py` helper uses the same parser as folder conversion and refuses to overwrite an existing project.
4. Fitting is hidden by default. Enable **View → Show fitting** to reveal fit controls, curves, residuals, and fit export. Choose a model and enter inclusive minimum/maximum X bounds. Alternatively, disable toolbar pan/zoom, check **Drag to select range**, and drag horizontally over the plot; drag the range handles to adjust. Numerical bounds are authoritative. The fit applies only to the selected dataset, even if others are overlaid.
5. If X/Y contain missing values, fitting stops unless **Exclude rows with missing X/Y** is checked. The fit reports the total missing X/Y rows excluded across the dataset (even when outside the range). Range selection separately excludes finite rows outside the bounds.
6. Click **Fit selected dataset**. Parameters, approximate standard errors, sample count, degrees of freedom, and RMSE appear on the right. Residuals (`observed - fitted`) appear below the main plot. Fits run in a background thread; editing is temporarily disabled for consistency. One latest fit is retained per dataset; make copies to retain competing fits. Changing X/Y preserves the fit's provenance and hides its curve if the columns differ.
7. **Export data…** writes selected dataset columns to CSV, leaving missing cells blank. **Export fit…** writes CSV sections for metadata, parameters/standard errors, and per-row predictions/residuals. Source row numbers in that export count data rows, excluding the header. **Export plot…** writes the visible plot panels as PNG or SVG.
8. **Save / Save as…** defaults to a portable `.rogi.h5` HDF5 file. JSON projects can still be opened and saved; use **Save as…** to convert an existing JSON project to HDF5. **Open…** restores datasets, edit history, fit results, column/style/visibility choices, labels, and main plot axis limits. Imported source text (including unselected columns) is embedded so the original file is not needed. Pending, unexecuted range/model choices are temporary; completed fit ranges are retained. Closing/opening another project prompts to save modified data/results.

## HDF5 storage and editing

Install or update dependencies with `python -m pip install -e ".[test]"`; h5py is a required dependency. New projects default to HDF5 (`.h5` or `.hdf5`). Open a project, select a raw dataset, click **Editable copy**, edit its table cells, and save. Editable datasets remain editable after reopening; raw data stays read-only. Editing invalidates the affected dataset's saved fit.

HDF5 stores values and per-row fit results as compressed typed arrays. Dataset IDs, column labels, source text, edit history, fit metadata, and plot settings are retained. Saves write a temporary file, close and sync it, then replace the destination. Existing version-1 JSON and HDF5 projects remain readable; datasets without group metadata open as ungrouped. New files include group metadata and may require this version of Rogi.

This is an in-memory editor with HDF5 persistence: opening still loads all datasets, and saving rewrites the project. It does not yet support lazy/out-of-core editing, concurrent writers, or arbitrary third-party HDF5 layouts. The earlier `artifacts/hdf5-trial/*.h5` benchmarks use a separate experimental schema and cannot be opened as Rogi projects.

## Bruker/NanoScope SPM import

Use **Open…** (or the Files panel with **Choose columns on first file**) to select a `.spm` file, preview its image or force-curve channels, and check the channels to import. Each imported file appears once in the dataset list. Its read-only table contains coordinates and one signal column per selected channel. Force curves use Segment and Sample in segment coordinates, retaining stored segment order without inferring approach/retract direction. Channels with different sampling grids retain separate coordinate columns and their original row counts. The default plot shows signal versus sample index. **New project from folder…** also includes `.spm` files (case-insensitive).

This importer supports NanoScope raster images and single force curves with explicit dimensions and signed little-endian 16-bit or 32-bit samples. Signals are **raw ADC counts**, not calibrated heights or other physical units. Pixel coordinates are zero-based and preserve storage order; scan orientation and physical coordinates are not inferred. Complete header text and structured metadata survive JSON/HDF5 project saves; original binary source bytes are not embedded. Keep the original `.spm` files for calibrated analysis.

Unrecognized SPM formats, force-volume files, and interleaved layouts are rejected with an explanatory error. Truncated data and inconsistent dimensions also stop import or folder conversion. File structure follows the [NanoScope file-format documentation](https://www.nanoqam.ca/help/Multimode/Content/SoftwareGuide/FileFormats/Parameters.htm).

## Nanonis scans and spectra

**Open…**, the Files panel and **New project from folder…** also accept Nanonis `.sxm` scans, including SXM content saved with a `.spm` extension. Each file is imported once, retaining all forward/backward channels as separate signal columns with their declared units and stored floating-point values. Pixel coordinates retain acquisition order, without rotation or reversal. Headers are retained in the project. Both big- and little-endian FLOAT scans are supported; incomplete payloads are rejected. Nanonis-style `[Data]` spectroscopy tables continue to use the existing `.dat` importer. Nanonis `.3ds` grids are not supported. SXM decoding follows the [Nanonis reader format reference](https://github.com/ethz-micro/matlab_nanonis/blob/master/Manual/sxm.tex).

## File-based channel organization

SPM and SXM imports and folder conversions create one dataset per source file. The **2D Map → Channel** selector switches among its image channels; the table and line-plot channel selectors expose the same signals. Map selection is remembered per file during the session. Selecting channels in the import preview includes only those channels in the file dataset.

Older projects containing untouched channel-by-channel imports are consolidated in memory when opened in Rogi. Files with edited or fitted channels, dependent copies, or ambiguous repeated imports remain separate to preserve their analysis history. The original project on disk changes only when saved. Use **Save as…** to keep a separate updated project.

## Recent projects

Rogi remembers the ten most recently opened or saved projects on this computer.
At startup, choose a recent project from the suggestion dialog, or cancel to start
with an empty workspace. **File → Recent projects** also opens them later. Missing
files are omitted, and successfully opened or saved projects move to the top.
