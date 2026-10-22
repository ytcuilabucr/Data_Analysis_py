"""The plot window: line plot with its controls, and the 2D map, apart from the file window.

The file window (MainWindow) owns datasets, menus, history and the editing lock.
The plot window is its child top-level window: built at startup with the rest of
the interface, shown only when asked for. Functions receive the MainWindow
explicitly, like plot_actions.
"""
from PySide6 import QtCore as C, QtWidgets as W, QtGui as G
from .screen import fit_to_screen
from .browser_panel import is_group

LINE, MAP = 0, 1
OPEN_TEXT, FRONT_TEXT = 'Open plot window', 'Bring plot window to front'
# Fixed colors read the same in light and dark appearance; disabled while locked.
OPEN_BUTTON_STYLE = """
QPushButton#open_plot_button { background-color: #1f6feb; color: white; font-size: 13px; font-weight: 600;
                               padding: 5px 14px; border: none; border-radius: 6px; }
QPushButton#open_plot_button:hover { background-color: #3b82f6; }
QPushButton#open_plot_button:pressed { background-color: #1858c4; }
QPushButton#open_plot_button:disabled { background-color: #9aa4b2; }
"""


class PlotWindow(W.QMainWindow):
    """Closing only hides it; the file window decides when the application ends."""
    shown_changed = C.Signal(bool)

    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowFlag(C.Qt.WindowType.Window)
        self.setObjectName('plot_window')
        self.setWindowTitle('Rogi — Plot')

    def showEvent(self, event):
        super().showEvent(event)
        if not event.spontaneous():  # not on restore from minimized
            self.shown_changed.emit(True)

    def hideEvent(self, event):
        super().hideEvent(event)
        if not event.spontaneous():  # not on minimize
            self.shown_changed.emit(False)


def open_button():
    """The file window's prominent way into the plot window."""
    button = W.QPushButton(OPEN_TEXT)
    button.setObjectName('open_plot_button')
    button.setStyleSheet(OPEN_BUTTON_STYLE)
    button.setCursor(C.Qt.CursorShape.PointingHandCursor)
    button.setToolTip('Line plot and 2D map open in their own window (Ctrl+Shift+P, ⌘⇧P on macOS)')
    return button


def build(self, view_menu, toolbar):
    fit_to_screen(self.plot_window, 1100, 800)
    self.plot_action = G.QAction("Plot window", self)
    self.plot_action.setCheckable(True)
    self.plot_action.setShortcut(G.QKeySequence("Ctrl+Shift+P"))
    self.plot_action.setShortcutContext(C.Qt.ShortcutContext.ApplicationShortcut)
    self.plot_action.setToolTip("Open or close the plot window (line plot and 2D map)")
    self.plot_action.triggered.connect(lambda checked: open_plot(self) if checked else self.plot_window.close())
    view_menu.insertAction(view_menu.actions()[0], self.plot_action)
    toolbar.insertAction(toolbar.actions()[0], self.plot_action)
    self.plot_window.shown_changed.connect(self.plot_action.setChecked)
    self.plot_window.shown_changed.connect(lambda shown: shown and self.plot_stale and self.redraw())
    self.browser.itemDoubleClicked.connect(lambda item, *args: is_group(item) or open_plot(self))
    self.open_plot_button.clicked.connect(lambda: open_plot(self))
    self.plot_window.shown_changed.connect(
        lambda shown: self.open_plot_button.setText(FRONT_TEXT if shown else OPEN_TEXT))


def plot_hidden(self):
    """Drawing is skipped while the file window is on screen without its plot window.

    Without a visible file window (scripts, tests) plots are always drawn.
    """
    return self.isVisible() and not self.plot_window.isVisible()


def open_plot(self, tab=None):
    if tab is not None:
        self.plot_tabs.setCurrentIndex(tab)
    self.plot_window.show()
    self.plot_window.raise_()
    self.plot_window.activateWindow()


def ensure_plot(self, tab=None):
    """Commands that act on the plot open it, unless a project is being restored."""
    if self.isVisible() and not self.loading:
        open_plot(self, tab)
    elif tab is not None:
        self.plot_tabs.setCurrentIndex(tab)


def save_state(self):
    """Open state and geometry are per machine (monitors differ), so they live in QSettings."""
    self.preferences.setValue('plot_window_open', self.plot_window.isVisible())
    self.preferences.setValue('plot_window_geometry', self.plot_window.saveGeometry())


def restore_state(self):
    """On first start the plot window stays closed; afterwards it reopens as it was left."""
    geometry = self.preferences.value('plot_window_geometry')
    if geometry is not None:
        # restoreGeometry moves a window saved on a disconnected monitor onto a present one.
        self.plot_window.restoreGeometry(geometry)
    if self.preferences.value('plot_window_open', False, type=bool):
        open_plot(self)


def update_titles(self):
    """The plot window says what it shows, e.g. on another monitor or in Mission Control."""
    d = self.current()
    view = 'Line plot' if self.plot_tabs.currentIndex() == LINE else '2D map'
    detail = d.name if d else ''
    if d and self.plot_tabs.currentIndex() == LINE and len(self.panels) > 1:
        detail += f' (Panel {self.active_panel + 1})'
    self.plot_window.setWindowTitle(f'Rogi — {view}' + (f' — {detail}' if detail else ''))
