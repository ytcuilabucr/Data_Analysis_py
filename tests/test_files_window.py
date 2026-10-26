"""File loading opens in its own window, under the file window's lock, dialogs and close."""
import pytest
from PySide6 import QtCore as C, QtWidgets as W
from rogi.dialogs import ImportDialog
from rogi.operations import coordinator, dialog_parent, set_editing_enabled
from rogi.ui import MainWindow, COMPACT_FILE_WIDTH


@pytest.fixture
def window(app):
    window = MainWindow()
    window.show()
    window.restore_files_window()
    app.processEvents()
    yield window
    window.dirty = False
    window.close()
    window.deleteLater()
    app.sendPostedEvents(None, C.QEvent.Type.DeferredDelete)
    app.processEvents()


def sweep(path):
    path.write_text('x\ty\n1\t2\n3\t4\n')
    return path


def open_files(window, app):
    window.open_files_button.click()
    app.processEvents()
    assert window.files_window.isVisible()
    return window.files_window


def test_files_window_is_closed_at_first_and_opens_on_demand(window, app):
    assert not window.files_window.isVisible() and not window.files_action.isChecked()
    assert window.width() <= COMPACT_FILE_WIDTH  # the panel no longer widens the file window
    files = open_files(window, app)
    assert window.files_action.isChecked() and coordinator(files.panel) is window
    files.close()
    app.processEvents()
    assert not window.files_action.isChecked()
    window.files_action.trigger()
    app.processEvents()
    assert files.isVisible()


def test_open_state_and_geometry_persist(window, app):
    files = open_files(window, app)
    files.setGeometry(70, 90, 480, 600)
    app.processEvents()
    geometry = files.geometry()
    window.close()
    assert not files.isVisible()  # the application would otherwise keep running
    assert window.preferences.value('files_window_open', type=bool)
    reopened = MainWindow()
    try:
        reopened.show()
        reopened.restore_files_window()
        app.processEvents()
        assert reopened.files_window.isVisible() and reopened.files_window.geometry() == geometry
    finally:
        reopened.close()


def test_earlier_shown_panel_opens_the_window(window, app):
    window.preferences.setValue('files_panel_shown', True)
    reopened = MainWindow()
    try:
        reopened.show()
        reopened.restore_files_window()
        assert reopened.files_window.isVisible()
    finally:
        reopened.close()


def test_title_names_the_folder_and_dropped_folder_opens_it(window, app, tmp_path):
    folder = tmp_path / 'day1'
    folder.mkdir()
    window.open_files([str(folder)])
    app.processEvents()
    assert window.files_window.isVisible() and window.files_panel.folder == str(folder)
    assert window.files_window.windowTitle() == 'Rogi — Files — day1'


def test_lock_covers_the_files_window(window, app):
    files = open_files(window, app)
    set_editing_enabled(window, False)
    assert not files.centralWidget().isEnabled()
    set_editing_enabled(window, True)
    assert files.centralWidget().isEnabled()


def test_import_dialog_opens_over_the_files_window(window, app, tmp_path, monkeypatch):
    files = open_files(window, app)
    files.activateWindow()
    monkeypatch.setattr(W.QApplication, 'activeWindow', staticmethod(lambda: files))
    assert dialog_parent(window) is files
    parents = []
    def choose(dialog):
        parents.append(dialog.parentWidget())
        dialog.import_data()
        return dialog.result()
    monkeypatch.setattr(ImportDialog, 'exec', choose)
    window.import_paths([sweep(tmp_path / 'a.dat')], preview=True)
    assert parents == [files] and len(window.datasets) == 1


def test_watch_keeps_loading_with_the_window_closed(window, app, tmp_path):
    sweep(tmp_path / 'run_1.dat')
    window.open_files_window(str(tmp_path))
    app.processEvents()
    panel = window.files_panel
    assert not window.watch_indicator.isVisibleTo(window)
    panel.watch.setChecked(True)
    assert window.watch_indicator.isVisibleTo(window)
    assert window.watch_indicator.text() == f'● Watching {tmp_path.name}'
    window.files_window.close()
    app.processEvents()
    new = sweep(tmp_path / 'run_2.dat')
    panel.refresh()
    panel.refresh()  # the size has settled
    assert [d.source for d in window.datasets] == [str(new.resolve())]
    window.watch_indicator.click()
    app.processEvents()
    assert window.files_window.isVisible()
    panel.watch.setChecked(False)
    assert not window.watch_indicator.isVisibleTo(window)
