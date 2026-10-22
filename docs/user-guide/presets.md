# Reusable pipeline presets

[User guide](index.md) · [Validation and limitations](../limitations.md)

## Reusable pipeline presets

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

## One-click temporary image previews

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
