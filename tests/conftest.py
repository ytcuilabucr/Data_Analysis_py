"""Keep one Qt application alive until every test widget has been disposed."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('MPLCONFIGDIR', '/tmp/rogi-matplotlib-tests')

import gc
import pytest
from PySide6 import QtCore as C, QtWidgets as W


@pytest.fixture(scope='session', autouse=True)
def app():
    application = W.QApplication.instance() or W.QApplication([])
    yield application
    # Qt must dispose its widgets before Python tears down QApplication.
    for widget in application.topLevelWidgets():
        widget.deleteLater()
    application.sendPostedEvents(None, C.QEvent.Type.DeferredDelete)
    application.processEvents()
    gc.collect()


@pytest.fixture(autouse=True)
def isolated_preferences(tmp_path, monkeypatch):
    from rogi import ui
    monkeypatch.setattr(ui, 'project_preferences', lambda: C.QSettings(
        str(tmp_path / 'preferences.ini'), C.QSettings.Format.IniFormat))
