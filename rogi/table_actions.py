"""Table workflows coordinated by MainWindow.

Functions receive the window explicitly to preserve ordering across history,
selection and presentation. They are not panel components; extracted panels
communicate with the window through their signals and data arguments.
"""
import numpy as np
from PySide6 import QtCore as C, QtWidgets as W
from .browser_panel import BrowserItem
from .history import CellCommand, CellsCommand
from .clipboard import MIME, selection_rectangle, copy_table, parse_paste


class DataTable(C.QAbstractTableModel):
    edited = C.Signal()
    failed = C.Signal(str)

    def __init__(self, dataset, edit_callback=None):
        super().__init__()
        self.dataset = dataset
        self.edit_callback = edit_callback

    def rowCount(self, parent=C.QModelIndex()):
        return 0 if parent.isValid() else len(self.dataset.values)

    def columnCount(self, parent=C.QModelIndex()):
        return 0 if parent.isValid() else len(self.dataset.columns)

    def data(self, index, role=C.Qt.ItemDataRole.DisplayRole):
        if index.isValid() and role in (C.Qt.ItemDataRole.DisplayRole, C.Qt.ItemDataRole.EditRole):
            value = self.dataset.values[index.row(), index.column()]
            return "" if np.isnan(value) else str(value)

    def headerData(self, section, orientation, role=C.Qt.ItemDataRole.DisplayRole):
        if role == C.Qt.ItemDataRole.DisplayRole:
            return self.dataset.columns[section] if orientation == C.Qt.Orientation.Horizontal else str(section+1)

    def flags(self, index):
        flags = super().flags(index)
        return flags if self.dataset.raw else flags | C.Qt.ItemFlag.ItemIsEditable

    def setData(self, index, value, role=C.Qt.ItemDataRole.EditRole):
        if role != C.Qt.ItemDataRole.EditRole or not index.isValid():
            return False
        try:
            if self.edit_callback:
                self.edit_callback(self.dataset, index.row(), index.column(), value)
            else:
                self.dataset.edit(index.row(), index.column(), value)
        except ValueError as error:
            self.failed.emit(str(error))
            return False
        self.dataChanged.emit(index, index)
        if not self.edit_callback:
            self.edited.emit()
        return True



def refresh_history_view(self):
    table_model = self.table.model()
    table_dataset_id = table_model.dataset.id if table_model else None
    table_ranges = [(r.top(), r.left(), r.bottom(), r.right())
                    for r in self.table.selectionModel().selection()] if table_model else []
    table_current = self.table.currentIndex()
    current_cell = (table_current.row(), table_current.column()) if table_current.isValid() else None
    selected = getattr(self, 'history_selection', {d.id for d in self.selected_datasets() if d})
    if hasattr(self, 'history_selection'):
        del self.history_selection
    item = self.browser.currentItem()
    current_id = item.data(C.Qt.ItemDataRole.UserRole) if item else None
    # Keep existing items alive while Qt handles a checkbox mouse event.
    # Replacing them mid-event loses the active row and clears channel controls.
    existing = {self.browser.item(row).data(C.Qt.ItemDataRole.UserRole): self.browser.item(row)
                for row in range(self.browser.count())}
    rebuild = set(existing) != {d.id for d in self.datasets}
    with C.QSignalBlocker(self.browser):
        if rebuild:
            self.browser.clear()
        for row, d in enumerate(self.datasets):
            item = BrowserItem(self.browser) if rebuild else existing[d.id]
            item.setData(C.Qt.ItemDataRole.UserRole, d.id)
            self.update_browser_item(item, d)
            item.setFlags(item.flags() | C.Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(C.Qt.CheckState.Checked if d.visible else C.Qt.CheckState.Unchecked)
            item.setSelected(d.id in selected)
            if d.id == current_id:
                self.browser.setCurrentItem(item, C.QItemSelectionModel.SelectionFlag.NoUpdate)
        if self.browser.currentItem() is None:
            items = self.browser.selectedItems()
            if items:
                self.browser.setCurrentItem(items[0], C.QItemSelectionModel.SelectionFlag.NoUpdate)
    if self.browser.sorted_column is not None:
        self.browser.sortItems(self.browser.sorted_column, self.browser.sort_order)
    self.update_groups()
    self.filter_browser()
    model = self.table.model()
    if model and model.dataset.id == table_dataset_id:
        selection = C.QItemSelection()
        for top, left, bottom, right in table_ranges:
            selection.select(model.index(top, left), model.index(bottom, right))
        self.table.selectionModel().select(selection, C.QItemSelectionModel.SelectionFlag.ClearAndSelect)
        if current_cell:
            self.table.selectionModel().setCurrentIndex(model.index(*current_cell), C.QItemSelectionModel.SelectionFlag.NoUpdate)
    self.redraw()


def set_table_shown(self, shown, remember=True):
    """The data table is optional; hidden, the file window shrinks to the dataset list."""
    if remember:
        self.preferences.setValue('data_table_shown', shown)
    self.table.setVisible(shown)
    self.show_table_button.setText("Hide data table" if shown else "Show data table")
    self.fit_file_window()


def update_clipboard_actions(self, *args):
    model = self.table.model()
    selected = bool(self.table.selectionModel() and self.table.selectionModel().hasSelection())
    busy = bool(self.worker and self.worker.isRunning())
    self.copy_action.setEnabled(bool(model and selected and not busy))
    self.paste_action.setEnabled(bool(model and selected and not model.dataset.raw and not busy))


def copy_selection(self):
    model = self.table.model()
    if model is None:
        raise ValueError("Select a dataset first.")
    rectangle = selection_rectangle(self.table.selectionModel().selectedIndexes())
    text = copy_table(model.dataset, rectangle)
    mime = C.QMimeData()
    mime.setText(text)
    mime.setData(MIME, text.encode('utf-8'))
    W.QApplication.clipboard().setMimeData(mime)
    self.statusBar().showMessage("Copied table selection with column headers.", 3000)


def select_table_block(self, top, left, height, width):
    model = self.table.model()
    selection = C.QItemSelection(model.index(top, left), model.index(top + height - 1, left + width - 1))
    self.table.selectionModel().select(selection, C.QItemSelectionModel.SelectionFlag.ClearAndSelect)
    self.table.selectionModel().setCurrentIndex(model.index(top, left), C.QItemSelectionModel.SelectionFlag.NoUpdate)


def paste_selection(self):
    if self.worker and self.worker.isRunning():
        raise ValueError("Wait for the current fit to finish before pasting.")
    model = self.table.model()
    if model is None:
        raise ValueError("Select a dataset first.")
    top, left, _, _ = selection_rectangle(self.table.selectionModel().selectedIndexes())
    mime = W.QApplication.clipboard().mimeData()
    text = mime.text()
    copied_headers = mime.hasFormat(MIME) and bytes(mime.data(MIME)) == text.encode('utf-8')
    values = parse_paste(model.dataset, text, top, left, copied_headers)
    d = model.dataset
    changes = []
    for r, row in enumerate(values):
        for c, value in enumerate(row):
            old = d.values[top + r, left + c]
            if old != value and not (np.isnan(old) and np.isnan(value)):
                changes.append((top + r, left + c, value))
    if changes:
        self.history.push(CellsCommand(
            self, d, changes, f"Paste {values.shape[0]} × {values.shape[1]} cells into {d.name}"))
    self.select_table_block(top, left, *values.shape)
    self.statusBar().showMessage(f"Pasted {values.shape[0]} × {values.shape[1]} cells; {len(changes)} changed.", 4000)


def edit_cell(self, dataset, row, column, text):
    if dataset.raw:
        raise ValueError("Raw data is read-only. Create an editable copy first.")
    value = float(text) if str(text).strip() else np.nan
    if np.isinf(value):
        raise ValueError("Use a finite number or a blank for missing data.")
    old = dataset.values[row, column]
    if old == value or (np.isnan(old) and np.isnan(value)):
        return
    self.history.push(CellCommand(self, dataset, row, column, value))


def select(self, row):
    dataset = self.current()
    self.refresh_statistics()
    if dataset is None:
        if not getattr(self, 'redraw_deferred', False):
            self.image_viewer.set_context(self.datasets, None)
        self.table.setModel(None)
        self.update_clipboard_actions()
        self.result.clear()
        self.info.setText("Select a dataset to inspect it.")
        self.loading = True
        self.x.clear()
        self.y.clear()
        self.loading = False
        return
    pair = self.panels[self.active_panel]['channels']
    if not self.opening and pair and dataset.id in pair and max(pair[dataset.id]) < len(dataset.columns):
        dataset.xcol, dataset.ycol = pair[dataset.id]
    self.loading = True
    for combo, index in [(self.x, dataset.xcol), (self.y, dataset.ycol)]:
        combo.clear()
        combo.addItems(dataset.columns)
        combo.setCurrentIndex(index)
    self.style.setCurrentText(dataset.style)
    self.color.setText(dataset.color or "Automatic color")
    self.marker.setCurrentIndex(self.marker.findData(dataset.marker))
    table_model = DataTable(dataset, self.edit_cell)
    table_model.edited.connect(self.edited)
    table_model.failed.connect(self.error)
    self.table_model = table_model
    self.table.setModel(table_model)
    self.table.selectionModel().selectionChanged.connect(self.update_clipboard_actions)
    self.update_clipboard_actions()
    missing = int(np.isnan(dataset.values).sum())
    self.info.setText(f"{dataset.name}\n{len(dataset.values)} rows × {len(dataset.columns)} channels; {missing} missing cells\n"
                      + ("Raw data: read-only" if dataset.raw else f"Editable data: revision {dataset.revision}"))
    self.info.setToolTip(f'{dataset.name}\nParent: {dataset.parent or "None"}')
    self.reset_fit_range(dataset, restore_fit=True)
    if dataset.fit:
        self.model.setCurrentText(dataset.fit['model'])
    self.loading = False
    self.show_result()
    self.redraw()


def edited(self):
    self.changed()
    self.select(self.browser.currentRow())


