# Keyboard shortcuts and table clipboard

[User guide](index.md) · [Validation and limitations](../limitations.md)

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
