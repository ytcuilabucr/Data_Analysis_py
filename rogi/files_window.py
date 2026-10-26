"""The Files window: the data folder list for bringing files in, apart from the file window.

Like the plot window it is a child top-level window of MainWindow, which owns
the datasets, the load commands and the editing lock. Closing it only hides it;
Watch keeps loading new files, and the file window's status bar says so.
"""
from pathlib import Path
from PySide6 import QtCore as C, QtWidgets as W, QtGui as G
from .screen import fit_to_screen
from .files_panel import FilesPanel
from .files import loaded_sources

OPEN_TEXT = 'Open files window'


class FilesWindow(W.QMainWindow):
    """Closing only hides it; the file window decides when the application ends."""
    shown_changed = C.Signal(bool)

    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowFlag(C.Qt.WindowType.Window)
        self.setObjectName('files_window')
        self.setWindowTitle('Rogi — Files')
        self.panel = FilesPanel()
        self.panel.layout().setContentsMargins(8, 8, 8, 8)
        self.setCentralWidget(self.panel)
        self.setAcceptDrops(True)

    def showEvent(self, event):
        super().showEvent(event)
        if not event.spontaneous():  # not on restore from minimized
            self.shown_changed.emit(True)

    def hideEvent(self, event):
        super().hideEvent(event)
        if not event.spontaneous():  # not on minimize
            self.shown_changed.emit(False)

    # Files and folders dropped here are handled as on the file window.
    def dragEnterEvent(self, event):
        self.parent().dragEnterEvent(event)

    def dropEvent(self, event):
        self.parent().dropEvent(event)


def build(self, view_menu):
    self.files_window = FilesWindow(self)
    fit_to_screen(self.files_window, 460, 720)
    self.files_panel = panel = self.files_window.panel
    panel.load_requested.connect(self.load_from_panel)
    panel.open_project_requested.connect(lambda path: self.guard(lambda: self.open_project(path)))
    panel.folder_changed.connect(lambda folder: update_title(self))
    panel.loaded_sources = lambda: loaded_sources(self.datasets)

    self.files_action = G.QAction('Files window', self)
    self.files_action.setCheckable(True)
    self.files_action.setShortcut(G.QKeySequence('Ctrl+Shift+L'))
    self.files_action.setShortcutContext(C.Qt.ShortcutContext.ApplicationShortcut)
    self.files_action.setToolTip('Open or close the Files window (browse, preview and load data files)')
    self.files_action.triggered.connect(lambda checked: open_files(self) if checked else self.files_window.close())
    view_menu.insertAction(view_menu.actions()[0], self.files_action)
    self.files_window.shown_changed.connect(self.files_action.setChecked)
    self.files_window.shown_changed.connect(lambda shown: shown and panel.update_loaded())

    # While watching, the file window shows it even with the Files window closed.
    self.watch_indicator = W.QPushButton()
    self.watch_indicator.setFlat(True)
    self.watch_indicator.setCursor(C.Qt.CursorShape.PointingHandCursor)
    self.watch_indicator.setToolTip('New files in this folder load automatically. Click to show the Files window.')
    self.watch_indicator.clicked.connect(lambda: open_files(self))
    self.statusBar().addPermanentWidget(self.watch_indicator)
    panel.watch.toggled.connect(lambda on: update_watch_indicator(self))
    panel.folder_changed.connect(lambda folder: update_watch_indicator(self))
    update_watch_indicator(self)


def open_button():
    button = W.QPushButton(OPEN_TEXT)
    button.setToolTip('Browse, preview and load data files in their own window (Ctrl+Shift+L, ⌘⇧L on macOS)')
    return button


def open_files(self, folder=None):
    if folder:
        self.files_panel.set_folder(folder)
    self.files_window.show()
    self.files_window.raise_()
    self.files_window.activateWindow()


def update_title(self):
    folder = self.files_panel.folder
    self.files_window.setWindowTitle('Rogi — Files' + (f' — {Path(folder).name or folder}' if folder else ''))


def update_watch_indicator(self):
    panel = self.files_panel
    watching = panel.watch.isChecked() and bool(panel.folder)
    self.watch_indicator.setVisible(watching)
    if watching:
        self.watch_indicator.setText(f'● Watching {Path(panel.folder).name or panel.folder}')


def save_state(self):
    """Open state and geometry are per machine, as for the plot window."""
    self.preferences.setValue('files_window_open', self.files_window.isVisible())
    self.preferences.setValue('files_window_geometry', self.files_window.saveGeometry())


def restore_state(self):
    """On first start the Files window stays closed; afterwards it reopens as it was left."""
    geometry = self.preferences.value('files_window_geometry')
    if geometry is not None:
        self.files_window.restoreGeometry(geometry)
    # Before the Files window, the panel sat in the file window and was shown by choice.
    legacy = self.preferences.value('files_panel_shown', False, type=bool)
    if self.preferences.value('files_window_open', legacy, type=bool):
        open_files(self)
