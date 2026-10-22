"""Plot views float as their own windows yet stay under the main window's lock, shortcuts and layout."""
import time

import pytest
from PySide6 import QtCore as C, QtGui as G, QtWidgets as W, QtTest
from rogi.core import parse_text
from rogi.operations import coordinator, dialog_parent
from rogi.plot_windows import LINE, MAP, LAYOUT_VERSION
from rogi.ui import MainWindow


@pytest.fixture
def window(app):
    window = MainWindow()
    window.show()
    app.processEvents()
    yield window
    window.dirty = False
    window.close()
    window.deleteLater()
    app.sendPostedEvents(None, C.QEvent.Type.DeferredDelete)
    app.processEvents()


def float_dock(window, app, index):
    dock = window.plot_docks[index]
    window.float_actions[dock.objectName()].setChecked(True)
    app.processEvents()
    assert dock.isFloating() and dock.widget().window() is dock
    return dock


def test_floating_docks_are_locked_and_defer_draws(window, app):
    float_dock(window, app, MAP)
    float_dock(window, app, LINE)
    assert coordinator(window.canvas) is window
    observed = []
    def inspect():
        observed.append([dock.widget().isEnabled() for dock in window.docks])
        window.canvas.draw()
        observed.append(window.canvas in window._pending_canvases)
    C.QTimer.singleShot(20, inspect)
    window.run_operation('Test lock', lambda: time.sleep(.08))
    assert observed == [[False, False], True]
    assert all(dock.widget().isEnabled() for dock in window.docks)


def test_main_shortcuts_reach_floating_map(window, app):
    dock = float_dock(window, app, MAP)
    window.history.push(G.QUndoCommand('probe'))
    fired = []
    window.undo_action.triggered.connect(lambda: fired.append(True))
    dock.activateWindow()
    window.image_viewer.setFocus()
    QtTest.QTest.keySequence(window.image_viewer, G.QKeySequence(G.QKeySequence.StandardKey.Undo))
    assert fired


def test_line_plot_and_map_float_separately(window, app):
    window.plot_tabs.setCurrentIndex(MAP)
    window.image_viewer.show_table.setChecked(False)
    app.processEvents()
    # The docked map alone takes the table's room.
    assert not window.table.isVisible()
    float_dock(window, app, MAP)
    assert window.plot_docks[LINE].isVisible() and window.plot_docks[MAP].isVisible()
    assert window.table.isVisible()
    window.plot_docks[MAP].setFloating(False)
    app.processEvents()
    assert not window.float_actions['map_dock'].isChecked()


def test_current_view_follows_focus_and_shortcut_floats_it(window, app):
    window.plot_tabs.setCurrentIndex(MAP)
    window.float_current.trigger()
    app.processEvents()
    assert window.plot_docks[MAP].isFloating() and not window.plot_docks[LINE].isFloating()
    window.activateWindow()
    window.canvas.setFocus()
    app.processEvents()
    assert window.plot_tabs.currentIndex() == LINE


def test_reset_layout_docks_everything_and_forgets_it(window, app):
    float_dock(window, app, LINE)
    float_dock(window, app, MAP)
    window.save_plot_layout()
    window.reset_layout.trigger()
    app.processEvents()
    assert not any(dock.isFloating() for dock in window.docks)
    assert window.preferences.value('plot_layout') is None
    assert window.plot_tabs.currentIndex() == LINE


def test_layout_persists_in_preferences_not_project(window, app):
    float_dock(window, app, MAP)
    window.close()
    assert window.preferences.value('plot_layout') is not None
    assert 'plot_layout' not in window.settings()
    reopened = MainWindow()
    try:
        assert reopened.plot_docks[MAP].isFloating() and reopened.float_actions['map_dock'].isChecked()
    finally:
        reopened.close()


def test_layout_from_another_version_is_ignored(window, app):
    float_dock(window, app, LINE)
    window.preferences.setValue('plot_layout', window.plot_host.saveState(LAYOUT_VERSION - 1))
    reopened = MainWindow()
    try:
        assert not reopened.plot_docks[LINE].isFloating()
    finally:
        reopened.close()


def test_floating_window_from_missing_screen_reopens_on_screen(window, app):
    dock = float_dock(window, app, LINE)
    dock.move(-100000, -100000)
    app.processEvents()
    window.close()
    reopened = MainWindow()
    try:
        dock = reopened.plot_docks[LINE]
        assert dock.isFloating()
        assert any(screen.availableGeometry().intersects(dock.frameGeometry())
                   for screen in G.QGuiApplication.screens())
    finally:
        reopened.close()


def test_floating_titles_name_dataset_and_panel(window, app):
    window.add_dataset(parse_text('x,y\n1,2\n2,4', name='trace'))
    assert window.plot_docks[LINE].windowTitle() == 'Line plot'
    dock = float_dock(window, app, LINE)
    assert dock.windowTitle() == 'Line plot — trace'
    window.add_panel()
    assert dock.windowTitle() == 'Line plot — trace (Panel 2)'
    dock.setFloating(False)
    app.processEvents()
    assert dock.windowTitle() == 'Line plot'


def test_hints_and_coordinates_stay_with_the_plot(window, app):
    assert window.coordinates.parentWidget() is window.plot_status
    dock = float_dock(window, app, LINE)
    assert window.plot_status.window() is dock


def test_dialogs_open_over_the_active_floating_window(window, app, monkeypatch):
    dock = float_dock(window, app, LINE)
    monkeypatch.setattr(W.QApplication, 'activeWindow', staticmethod(lambda: dock))
    assert dialog_parent(window) is dock
    other = W.QWidget()
    monkeypatch.setattr(W.QApplication, 'activeWindow', staticmethod(lambda: other))
    assert dialog_parent(window) is window


def test_toolbar_copy_and_export(window, app, tmp_path, monkeypatch):
    window.add_dataset(parse_text('x,y\n1,2\n2,4', name='trace'))
    W.QApplication.clipboard().clear()
    window.navigation.copy_plot()
    assert not W.QApplication.clipboard().image().isNull()
    target = tmp_path / 'map'
    monkeypatch.setattr(W.QFileDialog, 'getSaveFileName', lambda *args: (str(target), 'SVG (*.svg)'))
    window.image_viewer.navigation.export_plot()
    assert (tmp_path / 'map.svg').read_text().lstrip().startswith('<?xml')


def test_keep_windows_visible_is_remembered(window, app):
    window.keep_windows_visible.setChecked(True)
    assert all(dock.testAttribute(C.Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow) for dock in window.docks)
    reopened = MainWindow()
    try:
        assert reopened.keep_windows_visible.isChecked()
    finally:
        reopened.close()


def test_plot_controls_float_with_the_line_plot(window, app):
    assert 'controls_dock' not in window.float_actions
    assert window.plot_docks[LINE].isAncestorOf(window.analysis_panel)
    dock = float_dock(window, app, LINE)
    assert window.analysis_panel.window() is dock and window.analysis_panel.isVisible()
