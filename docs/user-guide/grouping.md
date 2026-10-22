# Dataset organization and grouping

[User guide](index.md) · [Validation and limitations](../limitations.md)

The browser keeps highlighting (selection) separate from checkboxes (plot visibility). Click a row to inspect it; use Cmd/Ctrl-click or Shift-click for multiple selection. The current highlighted dataset supplies the table, axis controls, editable-copy, fitting, and export actions. Changing its X/Y channels checks its visibility box so the edited curve appears. Projects restore the saved active dataset; projects without a saved selection select the first visible dataset. **Organize → Show selected / Hide selected** changes plot visibility for highlighted rows together.

Search matches dataset names, group names, and source paths, ignoring case. The group filter offers All groups, Ungrouped, and each assigned group. Filtering only changes the browser; already visible curves remain plotted. Rows hidden by a filter are deselected so bulk actions cannot unexpectedly affect hidden rows. **Select all shown** selects matching rows; **Clear selection** clears highlights.

Use **Organize → Rename…** for a single selected dataset, **Assign group…** to create or choose a group for selected datasets, or **Ungroup selected** to clear membership. Manual groups are plain labels; metadata grouping supports nested paths. Empty groups disappear. See [metadata grouping](spectrum-metadata.md). Editable copies inherit their parent's group. Names and groups do not change IDs, numeric values, source text, edit history, or fits.

**Remove selected…** confirms removal from the project, including the selected datasets' edits and fits. Source files are untouched. Removal is blocked if a remaining derived copy references a selected dataset: keep the parent (you can hide it), or explicitly select the dependent copies too. This also protects chains of copies. Use **Edit → Undo** to restore removed datasets during the current session.

Names, group membership, and plot visibility persist in both JSON and HDF5 projects. Search text, the group filter, and row selection are temporary and reset when a project is opened. Older projects without groups open as ungrouped; existing provenance and missing values are preserved. Previously missing parent references in legacy files are retained as recorded; organization does not reconstruct unavailable ancestors.
