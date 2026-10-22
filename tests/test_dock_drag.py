"""Dragging a docked plot out of the main window must not crash Qt.

The drag runs in a subprocess: a regression is a segmentation fault, which
would otherwise take the whole test session down.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = r'''
import sys
from PySide6 import QtCore as C, QtGui as G, QtWidgets as W
from PySide6.QtTest import QTest
app = W.QApplication([])
from rogi import ui
from rogi.core import parse_text
ui.project_preferences = lambda: C.QSettings(sys.argv[2], C.QSettings.Format.IniFormat)
window = ui.MainWindow()
window.resize(1400, 850)
window.show()
window.add_dataset(parse_text('x,y\n1,2\n2,4', name='trace'))
dock = window.plot_docks[int(sys.argv[1])]
window.plot_tabs.setCurrentIndex(int(sys.argv[1]))
QTest.qWait(100)
start, delta = C.QPoint(dock.width() // 2, 8), C.QPoint(250, 200)
QTest.mousePress(dock, C.Qt.MouseButton.LeftButton, C.Qt.KeyboardModifier.NoModifier, start)
for step in range(1, 16):
    point = start + delta * step / 15
    app.sendEvent(dock, G.QMouseEvent(G.QMouseEvent.Type.MouseMove, C.QPointF(point),
                                      C.QPointF(dock.mapToGlobal(point)), C.Qt.MouseButton.NoButton,
                                      C.Qt.MouseButton.LeftButton, C.Qt.KeyboardModifier.NoModifier))
    QTest.qWait(10)
QTest.mouseRelease(dock, C.Qt.MouseButton.LeftButton, C.Qt.KeyboardModifier.NoModifier, start + delta)
QTest.qWait(100)
print('floating' if dock.isFloating() else 'docked')
window.dirty = False
window.close()
'''


@pytest.mark.parametrize('view', [0, 1])
def test_dragging_a_docked_plot_out(view, tmp_path):
    env = dict(os.environ, QT_QPA_PLATFORM=os.environ.get('QT_QPA_PLATFORM', 'offscreen'))
    result = subprocess.run([sys.executable, '-c', SCRIPT, str(view), str(tmp_path / 'preferences.ini')],
                            cwd=Path(__file__).resolve().parent.parent, env=env,
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr[-2000:]
    assert result.stdout.split()[-1] == 'floating'
