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
from .canvas import ResponsiveCanvas as FigureCanvasQTAgg
from matplotlib.widgets import SpanSelector, Cursor, RectangleSelector
from .browser_panel import BrowserPanel, BrowserState, BrowserItem, DatasetBrowser, populate_group_tree
from .plot_controls_panel import PlotControlsPanel
from .files_panel import FilesPanel
from .files import loaded_sources
from .fitting_panel import FittingPanel, FitWorker
from . import project_actions as project_commands
from .screen import fit_to_screen
from .dialogs import ImportDialog, SpmImportDialog, ImportGroupDialog, MetadataGroupingDialog, MetadataDialog
from . import dataset_actions
from .table_actions import DataTable
from . import table_actions
from . import plot_actions, plot_context
from . import plot_windows
from .operations import run_operation, set_editing_enabled, Cancelled, dialog_parent, collect_on_main_thread
from .history import ChangeCommand, CellCommand, CellsCommand
from .grouping import group_path, path_key, path_label, node_label, partitions, varying_fields, field_labels, import_destinations
from .spm import load_spm
from .scanfile import bundle_channels, consolidate_legacy
from .images import ImageViewer
from .metadata import attach_spectrum_metadata, metadata_fields, metadata_search_text, acquisition_timestamp, channel_count
from .clipboard import MIME, selection_rectangle, copy_table, parse_paste
from .plotting import MARKERS, LEGENDS, full_plot_style, validate_view, display_values
from .core import Dataset, parse_text, spectrum_table, fit_dataset, export_data, export_fit, remove_datasets
from .core import region_statistics
from .project import save_project, load_project, convert_folder


# The file window leaves room beside it for the plot window (capped to the screen);
# without the optional data table it is only as wide as the dataset list.
FILE_WINDOW_SIZE = (1150, 760)
COMPACT_FILE_WIDTH = 520
FILES_PANEL_WIDTH = 400


def project_preferences():
    return C.QSettings('Rogi', 'Rogi')


class MainWindow(W.QMainWindow):
    def __init__(self):
        super().__init__()
        self._build_state()
        self._build_menus()
        central = W.QWidget()
        central_layout = W.QVBoxLayout(central)
        central_layout.setContentsMargins(0, 0, 0, 0)
        self.setCentralWidget(central)
        central_layout.addWidget(self.project_toolbar)
        central_layout.addLayout(self._build_file_buttons())
        splitter = W.QSplitter()
        self._build_files(splitter)
        self._build_browser(splitter)
        self._build_center(splitter)
        layout = self._build_analysis_container(splitter)
        self._build_channels(layout)
        self._build_plot_controls(layout)
        self._build_statistics(layout)
        self._build_fitting(layout)
        # Never narrower than the controls' widest row, so no horizontal scrollbar.
        self.analysis_panel.setMinimumWidth(self.analysis_panel.widget().minimumSizeHint().width()
                                            + self.analysis_panel.verticalScrollBar().sizeHint().width()
                                            + 2 * self.analysis_panel.frameWidth())
        central_layout.addWidget(splitter)
        self._build_connections()
        shown = self.preferences.value('data_table_shown', False, type=bool)
        with C.QSignalBlocker(self.show_table_button):
            self.show_table_button.setChecked(shown)
        self.set_table_shown(shown, remember=False)
        files_shown = self.preferences.value('files_panel_shown', True, type=bool)
        with C.QSignalBlocker(self.show_files_button):
            self.show_files_button.setChecked(files_shown)
        self.set_files_shown(files_shown, remember=False)
        project_commands.restore_files_folder(self)
        self.setAcceptDrops(True)

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
        self.plot_style = full_plot_style()
        self.legend_labels = {}
        self.legend_order = []  # dataset ids, first in the legend first
        self.legend_hidden = []
        self.legend_entries = {}
        self.legend_ids = {}
        self.curve_artists = {}
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
        self.plot_stale = False
        self.last_import_group = None
        self.setWindowTitle("Rogi — Scientific Analysis")
        fit_to_screen(self, COMPACT_FILE_WIDTH, FILE_WINDOW_SIZE[1])
        self.history = G.QUndoStack(self)

    def _build_menus(self):
        return project_commands._build_menus(self)

    def _build_files(self, splitter):
        self.files_panel = FilesPanel()
        self.files_panel.load_requested.connect(self.load_from_panel)
        self.files_panel.open_project_requested.connect(lambda path: self.guard(lambda: self.open_project(path)))
        self.files_panel.convert_requested.connect(lambda folder: self.guard(lambda: self.convert_folder(folder)))
        self.files_panel.folder_changed.connect(lambda folder: project_commands.remember_files_folder(self, folder))
        self.files_panel.loaded_sources = lambda: loaded_sources(self.datasets)
        splitter.addWidget(self.files_panel)

    def _build_browser(self, splitter):
        self.browser_panel = BrowserPanel(self.browser_state)
        self.browser_panel.selection_requested.connect(self.select)
        self.browser_panel.selection_requested.connect(self.update_analysis_actions)
        self.history.indexChanged.connect(self.update_analysis_actions)
        self.browser_panel.action_requested.connect(
            lambda name, args: self.guard(lambda: getattr(self, name)(*args)))
        self.browser_panel.attributes_requested.connect(self.change_attributes)
        self.browser = self.browser_panel.browser
        self.group_filter = self.browser_panel.group_filter
        self.kind_filter = self.browser_panel.kind_filter
        self.organization_actions = self.browser_panel.organization_actions
        self.search = self.browser_panel.search
        self.selection_info = self.browser_panel.selection_info
        self.tag_button = self.browser_panel.tag_button
        tree_toggle = self.browser_panel.tree_toggle
        tree_toggle.setChecked(self.preferences.value('browser_tree', True, type=bool))
        tree_toggle.toggled.connect(lambda shown: self.preferences.setValue('browser_tree', shown))
        splitter.addWidget(self.browser_panel)

    def _build_center(self, splitter):
        # The plot window holds the line plot (with its controls) and the 2D map; the
        # file window keeps the browser and the data table (see plot_windows).
        self.plot_window = plot_windows.PlotWindow(self)
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
        # Plot hints and cursor coordinates appear in the plot window, next to the plot.
        self.plot_status = self.plot_window.statusBar()
        self.image_viewer = ImageViewer(self)
        self.image_viewer.profile_created.connect(self.add_dataset)
        self.image_viewer.preview_requested.connect(lambda name: self.guard(lambda: self.preview_image_preset(name)))
        # Plot controls sit beside the line plot (see _build_analysis_container).
        self.line_view = W.QSplitter()
        self.line_view.addWidget(plot_widget)
        self.plot_tabs = W.QTabWidget()
        self.plot_tabs.addTab(self.line_view, 'Line plot')
        self.plot_tabs.addTab(self.image_viewer, '2D Map')
        self.plot_tabs.currentChanged.connect(self.plot_tab_changed)
        self.plot_window.setCentralWidget(self.plot_tabs)
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
        splitter.addWidget(self.table)

    def _build_file_buttons(self):
        row = W.QHBoxLayout()
        row.setContentsMargins(8, 6, 8, 0)
        self.show_files_button = W.QPushButton("Show files")
        self.show_files_button.setCheckable(True)
        self.show_files_button.setToolTip("List a data folder to browse, preview and load its files")
        self.show_files_button.toggled.connect(self.set_files_shown)
        row.addWidget(self.show_files_button)
        self.open_plot_button = plot_windows.open_button()
        row.addWidget(self.open_plot_button)
        self.show_table_button = W.QPushButton("Show data table")
        self.show_table_button.setCheckable(True)
        self.show_table_button.setToolTip("Show the selected dataset's values beside the dataset list")
        self.show_table_button.toggled.connect(self.set_table_shown)
        row.addWidget(self.show_table_button)
        row.addStretch()
        return row

    def _build_analysis_container(self, splitter):
        panel = W.QWidget()
        layout = W.QVBoxLayout(panel)
        panel_scroll = W.QScrollArea()
        self.analysis_panel = panel_scroll
        panel_scroll.setWidgetResizable(True)
        panel_scroll.setWidget(panel)
        panel_scroll.setMinimumWidth(300)
        panel_scroll.setMaximumWidth(400)
        self.line_view.addWidget(panel_scroll)
        self.line_view.setCollapsible(0, False)
        self.line_view.setSizes([680, 380])
        plot_windows.build(self, self.show_fitting.parent(), self.project_toolbar)
        splitter.setSizes([FILES_PANEL_WIDTH, 420, 730])
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
        self.plot_controls.legend_changed_requested.connect(lambda: plot_context.legend_position_changed(self))
        self.plot_controls.add_curve_requested.connect(lambda dataset_id: self.guard(lambda: self.add_curve(dataset_id)))
        self.plot_controls.remove_curve_requested.connect(lambda dataset_id: self.guard(lambda: self.remove_curve(dataset_id)))
        self.plot_controls.curve_filter_changed_requested.connect(self.refresh_curves)
        self.browser_panel.filter_changed.connect(self.refresh_curves)

    def _build_plot_controls(self, layout):
        self.show_plot_controls.toggled.connect(self.plot_panel.setVisible)
        self.show_plot_controls.toggled.connect(lambda on: on and plot_windows.ensure_plot(self, plot_windows.LINE))
        self.plot_status.addPermanentWidget(self.coordinates)
        self.canvas.mpl_connect('motion_notify_event', self.cursor_motion)
        self.canvas.mpl_connect('button_press_event', lambda event: plot_context.canvas_pressed(self, event))
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

    def run_operation(self, label, function, **options):
        return run_operation(self, label, function, **options)

    def guard(self, function):
        try:
            return function()
        except Cancelled:
            return False
        except Exception as error:
            self.error(str(error))
            return False

    def error(self, text):
        W.QMessageBox.warning(dialog_parent(self), "Rogi", text)

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

    def filter_browser(self, *args):
        return self.browser_panel.filter_browser(*args)

    def update_browser_item(self, item, dataset):
        return self.browser_panel.update_browser_item(item, dataset)

    def display_group_path(self, path):
        return self.browser_panel.display_group_path(path)

    def annotate_selected(self, attribute, value):
        return dataset_actions.annotate_selected(self, attribute, value)

    def edit_tags(self):
        return dataset_actions.edit_tags(self)

    def edit_comments(self):
        return dataset_actions.edit_comments(self)

    def rename_dataset(self):
        return dataset_actions.rename_dataset(self)

    def edit_units(self):
        return dataset_actions.edit_units(self)

    def assign_group(self):
        return dataset_actions.assign_group(self)

    def group_by_metadata(self):
        return dataset_actions.group_by_metadata(self)

    def group_by_levels(self, datasets, levels, append=False):
        return dataset_actions.group_by_levels(self, datasets, levels, append)

    def group_selected_by_metadata(self, key, descending=False, datasets=None):
        return dataset_actions.group_selected_by_metadata(self, key, descending, datasets)

    def view_metadata(self):
        return dataset_actions.view_metadata(self)

    def set_selected_group(self, group):
        return dataset_actions.set_selected_group(self, group)

    def change_attributes(self, datasets, attribute, value, label):
        return dataset_actions.change_attributes(self, datasets, attribute, value, label)

    def set_selected_visibility(self, visible):
        return dataset_actions.set_selected_visibility(self, visible)

    def remove_selected(self):
        return dataset_actions.remove_selected(self)

    def set_table_shown(self, shown, remember=True):
        return table_actions.set_table_shown(self, shown, remember)

    def set_files_shown(self, shown, remember=True):
        """The Files panel sits left of the dataset list; hidden, the window narrows again."""
        if remember:
            self.preferences.setValue('files_panel_shown', shown)
        self.files_panel.setVisible(shown)
        self.show_files_button.setText("Hide files" if shown else "Show files")
        # Recompute the window's minimum width now, or it still includes the hidden panel.
        self.layout().activate()
        self.fit_file_window()

    def fit_file_window(self):
        """Size for the dataset list, plus the files panel and data table when shown; height is kept once on screen."""
        width = FILE_WINDOW_SIZE[0] if self.table.isVisibleTo(self) else COMPACT_FILE_WIDTH
        if hasattr(self, 'files_panel') and self.files_panel.isVisibleTo(self):
            width += FILES_PANEL_WIDTH
        fit_to_screen(self, width, self.height() if self.isVisible() else FILE_WINDOW_SIZE[1])

    def update_dirty(self, *args):
        return project_commands.update_dirty(self, *args)

    def update_analysis_actions(self, *args):
        return project_commands.update_analysis_actions(self, *args)

    def changed(self):
        return project_commands.changed(self)

    def refresh_history_view(self):
        return table_actions.refresh_history_view(self)

    def update_clipboard_actions(self, *args):
        return table_actions.update_clipboard_actions(self, *args)

    def copy_selection(self):
        return table_actions.copy_selection(self)

    def select_table_block(self, top, left, height, width):
        return table_actions.select_table_block(self, top, left, height, width)

    def paste_selection(self):
        return table_actions.paste_selection(self)

    def edit_cell(self, dataset, row, column, text):
        return table_actions.edit_cell(self, dataset, row, column, text)

    def add_dataset(self, dataset):
        return dataset_actions.add_dataset(self, dataset)

    def add_datasets(self, datasets):
        return dataset_actions.add_datasets(self, datasets)

    def open_files(self, paths=None):
        return project_commands.open_files(self, paths)

    def import_paths(self, paths, **options):
        return project_commands.import_paths(self, paths, **options)

    def load_from_panel(self, paths, options):
        if options.get('grouping') == 'last':
            return project_commands.auto_load(self, paths, options)
        self.guard(lambda: self.import_paths(paths, **options))

    def convert_folder(self, folder=None):
        return project_commands.convert_folder(self, folder)

    def dragEnterEvent(self, event):
        return project_commands.drag_enter(self, event)

    def dropEvent(self, event):
        return project_commands.drop(self, event)

    def select(self, row):
        return table_actions.select(self, row)

    def edited(self):
        return table_actions.edited(self)

    def spectrum_map(self, recipe=None):
        return dataset_actions.spectrum_map(self, recipe)

    def analysis_pipeline(self):
        return dataset_actions.analysis_pipeline(self)

    def add_analysis_batch(self, results):
        return dataset_actions.add_analysis_batch(self, results)

    def pipeline_presets_changed(self):
        return dataset_actions.pipeline_presets_changed(self)

    def preview_image_preset(self, name):
        return dataset_actions.preview_image_preset(self, name)

    def apply_pipeline_preset(self):
        return dataset_actions.apply_pipeline_preset(self)

    def reopen_analysis_recipe(self):
        return dataset_actions.reopen_analysis_recipe(self)

    def make_copy(self):
        return dataset_actions.make_copy(self)

    def activate_dataset(self, dataset_id):
        return self.browser_panel.activate_dataset(dataset_id)

    def visibility(self, item):
        return self.browser_panel.visibility(item)

    def panel_datasets(self, panel):
        return plot_actions.panel_datasets(self, panel)

    def freeze_default_panel(self):
        return plot_actions.freeze_default_panel(self)

    def refresh_panels(self):
        return plot_actions.refresh_panels(self)

    def add_panel(self):
        return plot_actions.add_panel(self)

    def assign_panel_channel(self):
        return plot_actions.assign_panel_channel(self)

    def unassign_panel_channel(self):
        return plot_actions.unassign_panel_channel(self)

    def remove_panel(self):
        return plot_actions.remove_panel(self)

    def activate_panel(self, index):
        return plot_actions.activate_panel(self, index)

    def add_curve(self, dataset_id):
        return plot_actions.add_curve(self, dataset_id)

    def remove_curve(self, dataset_id):
        return plot_actions.remove_curve(self, dataset_id)

    def refresh_curves(self):
        return plot_actions.refresh_curves(self)

    def set_sync_x(self, enabled):
        return plot_actions.set_sync_x(self, enabled)

    def restore_panels(self, settings):
        return plot_actions.restore_panels(self, settings)

    def plot_options(self):
        return plot_actions.plot_options(self)

    def reset_fit_range(self, dataset, restore_fit=False):
        return self.fit_panel.reset_fit_range(dataset, restore_fit)

    def labels_changed(self):
        return plot_actions.labels_changed(self)

    def toggle_fitting(self, visible):
        return plot_actions.toggle_fitting(self, visible)

    def toggle_span(self, active):
        return plot_actions.toggle_span(self, active)

    def range_selected(self, lower, upper):
        return self.fit_panel.range_selected(lower, upper)

    def disable_navigation(self):
        return plot_actions.disable_navigation(self)

    def toggle_statistics(self, visible):
        return plot_actions.toggle_statistics(self, visible)

    def statistics_mode_changed(self, *args):
        return plot_actions.statistics_mode_changed(self, *args)

    def toggle_statistics_drag(self, active):
        return plot_actions.toggle_statistics_drag(self, active)

    def statistics_selected(self, lower, upper, ylower=None, yupper=None):
        return plot_actions.statistics_selected(self, lower, upper, ylower, yupper)

    def statistics_rectangle_selected(self, press, release):
        return plot_actions.statistics_rectangle_selected(self, press, release)

    def calculate_statistics(self):
        return plot_actions.calculate_statistics(self)

    def refresh_statistics(self, *args):
        return plot_actions.refresh_statistics(self, *args)

    def sync_axis_controls(self):
        self.plot_controls.sync_axis_controls(self.view)

    def apply_axes(self):
        return plot_actions.apply_axes(self)


    def choose_color(self):
        return plot_actions.choose_color(self)

    def set_color(self, color):
        return plot_actions.set_color(self, color)

    def appearance_changed(self):
        return plot_actions.appearance_changed(self)

    def presentation_changed(self, *args):
        return plot_actions.presentation_changed(self, *args)

    def cursor_motion(self, event):
        return plot_actions.cursor_motion(self, event)

    def limits_changed(self, axis, axes):
        return plot_actions.limits_changed(self, axis, axes)

    def plot_tab_changed(self, index):
        return plot_actions.plot_tab_changed(self, index)

    def open_plot(self, tab=None):
        return plot_windows.open_plot(self, tab)

    def save_plot_window(self):
        return plot_windows.save_state(self)

    def restore_plot_window(self):
        return plot_windows.restore_state(self)

    def redraw(self):
        return plot_actions.redraw(self)

    def draw_plot(self):
        return plot_actions.draw_plot(self)

    def draw_panel(self, panel_index):
        return plot_actions.draw_panel(self, panel_index)

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
        set_editing_enabled(self, False)
        self.statusBar().showMessage("Fitting…")
        self.worker.start()

    def fit_ready(self, dataset, fit):
        dataset.fit = fit
        self.changed()
        self.show_result()
        self.redraw()

    def fit_finished(self):
        set_editing_enabled(self, True)
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
    collect_on_main_thread(app)
    window = MainWindow()
    window.show()
    window.fit_file_window()  # actual frame margins are known once shown
    window.restore_plot_window()
    C.QTimer.singleShot(0, window.suggest_recent_project)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
