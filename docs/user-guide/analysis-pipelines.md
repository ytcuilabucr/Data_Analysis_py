# Non-destructive analysis pipelines

[User guide](index.md) · [Validation and limitations](../limitations.md)

## Non-destructive analysis pipelines

Select a dataset and click **Analysis pipeline…** in the toolbar (or the
**Analysis** menu). **Apply pipeline preset…** and **Reopen analysis recipe…**
sit beside it on the toolbar and in the same menu; they are greyed out when they
do not apply to the current selection. When the window is too narrow for every
toolbar button, the rest fold into the toolbar's **»** overflow menu. Choose distinct X and Y input
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

## Analysis across selected spectra

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
