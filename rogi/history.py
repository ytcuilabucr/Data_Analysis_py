"""Session undo commands. Dataset objects and provenance retain their identity."""
from copy import deepcopy
import numpy as np
from PySide6.QtGui import QUndoCommand


def valid_fit(dataset, fit):
    """A restored fit must match the revision and the observations it fitted."""
    if not fit or fit.get('revision') != dataset.revision:
        return None
    try:
        rows = np.asarray(fit['rows'], dtype=int)
        if np.any(rows < 0) or np.any(rows >= len(dataset.values)):
            return None
        if (not np.array_equal(dataset.values[rows, fit['xcol']], fit['x'])
                or not np.array_equal(dataset.values[rows, fit['ycol']], fit['observed'])):
            return None
    except (KeyError, IndexError, TypeError, ValueError):
        return None
    return deepcopy(fit)


class ChangeCommand(QUndoCommand):
    def __init__(self, window, label, redo, undo):
        super().__init__(label)
        self.window, self.apply, self.revert = window, redo, undo

    def run(self, operation):
        self.window.replaying = True
        try:
            operation()
            self.window.refresh_history_view()
        finally:
            self.window.replaying = False

    def redo(self):
        self.run(self.apply)

    def undo(self):
        self.run(self.revert)


class CellsCommand(ChangeCommand):
    def __init__(self, window, dataset, changes, label):
        self.dataset = dataset
        self.rows = np.array([r for r, c, value in changes], dtype=int)
        self.columns = np.array([c for r, c, value in changes], dtype=int)
        self.before_values = dataset.values[self.rows, self.columns].copy()
        self.after_values = np.array([value for r, c, value in changes], dtype=float)
        self.before_revision = dataset.revision
        self.before_edits = deepcopy(dataset.edits)
        self.before_fit = valid_fit(dataset, dataset.fit)
        self.after_fit = None
        self.after_edits = self.before_edits + [
            dict(row=r, column=c, old=None if np.isnan(old) else float(old),
                 new=None if np.isnan(value) else float(value))
            for (r, c, value), old in zip(changes, self.before_values)]
        self.provenance = (dataset.id, dataset.parent, dataset.source, dataset.source_text)
        super().__init__(window, label, self.apply_cells, self.revert_cells)

    def restore(self, values, revision, edits, fit):
        d = self.dataset
        # Commands never unlock raw arrays or rewrite source/parent metadata.
        if d.raw:
            raise ValueError("Raw data is read-only.")
        d.values[self.rows, self.columns] = values
        d.revision = revision
        d.edits = deepcopy(edits)
        same_origin = self.provenance == (d.id, d.parent, d.source, d.source_text)
        d.fit = valid_fit(d, fit) if same_origin else None

    def apply_cells(self):
        self.before_fit = valid_fit(self.dataset, self.dataset.fit)
        self.restore(self.after_values, self.before_revision + len(self.rows), self.after_edits, self.after_fit)

    def revert_cells(self):
        self.after_fit = valid_fit(self.dataset, self.dataset.fit)
        self.restore(self.before_values, self.before_revision, self.before_edits, self.before_fit)


class CellCommand(CellsCommand):
    def __init__(self, window, dataset, row, column, value):
        super().__init__(window, dataset, [(row, column, value)],
                         f"Edit {dataset.name}, row {row + 1}, {dataset.columns[column]}")
