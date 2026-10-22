"""The plot floats as its own window yet stays under the main window's lock, shortcuts and layout."""
import time

import pytest
from PySide6 import QtCore as C, QtGui as G, QtWidgets as W, QtTest
from rogi.operations import coordinator
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


def float_plot(window, app):
    window.float_plot.setChecked(True)
    app.processEvents()
    assert window.plot_dock.isFloating()
    assert window.canvas.window() is window.plot_dock


def test_floating_plot_is_locked_and_defers_draws(window, app):
    float_plot(window, app)
    assert coordinator(window.canvas) is window
    observed = []
    def inspect():
        observed.append(window.plot_tabs.isEnabled())
        window.canvas.draw()
        observed.append(window.canvas in window._pending_canvases)
    C.QTimer.singleShot(20, inspect)
    window.run_operation('Test lock', lambda: time.sleep(.08))
    assert observed == [False, True]
    assert window.plot_tabs.isEnabled()


def test_main_shortcuts_reach_floating_plot(window, app):
    float_plot(window, app)
    window.history.push(G.QUndoCommand('probe'))
    fired = []
    window.undo_action.triggered.connect(lambda: fired.append(True))
    window.plot_dock.activateWindow()
    window.plot_tabs.setFocus()
    QtTest.QTest.keySequence(window.plot_tabs, G.QKeySequence(G.QKeySequence.StandardKey.Undo))
    assert fired


def test_menu_and_table_follow_floating_state(window, app):
    window.plot_tabs.setCurrentIndex(1)
    window.image_viewer.show_table.setChecked(False)
    assert not window.table.isVisible()
    float_plot(window, app)
    assert window.table.isVisible()
    window.plot_dock.setFloating(False)
    app.processEvents()
    assert not window.float_plot.isChecked() and not window.table.isVisible()


def test_layout_persists_in_preferences_not_project(window, app):
    float_plot(window, app)
    window.close()
    assert window.preferences.value('plot_layout') is not None
    assert 'plot_layout' not in window.settings()
    reopened = MainWindow()
    try:
        assert reopened.plot_dock.isFloating() and reopened.float_plot.isChecked()
    finally:
        reopened.close()


def test_floating_plot_from_missing_screen_reopens_on_screen(window, app):
    float_plot(window, app)
    window.plot_dock.move(-100000, -100000)
    app.processEvents()
    window.close()
    reopened = MainWindow()
    try:
        assert reopened.plot_dock.isFloating()
        assert any(screen.availableGeometry().intersects(reopened.plot_dock.frameGeometry())
                   for screen in G.QGuiApplication.screens())
    finally:
        reopened.close()
