"""The plot opens in its own window on demand, under the file window's lock, shortcuts and close."""
import time

import pytest
from PySide6 import QtCore as C, QtGui as G, QtWidgets as W, QtTest
from rogi.core import parse_text
from rogi.operations import coordinator, dialog_parent
from rogi.plot_windows import LINE, MAP
from rogi.ui import MainWindow


@pytest.fixture
def window(app):
    window = MainWindow()
    window.show()
    window.restore_plot_window()
    app.processEvents()
    yield window
    window.dirty = False
    window.close()
    window.deleteLater()
    app.sendPostedEvents(None, C.QEvent.Type.DeferredDelete)
    app.processEvents()


def open_plot(window, app):
    window.plot_action.trigger()
    app.processEvents()
    assert window.plot_window.isVisible()
    return window.plot_window


def test_first_start_shows_only_the_file_window(window):
    assert window.isVisible() and not window.plot_window.isVisible()
    assert not window.plot_action.isChecked()
    assert window.plot_window.isWindow() and window.plot_window.parentWidget() is window
    assert window.isAncestorOf(window.browser) and window.isAncestorOf(window.table)
    assert window.plot_window.isAncestorOf(window.canvas)
    assert window.plot_window.isAncestorOf(window.image_viewer)
    assert window.plot_window.isAncestorOf(window.analysis_panel)


def test_plot_action_and_double_click_open_it(window, app):
    plot = open_plot(window, app)
    assert window.plot_action.isChecked()
    plot.close()
    app.processEvents()
    assert not plot.isVisible() and not window.plot_action.isChecked()
    window.add_dataset(parse_text('x,y\n1,2\n2,4', name='trace'))
    item = window.browser.item(0)
    window.browser.itemDoubleClicked.emit(item, 0)
    app.processEvents()
    assert plot.isVisible() and window.plot_action.isChecked()


def test_drawing_waits_for_the_plot_window(window, app):
    window.add_dataset(parse_text('x,y\n1,2\n2,4', name='trace'))
    assert window.plot_stale
    assert 'trace' not in [line.get_label() for line in window.ax.get_lines()]
    open_plot(window, app)
    assert not window.plot_stale
    assert 'trace' in [line.get_label() for line in window.ax.get_lines()]


def test_plot_window_is_locked_and_defers_draws(window, app):
    open_plot(window, app)
    assert coordinator(window.canvas) is window
    observed = []
    def inspect():
        observed.append(window.plot_window.centralWidget().isEnabled())
        window.canvas.draw()
        observed.append(window.canvas in window._pending_canvases)
    C.QTimer.singleShot(20, inspect)
    window.run_operation('Test lock', lambda: time.sleep(.08))
    assert observed == [False, True]
    assert window.plot_window.centralWidget().isEnabled()


def test_file_window_shortcuts_work_in_the_plot_window(window, app):
    plot = open_plot(window, app)
    window.history.push(G.QUndoCommand('probe'))
    fired = []
    window.undo_action.triggered.connect(lambda: fired.append(True))
    plot.activateWindow()
    window.navigation.setFocus()
    QtTest.QTest.keySequence(window.navigation, G.QKeySequence(G.QKeySequence.StandardKey.Undo))
    assert fired
    QtTest.QTest.keySequence(window.navigation, G.QKeySequence('Ctrl+Shift+P'))
    app.processEvents()
    assert not plot.isVisible()


@pytest.mark.parametrize('action', ['show_fitting', 'show_statistics', 'show_plot_controls'])
def test_plot_commands_open_the_line_plot(window, app, action):
    window.plot_tabs.setCurrentIndex(MAP)
    getattr(window, action).setChecked(True)
    app.processEvents()
    assert window.plot_window.isVisible() and window.plot_tabs.currentIndex() == LINE


def test_export_and_saved_view_open_the_plot(window, app, tmp_path, monkeypatch):
    window.add_dataset(parse_text('x,y\n1,2\n2,4', name='trace'))
    window.plot_tabs.setCurrentIndex(MAP)
    window.create_view('Map')
    monkeypatch.setattr(W.QFileDialog, 'getSaveFileName', lambda *args: (str(tmp_path / 'plot.png'), 'PNG (*.png)'))
    window.export_plot()
    assert window.plot_window.isVisible() and (tmp_path / 'plot.png').stat().st_size
    window.plot_window.close()
    app.processEvents()
    window.restore_view('Map')
    app.processEvents()
    assert window.plot_window.isVisible() and window.plot_tabs.currentIndex() == MAP


def test_opening_a_project_does_not_pop_the_plot(window, app, tmp_path):
    window.add_dataset(parse_text('x,y\n1,2\n2,4', name='trace'))
    window.show_fitting.setChecked(True)
    window.path = tmp_path / 'project.json'
    window.save()
    window.plot_window.close()
    app.processEvents()
    window.open_project(window.path, confirm=False)
    app.processEvents()
    assert not window.plot_window.isVisible() and window.show_fitting.isChecked()


def test_open_state_and_geometry_persist_per_machine(window, app):
    plot = open_plot(window, app)
    plot.setGeometry(60, 80, 520, 420)
    app.processEvents()
    geometry = plot.geometry()
    window.close()
    assert not plot.isVisible()  # the application would otherwise keep running
    assert window.preferences.value('plot_window_open', type=bool)
    assert 'plot_window_open' not in window.settings()
    reopened = MainWindow()
    try:
        reopened.show()
        reopened.restore_plot_window()
        app.processEvents()
        assert reopened.plot_window.isVisible() and reopened.plot_window.geometry() == geometry
    finally:
        reopened.close()


def test_closed_plot_window_stays_closed_next_time(window, app):
    plot = open_plot(window, app)
    plot.close()
    window.close()
    reopened = MainWindow()
    try:
        reopened.show()
        reopened.restore_plot_window()
        assert not reopened.plot_window.isVisible()
    finally:
        reopened.close()


def test_title_names_view_dataset_and_panel(window, app):
    open_plot(window, app)
    window.add_dataset(parse_text('x,y\n1,2\n2,4', name='trace'))
    assert window.plot_window.windowTitle() == 'Rogi — Line plot — trace'
    window.add_panel()
    assert window.plot_window.windowTitle() == 'Rogi — Line plot — trace (Panel 2)'
    window.plot_tabs.setCurrentIndex(MAP)
    assert window.plot_window.windowTitle() == 'Rogi — 2D map — trace'


def test_hints_and_coordinates_are_in_the_plot_window(window):
    assert window.plot_status is window.plot_window.statusBar()
    assert window.coordinates.window() is window.plot_window


def test_dialogs_open_over_the_active_plot_window(window, app, monkeypatch):
    plot = open_plot(window, app)
    monkeypatch.setattr(W.QApplication, 'activeWindow', staticmethod(lambda: plot))
    assert dialog_parent(window) is plot
    other = W.QWidget()
    monkeypatch.setattr(W.QApplication, 'activeWindow', staticmethod(lambda: other))
    assert dialog_parent(window) is window


def test_toolbar_copy_and_export(window, app, tmp_path, monkeypatch):
    open_plot(window, app)
    window.add_dataset(parse_text('x,y\n1,2\n2,4', name='trace'))
    W.QApplication.clipboard().clear()
    window.navigation.copy_plot()
    assert not W.QApplication.clipboard().image().isNull()
    target = tmp_path / 'map'
    monkeypatch.setattr(W.QFileDialog, 'getSaveFileName', lambda *args: (str(target), 'SVG (*.svg)'))
    window.image_viewer.navigation.export_plot()
    assert (tmp_path / 'map.svg').read_text().lstrip().startswith('<?xml')


def test_file_window_leaves_room_for_the_plot(window):
    from rogi.screen import available_area
    from rogi.ui import FILE_WINDOW_SIZE
    area = available_area(window)
    assert window.width() <= min(FILE_WINDOW_SIZE[0], area.width())
    assert window.height() <= min(FILE_WINDOW_SIZE[1], area.height())


def test_prominent_button_opens_and_raises_the_plot(window, app):
    button = window.open_plot_button
    assert button.isVisible() and button.text() == 'Open plot window'
    assert button.height() >= 48 and window.isAncestorOf(button)
    button.click()
    app.processEvents()
    assert window.plot_window.isVisible() and button.text() == 'Bring plot window to front'
    button.click()  # a second click keeps it open
    app.processEvents()
    assert window.plot_window.isVisible()
    window.plot_window.close()
    app.processEvents()
    assert button.text() == 'Open plot window'
