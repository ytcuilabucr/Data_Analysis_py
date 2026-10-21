"""Qt desktop presentation. Numerical routines live in core.py."""
import csv
import io
import sys
from copy import deepcopy, copy
from pathlib import Path

# PyCharm's file run configuration executes this without a package context.
if __name__ == "__main__" and not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    __package__ = "rogi"

import numpy as np
from PySide6 import QtCore as C, QtWidgets as W, QtGui as G
from matplotlib.figure import Figure
from .navigation import PlotNavigationToolbar
from matplotlib.transforms import Bbox
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.widgets import SpanSelector, Cursor, RectangleSelector
from .browser_panel import BrowserPanel, BrowserState, BrowserItem, DatasetBrowser, populate_group_tree
from .plot_controls_panel import PlotControlsPanel
from .fitting_panel import FittingPanel, FitWorker
from . import project_actions as project_commands
from .dialogs import ImportDialog, SpmImportDialog, ImportGroupDialog, MetadataGroupingDialog, MetadataDialog
from .history import ChangeCommand, CellCommand, CellsCommand
from .grouping import group_path, path_key, path_label, node_label, partitions, varying_fields, field_labels, import_destinations
from .spm import load_spm
from .scanfile import bundle_channels, consolidate_legacy
from .images import ImageViewer
from .metadata import attach_spectrum_metadata, metadata_fields, metadata_search_text, acquisition_timestamp, channel_count
from .clipboard import MIME, selection_rectangle, copy_table, parse_paste
from .plotting import MARKERS, LEGENDS, validate_view, display_values
from .core import Dataset, parse_text, spectrum_table, fit_dataset, export_data, export_fit, remove_datasets
from .core import region_statistics
from .project import save_project, load_project, convert_folder


def project_preferences():
    return C.QSettings('Rogi', 'Rogi')






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
















class MainWindow(W.QMainWindow):
    def __init__(self):
        super().__init__()
        self._build_state()
        self._build_menus()
        splitter = W.QSplitter()
        self.setCentralWidget(splitter)
        self._build_browser(splitter)
        self._build_center(splitter)
        layout = self._build_analysis_container(splitter)
        self._build_channels(layout)
        self._build_plot_controls(layout)
        self._build_statistics(layout)
        self._build_fitting(layout)
        self._build_connections()

    @property
    def datasets(self):
        return self.browser_state.datasets

    @datasets.setter
    def datasets(self, value):
        self.browser_state.datasets = value

    @property
    def loading(self):
        return self.browser_state.loading

    @loading.setter
    def loading(self, value):
        self.browser_state.loading = value

    def _build_state(self):
        self.browser_state = BrowserState()
        self.datasets = []
        self.path = None
        self.preferences = project_preferences()
        self.saved_views = {}
        self.pipeline_presets = {}
        self.dirty = False
        self.external_dirty = False
        self.replaying = False
        self.opening = False
        self.worker = None
        self.loading = False
        self.drawing = False
        self.view = {axis: dict(scale='linear', auto=True, limits=None) for axis in ('x', 'y', 'resy')}
        self.panels = [dict(channels=None, view=self.view)]
        self.active_panel = 0
        self.sync_x = False
        self.panel_axes = []
        self.limit_callbacks = []
        self.stats_region = None
        self.stats_context = None
        self.setWindowTitle("Rogi — Scientific Analysis")
        self.resize(1280, 850)
        self.history = G.QUndoStack(self)

    def _build_menus(self):
        return project_commands._build_menus(self)

    def _build_browser(self, splitter):
        self.browser_panel = BrowserPanel(self.browser_state)
        self.browser_panel.selection_requested.connect(self.select)
        self.browser_panel.action_requested.connect(
            lambda name, args: self.guard(lambda: getattr(self, name)(*args)))
        self.browser_panel.attributes_requested.connect(self.change_attributes)
        self.browser = self.browser_panel.browser
        self.date_from = self.browser_panel.date_from
        self.date_to = self.browser_panel.date_to
        self.favorites_filter = self.browser_panel.favorites_filter
        self.group_filter = self.browser_panel.group_filter
        self.group_tree = self.browser_panel.group_tree
        self.metadata_filter = self.browser_panel.metadata_filter
        self.organization_actions = self.browser_panel.organization_actions
        self.search = self.browser_panel.search
        self.selection_info = self.browser_panel.selection_info
        self.tag_filter = self.browser_panel.tag_filter
        splitter.addWidget(self.browser_panel)

    def _build_center(self, splitter):
        center = W.QSplitter(C.Qt.Orientation.Vertical)
        splitter.addWidget(center)
        plot_widget = W.QWidget()
        plot_layout = W.QVBoxLayout(plot_widget)
        self.figure = Figure(figsize=(8, 6), layout='constrained')
        self.ax, self.resax = self.figure.subplots(2, 1, sharex=True, gridspec_kw={'height_ratios': [3, 1]})
        self.fit_plot_spec = self.ax.get_subplotspec()
        self.full_plot_spec = self.figure.add_gridspec(1, 1)[0]
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.navigation = PlotNavigationToolbar(self.canvas, self)
        plot_layout.addWidget(self.navigation)
        plot_layout.addWidget(self.canvas)
        self.plot_tabs = W.QTabWidget()
        self.plot_tabs.addTab(plot_widget, 'Line plot')
        self.image_viewer = ImageViewer(self)
        self.image_viewer.profile_created.connect(self.add_dataset)
        self.image_viewer.preview_requested.connect(lambda name: self.guard(lambda: self.preview_image_preset(name)))
        self.plot_tabs.addTab(self.image_viewer, '2D Map')
        self.plot_tabs.currentChanged.connect(self.plot_tab_changed)
        center.addWidget(self.plot_tabs)
        self.table = W.QTableView()
        self.table.setSelectionMode(W.QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setSelectionBehavior(W.QAbstractItemView.SelectionBehavior.SelectItems)
        self.copy_action = G.QAction("Copy table selection with headers", self.table)
        self.paste_action = G.QAction("Paste numeric block", self.table)
        for action, key, function in (
                (self.copy_action, G.QKeySequence.StandardKey.Copy, self.copy_selection),
                (self.paste_action, G.QKeySequence.StandardKey.Paste, self.paste_selection)):
            action.setShortcuts(G.QKeySequence.keyBindings(key))
            action.setShortcutContext(C.Qt.ShortcutContext.WidgetWithChildrenShortcut)
            action.triggered.connect(lambda checked=False, fn=function: self.guard(fn))
            self.table.addAction(action)
            self.edit_menu.addAction(action)
            action.setEnabled(False)
        center.addWidget(self.table)
        self.image_viewer.show_table.toggled.connect(self.update_table_visibility)
        center.setSizes([580, 220])

    def _build_analysis_container(self, splitter):
        panel = W.QWidget()
        layout = W.QVBoxLayout(panel)
        panel_scroll = W.QScrollArea()
        self.analysis_panel = panel_scroll
        panel_scroll.setWidgetResizable(True)
        panel_scroll.setWidget(panel)
        panel_scroll.setMinimumWidth(380)
        panel_scroll.setMaximumWidth(400)
        splitter.addWidget(panel_scroll)
        splitter.setSizes([420, 680, 380])
        return layout

    def _build_channels(self, layout):
        self.plot_controls = PlotControlsPanel(layout)
        self.info = self.plot_controls.info
        self.x = self.plot_controls.x
        self.y = self.plot_controls.y
        self.panel_choice = self.plot_controls.panel_choice
        self.sync_x_control = self.plot_controls.sync_x_control
        self.style = self.plot_controls.style
        self.title = self.plot_controls.title
        self.xlabel = self.plot_controls.xlabel
        self.ylabel = self.plot_controls.ylabel
        self.plot_panel = self.plot_controls.plot_panel
        self.axis_controls = self.plot_controls.axis_controls
        self.color = self.plot_controls.color
        self.marker = self.plot_controls.marker
        self.legend_position = self.plot_controls.legend_position
        self.cursor_enabled = self.plot_controls.cursor_enabled
        self.log_notice = self.plot_controls.log_notice
        self.coordinates = self.plot_controls.coordinates
        self.plot_controls.activate_panel_requested.connect(self.activate_panel)
        self.plot_controls.add_panel_requested.connect(self.add_panel)
        self.plot_controls.assign_panel_channel_requested.connect(self.assign_panel_channel)
        self.plot_controls.unassign_panel_channel_requested.connect(self.unassign_panel_channel)
        self.plot_controls.remove_panel_requested.connect(self.remove_panel)
        self.plot_controls.set_sync_x_requested.connect(self.set_sync_x)
        self.plot_controls.apply_axes_requested.connect(lambda: self.guard(self.apply_axes))
        self.plot_controls.choose_color_requested.connect(self.choose_color)
        self.plot_controls.set_color_requested.connect(self.set_color)
        self.plot_controls.appearance_changed_requested.connect(self.appearance_changed)
        self.plot_controls.presentation_changed_requested.connect(self.presentation_changed)

    def _build_plot_controls(self, layout):
        self.show_plot_controls.toggled.connect(self.plot_panel.setVisible)
        self.statusBar().addPermanentWidget(self.coordinates)
        self.canvas.mpl_connect('motion_notify_event', self.cursor_motion)
        self.sync_axis_controls()

    def _build_statistics(self, layout):
        self.stats_panel = W.QGroupBox("Statistics — active dataset Y")
        stats_layout = W.QFormLayout(self.stats_panel)
        self.stats_mode = W.QComboBox()
        self.stats_mode.addItems(["X range", "Rectangle"])
        stats_layout.addRow("Region", self.stats_mode)
        self.stats_bounds = [W.QLineEdit() for _ in range(4)]
        for label, field in zip(("X minimum", "X maximum", "Y minimum", "Y maximum"), self.stats_bounds):
            field.setAccessibleName("Statistics " + label)
            stats_layout.addRow(label, field)
        self.stats_sample = W.QComboBox()
        self.stats_sample.addItems(["Sample (N − 1)", "Population (N)"])
        stats_layout.addRow("Std / variance", self.stats_sample)
        self.stats_drag = W.QCheckBox("Drag on plot to select")
        stats_layout.addRow(self.stats_drag)
        self.stats_calculate = W.QPushButton("Calculate statistics")
        self.stats_calculate.clicked.connect(lambda: self.guard(self.calculate_statistics))
        stats_layout.addRow(self.stats_calculate)
        self.stats_result = W.QPlainTextEdit()
        self.stats_result.setReadOnly(True)
        self.stats_result.setMinimumHeight(220)
        stats_layout.addRow(self.stats_result)
        layout.addWidget(self.stats_panel)
        self.stats_panel.hide()
        self.show_statistics.toggled.connect(self.toggle_statistics)
        self.stats_mode.currentIndexChanged.connect(self.statistics_mode_changed)
        self.stats_sample.currentIndexChanged.connect(self.refresh_statistics)
        self.stats_drag.toggled.connect(self.toggle_statistics_drag)
        for field in self.stats_bounds[2:]:
            field.setEnabled(False)

    def _build_fitting(self, layout):
        self.fit_panel = FittingPanel()
        layout.addWidget(self.fit_panel)
        layout.addStretch()
        self.fit_panel.drag_changed.connect(self.toggle_span)
        self.fit_panel.fit_requested.connect(lambda: self.guard(self.start_fit))
        self.show_fitting.toggled.connect(self.toggle_fitting)
        self.model = self.fit_panel.model
        self.lower = self.fit_panel.lower
        self.upper = self.fit_panel.upper
        self.drag = self.fit_panel.drag
        self.exclude = self.fit_panel.exclude
        self.fitbutton = self.fit_panel.fitbutton
        self.result = self.fit_panel.result

    def _build_connections(self):
        self.browser.currentRowChanged.connect(self.select)
        self.browser.itemChanged.connect(lambda item, column: self.visibility(item) if column == 0 else None)
        for combo in (self.x, self.y, self.style):
            combo.currentIndexChanged.connect(self.plot_options)
        for entry in (self.title, self.xlabel, self.ylabel):
            entry.editingFinished.connect(self.labels_changed)
        self.selection_changed()
        self.redraw()

    def guard(self, function):
        try:
            return function()
        except (ValueError, OSError, csv.Error, UnicodeError) as error:
            self.error(str(error))
            return False

    def error(self, text):
        W.QMessageBox.warning(self, "Rogi", text)

    def current(self):
        return self.browser_panel.current()

    def dataset_for_item(self, item):
        return self.browser_panel.dataset_for_item(item)

    def selected_datasets(self):
        return self.browser_panel.selected_datasets()

    def selection_changed(self):
        return self.browser_panel.selection_changed()

    def select_all_shown(self):
        return self.browser_panel.select_all_shown()

    def update_groups(self):
        return self.browser_panel.update_groups()

    def select_group_node(self, item, column):
        return self.browser_panel.select_group_node(item, column)

    def filter_browser(self, *args):
        return self.browser_panel.filter_browser(*args)

    def update_browser_item(self, item, dataset):
        return self.browser_panel.update_browser_item(item, dataset)

    def display_group_path(self, path):
        return self.browser_panel.display_group_path(path)

    def annotate_selected(self, attribute, value):
        self.change_attributes(self.selected_datasets(), attribute, value, f'Edit {attribute}')

    def edit_tags(self):
        selected = self.selected_datasets()
        if not selected:
            return
        value, ok = W.QInputDialog.getText(self, 'Edit tags', 'Tags, comma separated (replaces selected tags):',
                                         text=', '.join(selected[0].tags) if len(selected) == 1 else '')
        if ok:
            self.annotate_selected('tags', list(dict.fromkeys(tag.strip() for tag in value.split(',') if tag.strip())))

    def edit_comments(self):
        selected = self.selected_datasets()
        if not selected:
            return
        value, ok = W.QInputDialog.getMultiLineText(self, 'Edit comments', 'Comments (replaces selected comments):',
                                                  selected[0].comments if len(selected) == 1 else '')
        if ok:
            self.annotate_selected('comments', value)

    def rename_dataset(self):
        selected = self.selected_datasets()
        if len(selected) != 1:
            return
        d = selected[0]
        name, ok = W.QInputDialog.getText(self, "Rename dataset", "Display name:", text=d.name)
        if not ok:
            return
        name = name.strip()
        if not name:
            raise ValueError("Dataset name cannot be blank.")
        if name != d.name:
            self.change_attributes([d], 'name', name, f'Rename {d.name} to {name}')

    def assign_group(self):
        if not self.selected_datasets():
            return
        groups = sorted({d.group for d in self.datasets if d.group}, key=str.casefold)
        group, ok = W.QInputDialog.getItem(self, "Assign group", "Group (blank = ungrouped):",
                                          groups, 0, True)
        if ok:
            self.set_selected_group(group.strip())

    def group_by_metadata(self):
        selected = self.selected_datasets()
        dialog = MetadataGroupingDialog(selected, self, all_datasets=self.datasets)
        if dialog.exec() == W.QDialog.DialogCode.Accepted:
            self.group_by_levels(dialog.datasets, dialog.levels, dialog.mode.currentIndex() == 1)

    def group_by_levels(self, datasets, levels, append=False):
        if not levels or not datasets:
            return
        pairs = partitions(datasets, levels, append)
        before = list(self.datasets)
        old = [(d, d.group, deepcopy(d.group_path)) for d, _ in pairs]
        ids = {d.id for d, _ in pairs}
        ordered = iter(d for d, _ in pairs)
        after = [next(ordered) if d.id in ids else d for d in before]
        def apply():
            for d, path in pairs:
                d.group_path = deepcopy(path)
                d.group = path_label(path)
            self.datasets[:] = after
        def revert():
            for d, label, path in old:
                d.group, d.group_path = label, deepcopy(path)
            self.datasets[:] = before
        self.history.push(ChangeCommand(self, 'Group by metadata levels', apply, revert))
        self.statusBar().showMessage(f'Grouped {len(pairs)} files into '
                                    f'{len({path_key(p) for _, p in pairs})} groups.', 6000)

    def group_selected_by_metadata(self, key, descending=False, datasets=None):
        self.group_by_levels(self.selected_datasets() if datasets is None else datasets,
                             [(key, descending)])

    def view_metadata(self):
        d = self.current()
        if d is None:
            raise ValueError("Select a dataset to inspect its metadata.")
        dialog = MetadataDialog(d, self)
        dialog.exec()

    def set_selected_group(self, group):
        selected = self.selected_datasets()
        label = f"Group {len(selected)} dataset(s) as {group}" if group else f"Ungroup {len(selected)} dataset(s)"
        self.change_attributes(selected, 'group', group, label)

    def change_attributes(self, datasets, attribute, value, label):
        changes = [(d, getattr(d, attribute)) for d in datasets
                   if getattr(d, attribute) != value or (attribute == 'group' and d.group_path)]
        if not changes:
            return
        old_paths = {d.id: deepcopy(d.group_path) for d, _ in changes} if attribute == 'group' else {}
        def apply():
            for d, old in changes:
                setattr(d, attribute, deepcopy(value))
                if attribute == 'group':
                    d.group_path = []
        def revert():
            for d, old in changes:
                setattr(d, attribute, deepcopy(old))
                if attribute == 'group':
                    d.group_path = deepcopy(old_paths[d.id])
        self.history.push(ChangeCommand(self, label, apply, revert))

    def set_selected_visibility(self, visible):
        selected = self.selected_datasets()
        self.change_attributes(selected, 'visible', visible,
                               f"{'Show' if visible else 'Hide'} {len(selected)} dataset(s)")

    def remove_selected(self):
        selected = self.selected_datasets()
        if not selected:
            return
        ids = {d.id for d in selected}
        remove_datasets(self.datasets, ids)  # Validate before confirmation.
        answer = W.QMessageBox.question(
            self, "Remove datasets",
            f"Remove {len(selected)} selected dataset(s) from this project?\n"
            + "\n".join(d.name for d in selected)
            + "\n\nTheir data, edits, and fits will be removed. Source files are untouched. Use Edit → Undo to restore them during this session.",
            W.QMessageBox.StandardButton.Yes | W.QMessageBox.StandardButton.Cancel,
            W.QMessageBox.StandardButton.Cancel)
        if answer != W.QMessageBox.StandardButton.Yes:
            return
        removed = [(i, d) for i, d in enumerate(self.datasets) if d.id in ids]
        def apply():
            self.datasets = remove_datasets(self.datasets, ids)
        def revert():
            for index, d in removed:
                self.datasets.insert(index, d)
            self.history_selection = ids
        self.history.push(ChangeCommand(self, f"Remove {len(removed)} dataset(s)", apply, revert))

    def update_dirty(self, *args):
        return project_commands.update_dirty(self, *args)

    def changed(self):
        return project_commands.changed(self)

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

    def add_dataset(self, dataset):
        def apply():
            self.datasets.append(dataset)
            self.history_selection = {dataset.id}
            # Keep the newly added dataset as the inspection target.
            with C.QSignalBlocker(self.browser):
                self.browser.setCurrentItem(None)
        def revert():
            self.datasets = remove_datasets(self.datasets, {dataset.id})
        if self.opening:
            apply()
            self.refresh_history_view()
        else:
            label = "Create analysis dataset" if dataset.analysis else ("Import" if dataset.raw else "Create editable copy")
            self.history.push(ChangeCommand(self, f"{label} {dataset.name}", apply, revert))

    def import_file(self):
        return project_commands.import_file(self)

    def convert_folder(self):
        return project_commands.convert_folder(self)

    def select(self, row):
        dataset = self.current()
        self.refresh_statistics()
        if dataset is None:
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

    def spectrum_map(self, recipe=None):
        from .maps_ui import MapDialog
        sources = self.selected_datasets()
        if recipe is not None:
            ids = recipe['ids']
            lookup = {d.id: d for d in self.datasets}
            if any(i not in lookup for i in ids):
                raise ValueError('A saved map source is missing. Reselect spectra to create a new map.')
            sources = [lookup[i] for i in ids]
        if not sources:
            raise ValueError('Select spectra in the dataset browser first.')
        dialog = MapDialog(sources, self, recipe)
        dialog.exec()

    def analysis_pipeline(self):
        if self.current():
            from .analysis_ui import AnalysisDialog, MultiAnalysisDialog
            selected = self.selected_datasets()
            dialog = MultiAnalysisDialog(selected, self) if len(selected) > 1 else AnalysisDialog(self.current(), self, self.pipeline_presets, self.pipeline_presets_changed)
            if dialog.exec() == W.QDialog.DialogCode.Accepted:
                for result in dialog.datasets if len(selected) > 1 else [dialog.dataset]:
                    self.add_dataset(result)

    def add_analysis_batch(self, results):
        if not results:
            return
        def apply():
            self.datasets.extend(results)
            self.history_selection = {d.id for d in results}
        def revert():
            self.datasets = remove_datasets(self.datasets, {d.id for d in results})
        self.history.push(ChangeCommand(self, f'Apply pipeline to {len(results)} datasets', apply, revert))

    def pipeline_presets_changed(self):
        self.image_viewer.set_presets(self.pipeline_presets)
        self.changed()

    def preview_image_preset(self, name):
        from .image_analysis import ImagePreviewDialog
        from .presets import validate_presets
        source = self.image_viewer.current
        if source is None:
            raise ValueError('Select an image file and channel in 2D Map first.')
        if name not in self.pipeline_presets:
            raise ValueError('The selected preset is no longer available.')
        validate_presets({name: self.pipeline_presets[name]})
        dialog = ImagePreviewDialog(source, self.pipeline_presets[name], name, self,
                                    palette=self.image_viewer.palette.currentText(),
                                    transpose=self.image_viewer.transpose.isChecked())
        try:
            dialog.exec()
        finally:
            dialog.deleteLater()

    def apply_pipeline_preset(self):
        from .analysis_ui import BatchPipelineDialog
        selected = self.selected_datasets()
        if not selected:
            raise ValueError('Select datasets in the browser first.')
        dialog = BatchPipelineDialog(selected, self.pipeline_presets, self)
        if dialog.exec() == W.QDialog.DialogCode.Accepted:
            self.add_analysis_batch(dialog.datasets)

    def reopen_analysis_recipe(self):
        from .analysis_ui import AnalysisDialog
        result = self.current()
        if result is None or not result.analysis or result.analysis.get('version') != 1:
            raise ValueError('Select a result from a single-signal analysis pipeline.')
        record = result.analysis
        source = next((d for d in self.datasets if d.id == record['source']['dataset_id']), None)
        if source is None:
            raise ValueError('The source dataset is unavailable. Its recipe cannot be reopened against the source.')
        dialog = AnalysisDialog(source, self, self.pipeline_presets, self.pipeline_presets_changed)
        dialog.load_operations(record['operations'])
        for axis in ('x', 'y'):
            channel = record['input_channels'][axis]
            if channel['index'] >= len(source.columns) or source.columns[channel['index']] != channel['name']:
                raise ValueError('The original input channels are unavailable.')
            getattr(dialog, axis + 'channel').setCurrentIndex(channel['index'])
            getattr(dialog, axis + 'unit').setText(channel['unit'])
        dialog.name.setText(result.name + ' (rerun)')
        if source.revision != record['source']['revision']:
            dialog.status.setText(f"Source changed: recorded revision {record['source']['revision']}, current revision {source.revision}. Preview will use current data.")
        else:
            dialog.status.setText('Saved recipe loaded against its source. Edit or save a preset, then preview to create a new result.')
        if dialog.exec() == W.QDialog.DialogCode.Accepted:
            self.add_dataset(dialog.dataset)

    def make_copy(self):
        if self.current():
            self.add_dataset(self.current().derived())

    def activate_dataset(self, dataset_id):
        return self.browser_panel.activate_dataset(dataset_id)

    def visibility(self, item):
        return self.browser_panel.visibility(item)

    def panel_datasets(self, panel):
        if panel['channels'] is None:
            return self.datasets
        result = []
        for d in self.datasets:
            pair = panel['channels'].get(d.id)
            if pair and max(pair) < len(d.columns):
                plotted = copy(d)
                plotted.xcol, plotted.ycol = pair
                result.append(plotted)
        return result

    def freeze_default_panel(self):
        for panel in self.panels:
            if panel['channels'] is None:
                panel['channels'] = {d.id: [d.xcol, d.ycol] for d in self.datasets}

    def refresh_panels(self):
        with C.QSignalBlocker(self.panel_choice):
            self.panel_choice.clear()
            self.panel_choice.addItems([f'Panel {i + 1}' for i in range(len(self.panels))])
            self.panel_choice.setCurrentIndex(self.active_panel)
        self.view = self.panels[self.active_panel]['view']
        with C.QSignalBlocker(self.ylabel):
            self.ylabel.setText(self.panels[self.active_panel].get('ylabel', ''))

    def add_panel(self):
        d = self.current()
        self.freeze_default_panel()
        channels = {d.id: [d.xcol, d.ycol]} if d else {}
        self.panels.append(dict(channels=channels, view={
            axis: dict(scale='linear', auto=True, limits=None) for axis in ('x', 'y', 'resy')}))
        self.activate_panel(len(self.panels) - 1)

    def assign_panel_channel(self):
        d = self.current()
        if d:
            self.freeze_default_panel()
            self.panels[self.active_panel]['channels'][d.id] = [d.xcol, d.ycol]
            self.changed()
            self.redraw()

    def unassign_panel_channel(self):
        d = self.current()
        if d:
            self.freeze_default_panel()
            self.panels[self.active_panel]['channels'].pop(d.id, None)
            self.changed()
            self.redraw()

    def remove_panel(self):
        if len(self.panels) > 1:
            self.panels.pop(self.active_panel)
            self.activate_panel(min(self.active_panel, len(self.panels) - 1))

    def activate_panel(self, index):
        if index < 0 or self.loading:
            return
        self.active_panel = index
        self.refresh_panels()
        channels = self.panels[index]['channels']
        d = self.current()
        if channels:
            if d is None or d.id not in channels:
                d = next((d for d in self.datasets if d.id in channels), None)
            if d and max(channels[d.id]) < len(d.columns):
                d.xcol, d.ycol = channels[d.id]
                self.activate_dataset(d.id)
                self.select(self.browser.currentRow())
        self.sync_axis_controls()
        self.navigation.update()
        self.changed()
        self.redraw()

    def set_sync_x(self, enabled):
        self.sync_x = enabled
        self.changed()
        self.redraw()

    def restore_panels(self, settings):
        self.panels = deepcopy(settings.get('panels', [dict(channels=None, view=self.view, ylabel=settings.get('ylabel', ''))]))
        self.active_panel = settings.get('active_panel', 0)
        self.sync_x = settings.get('sync_x', False)
        with C.QSignalBlocker(self.sync_x_control):
            self.sync_x_control.setChecked(self.sync_x)
        self.refresh_panels()
        d = self.current()
        channels = self.panels[self.active_panel]['channels']
        if d and channels and d.id in channels and max(channels[d.id]) < len(d.columns):
            d.xcol, d.ycol = channels[d.id]
        if d:
            self.select(self.browser.currentRow())

    def plot_options(self):
        if self.loading or not self.current():
            return
        d = self.current()
        x_changed = d.xcol != self.x.currentIndex()
        channels_changed = x_changed or d.ycol != self.y.currentIndex()
        d.xcol, d.ycol, d.style = self.x.currentIndex(), self.y.currentIndex(), self.style.currentText()
        if self.panels[self.active_panel]['channels'] is not None:
            self.panels[self.active_panel]['channels'][d.id] = [d.xcol, d.ycol]
        if channels_changed and not d.visible:
            previous = [(dataset, dataset.visible) for dataset in self.datasets]
            def show_only():
                for dataset, visible in previous:
                    dataset.visible = dataset is d
            def restore_visibility():
                for dataset, visible in previous:
                    dataset.visible = visible
            self.history.push(ChangeCommand(self, f"Show only {d.name} after channel change",
                                            show_only, restore_visibility))
            self.statusBar().showMessage(f'Showing only {d.name}. Check other datasets to compare.', 5000)
        if x_changed:
            self.reset_fit_range(d)
        self.changed()
        self.show_result()
        self.redraw()

    def reset_fit_range(self, dataset, restore_fit=False):
        return self.fit_panel.reset_fit_range(dataset, restore_fit)

    def labels_changed(self):
        self.panels[self.active_panel]['ylabel'] = self.ylabel.text()
        self.changed()
        self.redraw()

    def toggle_fitting(self, visible):
        self.fit_panel.setVisible(visible)
        self.export_fit_action.setVisible(visible)
        if not visible:
            self.drag.setChecked(False)
        self.changed()
        self.redraw()

    def toggle_span(self, active):
        if active:
            self.stats_drag.setChecked(False)
            self.disable_navigation()
        if hasattr(self, 'span'):
            self.span.set_active(active)

    def range_selected(self, lower, upper):
        return self.fit_panel.range_selected(lower, upper)

    def disable_navigation(self):
        if self.navigation.mode == 'pan/zoom':
            self.navigation.pan()
        elif self.navigation.mode == 'zoom rect':
            self.navigation.zoom()

    def toggle_statistics(self, visible):
        self.stats_panel.setVisible(visible)
        if not visible:
            self.stats_drag.setChecked(False)
        self.refresh_statistics()
        self.redraw()

    def statistics_mode_changed(self, *args):
        for field in self.stats_bounds[2:]:
            field.setEnabled(self.stats_mode.currentIndex() == 1)
        self.stats_region = None
        self.stats_result.setPlainText("Select a region or enter bounds, then calculate.")
        self.redraw()

    def toggle_statistics_drag(self, active):
        if active:
            self.drag.setChecked(False)
            self.disable_navigation()
            d = self.current()
            if d and not d.visible:
                self.statusBar().showMessage("Check the active dataset to see its curve while selecting.", 5000)
        self.redraw()

    def statistics_selected(self, lower, upper, ylower=None, yupper=None):
        bounds = (lower, upper, ylower, yupper)
        for field, value in zip(self.stats_bounds, bounds):
            if value is not None:
                field.setText(f"{value:.17g}")
        self.guard(self.calculate_statistics)

    def statistics_rectangle_selected(self, press, release):
        if None not in (press.xdata, press.ydata, release.xdata, release.ydata):
            self.statistics_selected(*sorted((press.xdata, release.xdata)),
                                     *sorted((press.ydata, release.ydata)))

    def calculate_statistics(self):
        d = self.current()
        if d is None:
            raise ValueError("Select an active dataset first.")
        bounds = [float(field.text()) for field in self.stats_bounds[:2]]
        bounds += ([float(field.text()) for field in self.stats_bounds[2:]]
                   if self.stats_mode.currentIndex() else [None, None])
        # Validate before replacing a previous valid selection.
        region_statistics(d, *bounds, sample=self.stats_sample.currentIndex() == 0)
        self.stats_context = (d.id, d.xcol, d.ycol)
        self.stats_region = tuple(bounds)
        self.refresh_statistics()
        self.redraw()

    def refresh_statistics(self, *args):
        d = self.current()
        context = (d.id, d.xcol, d.ycol) if d else None
        if context != self.stats_context:
            self.stats_context = context
            self.stats_region = None
            for field in self.stats_bounds:
                field.clear()
        if not d or self.stats_region is None:
            self.stats_result.setPlainText("Select a dataset and drag a region, or enter bounds and calculate.")
            return
        result = region_statistics(d, *self.stats_region, sample=self.stats_sample.currentIndex() == 0)
        lo, hi, ylo, yhi = self.stats_region
        lines = [d.name, f"Y: {d.columns[d.ycol]} · X: {d.columns[d.xcol]}",
                 f"X range: [{lo:.8g}, {hi:.8g}] (inclusive)"]
        if ylo is not None:
            lines.append(f"Y range: [{ylo:.8g}, {yhi:.8g}] (inclusive)")
        lines += [f"Count: {result['count']}",
                  f"Missing X (whole dataset): {result['missing_x']}",
                  f"Missing Y within X range: {result['missing_y']}",
                  "Std / variance: " + ("sample (N − 1)" if result['sample'] else "population (N)")]
        for key, label in (('minimum', 'Minimum'), ('maximum', 'Maximum'), ('mean', 'Mean'),
                           ('median', 'Median'), ('std', 'Standard deviation'), ('variance', 'Variance'),
                           ('sem', 'Standard error of mean'), ('sum', 'Sum'), ('rms', 'RMS'),
                           ('q1', '25th percentile'), ('q3', '75th percentile')):
            value = result[key]
            lines.append(f"{label}: " + (f"{value:.10g}" if value is not None else "N/A"))
        lines += ["N/A: insufficient observations or result outside numeric range.",
                  "Stored values, not fitted/interpolated points. Log-hidden values are included if within bounds."]
        self.stats_result.setPlainText("\n".join(lines))

    def sync_axis_controls(self):
        self.plot_controls.sync_axis_controls(self.view)

    def apply_axes(self):
        proposed = self.plot_controls.read_axes()
        self.view.update(proposed)
        # Applying automatic axes also resets any residual-panel zoom.
        self.view['resy'] = dict(scale='linear', auto=True, limits=None)
        self.changed()
        self.redraw()
        self.navigation.update()


    def choose_color(self):
        if self.current():
            color = W.QColorDialog.getColor(parent=self, title="Dataset color")
            if color.isValid():
                self.set_color(color.name())

    def set_color(self, color):
        if self.current() and self.current().color != color:
            self.current().color = color
            self.color.setText(color or "Automatic color")
            self.changed()
            self.redraw()

    def appearance_changed(self):
        if not self.loading and self.current():
            self.current().marker = self.marker.currentData()
            self.changed()
            self.redraw()

    def presentation_changed(self, *args):
        if not self.loading:
            self.changed()
            self.redraw()

    def cursor_motion(self, event):
        if (self.cursor_enabled.isChecked() and event.inaxes in [a for pair in self.panel_axes for a in pair]
                and event.xdata is not None and event.ydata is not None):
            for line in getattr(self, 'shared_cursor_lines', []):
                line.set_xdata([event.xdata, event.xdata])
                line.set_visible(True)
            self.canvas.draw_idle()
            label = "Residual" if event.inaxes is self.resax else "Y"
            self.coordinates.setText(f"X: {event.xdata:.7g}   {label}: {event.ydata:.7g}")
        else:
            self.coordinates.clear()
            for line in getattr(self, 'shared_cursor_lines', []):
                line.set_visible(False)
            self.canvas.draw_idle()

    def limits_changed(self, axis, axes):
        if self.drawing:
            return
        limits = list(axes.get_xlim() if axis == 'x' else axes.get_ylim())
        panel_index = next((i for i, pair in enumerate(self.panel_axes) if axes in pair), self.active_panel)
        state = self.panels[panel_index]['view'][axis]
        if axis == 'x' and self.sync_x:
            self.drawing = True
            try:
                for panel, pair in zip(self.panels, self.panel_axes):
                    panel['view']['x'].update(auto=False, limits=limits)
                    for target in pair:
                        if target is not axes:
                            target.set_xlim(limits)
            finally:
                self.drawing = False
            self.sync_axis_controls()
            self.changed()
        if state['limits'] != limits:
            state.update(auto=False, limits=limits)
            self.sync_axis_controls()
            self.changed()

    def update_table_visibility(self, *args):
        self.table.setVisible(self.plot_tabs.currentIndex() == 0 or self.image_viewer.show_table.isChecked())

    def plot_tab_changed(self, index):
        self.update_table_visibility()
        self.analysis_panel.setVisible(index == 0)
        self.image_viewer.set_context(self.datasets, self.current())

    def redraw(self):
        self.image_viewer.set_context(self.datasets, self.current())
        self.drawing = True
        try:
            self.draw_plot()
        finally:
            self.drawing = False

    def draw_plot(self):
        for axes, callback in self.limit_callbacks:
            axes.callbacks.disconnect(callback)
        self.limit_callbacks.clear()
        if hasattr(self, 'span'):
            self.span.disconnect_events()
        if hasattr(self, 'stats_selector'):
            self.stats_selector.disconnect_events()
        for cursor in getattr(self, 'cursors', []):
            cursor.disconnect_events()
        self.cursors = []
        if len(self.panel_axes) != len(self.panels):
            self.figure.clear()
            self.panel_grid = self.figure.add_gridspec(len(self.panels), 1)
            self.panel_axes = []
            self.panel_fit_specs = []
            for i in range(len(self.panels)):
                sub = self.panel_grid[i].subgridspec(2, 1, height_ratios=[3, 1])
                ax = self.figure.add_subplot(sub[0])
                resax = self.figure.add_subplot(sub[1], sharex=ax)
                self.panel_axes.append((ax, resax))
                self.panel_fit_specs.append(sub[0])
            self.navigation.update()
        self.panel_log_notices = []
        active_view = self.panels[self.active_panel]['view']
        if self.sync_x:
            for panel in self.panels:
                panel['view']['x'] = deepcopy(active_view['x'])
        for i in [j for j in range(len(self.panels)) if j != self.active_panel] + [self.active_panel]:
            self.ax, self.resax = self.panel_axes[i]
            self.view = self.panels[i]['view']
            self.fit_plot_spec = self.panel_fit_specs[i]
            self.full_plot_spec = self.panel_grid[i]
            self.draw_panel(i)
        if self.sync_x:
            limits = self.ax.get_xlim()
            for panel, pair in zip(self.panels, self.panel_axes):
                panel['view']['x']['limits'] = list(limits)
                pair[0].set_xlim(limits)
        self.log_notice.setText(("Log axes require positive values. Not drawn: "
                                 + "; ".join(self.panel_log_notices)
                                 + ". Stored data and fits are unchanged.") if self.panel_log_notices else "")
        self.log_notice.setVisible(bool(self.panel_log_notices))
        self.shared_cursor_lines = [ax.axvline(0, visible=False, color='gray', linewidth=.7)
                                    for pair in self.panel_axes for ax in pair if ax.get_visible()]
        self.sync_axis_controls()
        self.canvas.draw_idle()

    def draw_panel(self, panel_index):
        active = panel_index == self.active_panel
        plotted_datasets = self.panel_datasets(self.panels[panel_index])
        self.coordinates.clear()
        self.ax.clear()
        self.resax.clear()
        # Empty axes otherwise retain limits contributed by old cursor artists.
        self.ax.dataLim = Bbox.null()
        self.resax.dataLim = Bbox.null()
        fitting = self.show_fitting.isChecked() and active
        self.resax.set_visible(fitting)
        self.ax.set_subplotspec(self.fit_plot_spec if fitting else self.full_plot_spec)
        self.ax.tick_params(labelbottom=not fitting)
        notices = []
        palette = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd',
                   '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf']
        color_indices = {d.id: i for i, d in enumerate(self.datasets)}
        for d in plotted_datasets:
            if not d.visible:
                continue
            color = d.color or palette[color_indices[d.id] % len(palette)]
            x, y, excluded = display_values(d.values[:, d.xcol], d.values[:, d.ycol],
                                            self.view['x']['scale'], self.view['y']['scale'])
            if excluded:
                notices.append(f"{d.name}: {excluded} data row(s)")
            if d.style == 'Scatter':
                self.ax.scatter(x, y, s=14, label=d.name, color=color, marker=d.marker or 'o')
            else:
                self.ax.plot(x, y, label=d.name, color=color, marker=d.marker or 'None')
            if (d.analysis and d.analysis.get('version') == 2 and d.analysis.get('operation') == 'mean'
                    and (d.xcol, d.ycol) == (0, 1)):
                sd = d.values[:, 2]
                lower, upper = y - sd, y + sd
                if self.view['y']['scale'] == 'log':
                    lower = np.where(lower > 0, lower, np.nan)
                    upper = np.where(upper > 0, upper, np.nan)
                self.ax.fill_between(x, lower, upper, color=color, alpha=.2, label=d.name + ' ±1 sample SD (not SEM)')
            if fitting and d.fit and (d.fit['xcol'], d.fit['ycol']) == (d.xcol, d.ycol):
                fit = d.fit
                order = np.argsort(fit['x'])
                fx, fy, count = display_values(np.array(fit['x'])[order], np.array(fit['predicted'])[order],
                                               self.view['x']['scale'], self.view['y']['scale'])
                if count:
                    notices.append(f"{d.name}: {count} fit point(s)")
                self.ax.plot(fx, fy, '--', label=d.name + ' fit', color=color)
                rx, ry, _ = display_values(fit['x'], fit['residuals'], self.view['x']['scale'], 'linear')
                self.resax.scatter(rx, ry, s=10, label=d.name, color=color)
        self.panel_log_notices.extend(
            (f'Panel {panel_index + 1}: ' if len(self.panels) > 1 else '') + notice
            for notice in notices)
        panel_title = self.title.text()
        if len(self.panels) > 1:
            panel_title = f"Panel {panel_index + 1}" + (' (active)' if active else '') + (f' — {panel_title}' if panel_title else '')
        self.ax.set_title(panel_title)
        visible = [d for d in plotted_datasets if d.visible]
        x_label = ', '.join(dict.fromkeys(d.columns[d.xcol] for d in visible)) or 'X'
        y_label = ', '.join(dict.fromkeys(d.columns[d.ycol] for d in visible)) or 'Y'
        self.xlabel.setPlaceholderText(x_label)
        self.ylabel.setPlaceholderText(y_label)
        self.ax.set_ylabel(self.panels[panel_index].get('ylabel', self.ylabel.text() if len(self.panels) == 1 else '') or y_label)
        self.resax.set_xlabel(self.xlabel.text() or x_label)
        self.ax.set_xlabel("" if fitting else self.resax.get_xlabel())
        self.resax.set_ylabel("Residual")
        self.resax.axhline(0, color='gray', linewidth=0.8)
        # No positive data has a deterministic log view, without clipping values.
        for axis in ('x', 'y'):
            state = self.view[axis]
            if state['scale'] == 'log':
                interval = self.ax.dataLim.intervalx if axis == 'x' else self.ax.dataLim.intervaly
                if not np.isfinite(interval).all() or max(interval) <= 0:
                    getattr(self.ax, 'set_' + axis + 'lim')(1, 10)
            getattr(self.ax, 'set_' + axis + 'scale')(state['scale'], **({'nonpositive': 'mask'} if state['scale'] == 'log' else {}))
        for axis, axes in (('x', self.ax), ('y', self.ax), ('resy', self.resax)):
            state = self.view[axis]
            coordinate = 'x' if axis == 'x' else 'y'
            if state['auto']:
                interval = axes.dataLim.intervalx if coordinate == 'x' else axes.dataLim.intervaly
                empty_log = state['scale'] == 'log' and (not np.isfinite(interval).all() or max(interval) <= 0)
                if empty_log:
                    getattr(axes, 'set_' + coordinate + 'lim')(1, 10)
                else:
                    getattr(axes, 'set_autoscale' + coordinate + '_on')(True)
                    axes.autoscale_view(scalex=coordinate == 'x', scaley=coordinate == 'y')
            elif state['limits'] is not None:
                getattr(axes, 'set_' + coordinate + 'lim')(state['limits'])
            state['limits'] = list(getattr(axes, 'get_' + coordinate + 'lim')())
        for axes in (self.ax, self.resax):
            axes.grid(True, alpha=0.2)
            if axes.get_legend_handles_labels()[0] and self.legend_position.currentText() != 'hidden':
                axes.legend(fontsize=8, loc=self.legend_position.currentText())
        # Interactive artists must not participate in automatic data limits.
        # Automatic ranges are recomputed explicitly on the next redraw.
        for axes in (self.ax, self.resax):
            axes.set_autoscalex_on(False)
            axes.set_autoscaley_on(False)
        if active:
            self.refresh_statistics()
            self.span = SpanSelector(self.ax, self.range_selected, 'horizontal', useblit=True,
                                     interactive=True, props=dict(alpha=0.2, facecolor='tab:blue'))
            self.span.set_active(self.drag.isChecked())
            if self.stats_mode.currentIndex() == 0:
                self.stats_selector = SpanSelector(self.ax, self.statistics_selected, 'horizontal',
                                                   useblit=True, interactive=True,
                                                   props=dict(alpha=.18, facecolor='tab:green'))
            else:
                self.stats_selector = RectangleSelector(self.ax, self.statistics_rectangle_selected,
                                                        useblit=True, interactive=True,
                                                        props=dict(alpha=.18, facecolor='tab:green'))
            if self.stats_region is not None and self.show_statistics.isChecked():
                self.stats_selector.extents = (self.stats_region[:2] if self.stats_mode.currentIndex() == 0
                                               else self.stats_region)
                self.stats_selector.set_visible(True)
            self.stats_selector.set_active(self.stats_drag.isChecked() and self.show_statistics.isChecked())
        self.cursors += [Cursor(axes, useblit=False, color='gray', linewidth=.7) for axes in (self.ax, self.resax)]
        for cursor in self.cursors:
            cursor.set_active(self.cursor_enabled.isChecked())
        self.sync_axis_controls()
        for axis, axes, event in [('x', self.ax, 'xlim_changed'), ('x', self.resax, 'xlim_changed'),
                                  ('y', self.ax, 'ylim_changed'), ('resy', self.resax, 'ylim_changed')]:
            callback = axes.callbacks.connect(event, lambda ax, key=axis: self.limits_changed(key, ax))
            self.limit_callbacks.append((axes, callback))
        self.canvas.draw_idle()

    def show_result(self):
        return self.fit_panel.show_result(self.current())

    def start_fit(self):
        channels = self.panels[self.active_panel]['channels']
        if self.current() and channels is not None and self.current().id not in channels:
            raise ValueError('Assign the active dataset to this panel before fitting.')
        if not self.current():
            raise ValueError("Import or select a dataset first.")
        lower, upper = float(self.lower.text()), float(self.upper.text())
        self.worker = FitWorker(self.current(), self.model.currentText(), lower, upper, self.exclude.isChecked(), self)
        self.worker.result.connect(self.fit_ready)
        self.worker.failed.connect(self.error)
        self.worker.finished.connect(self.fit_finished)
        self.centralWidget().setEnabled(False)
        self.edit_menu.setEnabled(False)
        self.file_menu.setEnabled(False)
        for action in self.project_actions.values():
            action.setEnabled(False)
        self.copy_action.setEnabled(False)
        self.paste_action.setEnabled(False)
        self.undo_action.setEnabled(False)
        self.redo_action.setEnabled(False)
        self.findChild(W.QToolBar).setEnabled(False)
        self.statusBar().showMessage("Fitting…")
        self.worker.start()

    def fit_ready(self, dataset, fit):
        dataset.fit = fit
        self.changed()
        self.show_result()
        self.redraw()

    def fit_finished(self):
        self.centralWidget().setEnabled(True)
        self.edit_menu.setEnabled(True)
        self.file_menu.setEnabled(True)
        for action in self.project_actions.values():
            action.setEnabled(True)
        self.update_clipboard_actions()
        self.undo_action.setEnabled(self.history.canUndo())
        self.redo_action.setEnabled(self.history.canRedo())
        self.findChild(W.QToolBar).setEnabled(True)
        self.statusBar().showMessage("Fit operation finished", 4000)

    def refresh_saved_views_menu(self):
        return project_commands.refresh_saved_views_menu(self)

    def prompt_save_view(self):
        return project_commands.prompt_save_view(self)

    def prompt_rename_view(self, name):
        return project_commands.prompt_rename_view(self, name)

    def view_name(self, name, previous=None):
        return project_commands.view_name(self, name, previous)

    def create_view(self, name):
        return project_commands.create_view(self, name)

    def rename_view(self, name, new_name):
        return project_commands.rename_view(self, name, new_name)

    def delete_view(self, name):
        return project_commands.delete_view(self, name)

    def restore_view(self, name):
        return project_commands.restore_view(self, name)

    def settings(self):
        return project_commands.settings(self)

    def recent_projects(self):
        return project_commands.recent_projects(self)

    def refresh_recent_projects(self):
        return project_commands.refresh_recent_projects(self)

    def remember_project(self, path):
        return project_commands.remember_project(self, path)

    def suggest_recent_project(self):
        return project_commands.suggest_recent_project(self)

    def save(self, save_as=False):
        return project_commands.save(self, save_project, save_as)

    def confirm_discard(self):
        return project_commands.confirm_discard(self)

    def open_project(self, path=None, *, confirm=True):
        return project_commands.open_project(self, path, confirm=confirm)

    def export_data(self):
        return project_commands.export_data(self)

    def export_fit(self):
        return project_commands.export_fit(self)

    def export_plot(self):
        return project_commands.export_plot(self)

    def closeEvent(self, event):
        return project_commands.closeEvent(self, event)


def main():
    app = W.QApplication.instance() or W.QApplication(sys.argv)
    window = MainWindow()
    window.show()
    C.QTimer.singleShot(0, window.suggest_recent_project)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
