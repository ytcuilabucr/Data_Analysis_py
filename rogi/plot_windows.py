"""Plot views as docks that can float as their own windows.

They live in a nested main window (window.plot_host) beside the data table, so
docked they keep the familiar layout, and each can move to another monitor.
Functions receive the MainWindow explicitly, like plot_actions.
"""
import sys
from PySide6 import QtCore as C, QtWidgets as W, QtGui as G

# Bump when the set of docks changes; older saved layouts are then ignored.
LAYOUT_VERSION = 2
LINE, MAP = 0, 1


def make_dock(host, title, name, widget, area, areas):
    dock = W.QDockWidget(title, host)
    dock.setObjectName(name)
    dock.setFeatures(W.QDockWidget.DockWidgetFeature.DockWidgetMovable
                     | W.QDockWidget.DockWidgetFeature.DockWidgetFloatable)
    dock.setAllowedAreas(areas)
    dock.setWidget(widget)
    host.addDockWidget(area, dock)
    return dock


class PlotViews(C.QObject):
    """Tab-like access to the line plot and 2D map docks.

    The current view is the one last brought forward or focused; with the
    docks on separate monitors both can be on screen at once.
    """
    currentChanged = C.Signal(int)

    def __init__(self, host, docks, parent):
        super().__init__(parent)
        self.host, self.docks = host, docks
        self.current = LINE
        # Which docked view is in front of its tab group. Tracked here because
        # Qt reports it only through visibilityChanged, and only once shown.
        self.front = [True] + [False] * (len(docks) - 1)
        for index, dock in enumerate(docks):
            dock.visibilityChanged.connect(lambda visible, i=index: visible and self.bring_forward(i))
            dock.topLevelChanged.connect(lambda floating, i=index: floating and self.activate(i))
        W.QApplication.instance().focusChanged.connect(self.focus_changed)

    def currentIndex(self):
        return self.current

    def setCurrentIndex(self, index):
        self.docks[index].raise_()
        self.bring_forward(index)

    def docked_shown(self, index):
        """Docked and not behind another tab."""
        return not self.docks[index].isFloating() and self.front[index]

    def bring_forward(self, index):
        if not self.docks[index].isFloating():
            for other in self.host.tabifiedDockWidgets(self.docks[index]):
                if other in self.docks:
                    self.front[self.docks.index(other)] = False
            self.front[index] = True
        self.activate(index)

    def activate(self, index):
        if index != self.current:
            self.current = index
            self.currentChanged.emit(index)

    def focus_changed(self, old, new):
        for index, dock in enumerate(self.docks):
            if new is not None and dock.isAncestorOf(new):
                self.activate(index)


def build_menu(self, view_menu):
    """View → Separate windows: one toggle per dock, plus layout commands."""
    menu = view_menu.addMenu("Separate windows")
    self.float_actions = {}
    for dock in self.docks:
        action = menu.addAction(dock.windowTitle())
        action.setCheckable(True)
        action.toggled.connect(dock.setFloating)
        dock.topLevelChanged.connect(action.setChecked)
        self.float_actions[dock.objectName()] = action
    menu.addSeparator()
    self.float_current = menu.addAction("Float or dock current plot")
    self.float_current.setShortcut(G.QKeySequence("Ctrl+Shift+D"))
    self.float_current.triggered.connect(lambda: toggle_current(self))
    self.reset_layout = menu.addAction("Reset window layout")
    self.reset_layout.triggered.connect(lambda: reset_layout(self))
    self.keep_windows_visible = menu.addAction("Keep separate windows visible in other apps")
    self.keep_windows_visible.setCheckable(True)
    self.keep_windows_visible.setChecked(self.preferences.value('keep_windows_visible', False, type=bool))
    self.keep_windows_visible.toggled.connect(lambda on: set_keep_visible(self, on))
    # Only macOS hides floating tool windows when the application is inactive.
    self.keep_windows_visible.setVisible(sys.platform == 'darwin')


def toggle_current(self):
    dock = self.plot_docks[self.plot_tabs.currentIndex()]
    dock.setFloating(not dock.isFloating())


def set_keep_visible(self, on):
    self.preferences.setValue('keep_windows_visible', on)
    apply_keep_visible(self)


def apply_keep_visible(self):
    on = self.keep_windows_visible.isChecked()
    for dock in self.docks:
        dock.setAttribute(C.Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow, on)
        if dock.isFloating():
            # macOS reads the attribute only when the floating window is created.
            geometry = dock.geometry()
            dock.setFloating(False)
            dock.setFloating(True)
            dock.setGeometry(geometry)


def save_layout(self):
    """Dock arrangement is per machine (monitors differ), so it lives in QSettings, not the project."""
    self.preferences.setValue('plot_layout', self.plot_host.saveState(LAYOUT_VERSION))


def restore_layout(self):
    self.default_layout = self.plot_host.saveState(LAYOUT_VERSION)
    apply_keep_visible(self)  # before any window floats, so none needs recreating
    # restoreState moves a floating window saved on a disconnected monitor onto a present one.
    state = self.preferences.value('plot_layout')
    if state is not None:
        self.plot_host.restoreState(state, LAYOUT_VERSION)
    layout_changed(self)


def reset_layout(self):
    self.preferences.remove('plot_layout')
    for dock in self.docks:
        dock.setFloating(False)
        dock.show()
    self.plot_host.restoreState(self.default_layout, LAYOUT_VERSION)
    self.plot_tabs.setCurrentIndex(LINE)
    layout_changed(self)


def layout_changed(self, *args):
    """Show what the docked layout has room for and name the floating windows."""
    views = self.plot_tabs
    # The 2D map alone in the middle column takes the table's space unless asked otherwise.
    self.table.setVisible(self.image_viewer.show_table.isChecked() or views.docked_shown(LINE)
                          or not views.docked_shown(MAP))
    update_titles(self)


def update_titles(self):
    """Floating windows say what they show, e.g. on another monitor or in Mission Control."""
    d = self.current()
    detail = {LINE: (d.name if d else '') + (f' (Panel {self.active_panel + 1})' if len(self.panels) > 1 else ''),
              MAP: d.name if d else ''}
    for index, (dock, title) in enumerate(zip(self.plot_docks, ('Line plot', '2D map'))):
        dock.setWindowTitle(f'{title} — {detail[index]}' if dock.isFloating() and detail[index] else title)
