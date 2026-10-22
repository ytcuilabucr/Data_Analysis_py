# Undo and redo

[User guide](index.md) · [Validation and limitations](../limitations.md)

Use **Edit → Undo / Redo**, **Cmd+Z / Cmd+Shift+Z** on macOS, or the platform's standard **Ctrl+Z / Ctrl+Y** (and supported Ctrl+Shift+Z) shortcuts. Menu labels describe the next action, such as a cell's dataset, row and channel, a rename, or a bulk group/visibility change. A text field that is still being edited retains its normal text-editing shortcuts; committed table edits enter the project history.

History covers editable-cell changes and rectangular pastes, dataset rename, grouping, removal, visibility (including automatic showing after a channel change), imports, and editable-copy creation. A bulk action is one undo step. New undoable changes after Undo discard the old redo branch. No-op edits and canceled/invalid operations do not add history. Dataset IDs, source text, parent links, and raw read-only values are preserved. Undo removal restores dataset order, values, edits and fits; the original lineage safeguards still apply.

Undoing a cell edit restores the previous value, revision, and edit history. A fit is restored only if its revision and fitted observations match the restored data and its dataset provenance is unchanged. Redo restores that edit's revision/history and a matching fit, if one was calculated for that state; otherwise the fit stays invalidated. Fits from discarded redo branches are not reused. Undo/redo is disabled during background fitting.

Saving retains session history and marks its current position as clean. Undoing back to that position clears the modified marker unless there are other unsaved changes. Plot presentation changes and fitting are not undo commands; they remain tracked as unsaved changes until saved. Opening a project clears history, while persisted data revisions and edit provenance remain. Removed datasets and saved fit snapshots occupy memory until their history is discarded or the project closes; history itself is not written to JSON/HDF5.
