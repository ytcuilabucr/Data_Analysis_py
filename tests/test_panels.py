import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('MPLCONFIGDIR', '/tmp/rogi-matplotlib-tests')
from types import SimpleNamespace
from copy import deepcopy
import numpy as np
import pytest
from PySide6 import QtWidgets as W
from rogi.ui import MainWindow
from rogi.core import parse_text, fit_dataset
from rogi.project import save_project, load_project
from rogi.plotting import validate_view


@pytest.fixture
def window():
    app = W.QApplication.instance() or W.QApplication([])
    w = MainWindow()
    w.add_dataset(parse_text('time,voltage,current\n1,2,100\n2,4,300\n3,6,900'))
    yield w
    w.dirty = False
    w.close()


def two_panels(w):
    w.add_panel()
    w.y.setCurrentIndex(2)


def test_channels_axes_and_active_fit(window):
    w = window
    two_panels(w)
    a, b = [pair[0] for pair in w.panel_axes]
    np.testing.assert_equal(a.lines[0].get_ydata(), [2, 4, 6])
    np.testing.assert_equal(b.lines[0].get_ydata(), [100, 300, 900])
    assert a.get_ylim()[1] < 10 < b.get_ylim()[1]
    assert a.get_ylabel() == 'voltage' and b.get_ylabel() == 'current'
    w.activate_panel(0)
    assert w.current().ycol == 1
    w.current().fit = fit_dataset(w.current(), 'Linear', 1, 3, True)
    w.show_fitting.setChecked(True)
    assert len(w.ax.lines) >= 2
    assert w.resax.get_visible()
    assert not w.panel_axes[1][1].get_visible()
    w.activate_panel(1)
    assert w.current().ycol == 2
    assert not any(line.get_label().endswith(' fit') for line in w.ax.lines)


def test_sync_zoom_and_cursor(window):
    w = window
    two_panels(w)
    w.sync_x_control.setChecked(True)
    w.panel_axes[0][0].set_xlim(1.2, 2.5)
    for panel, pair in zip(w.panels, w.panel_axes):
        np.testing.assert_allclose(pair[0].get_xlim(), [1.2, 2.5])
        assert not panel['view']['x']['auto']
    w.panel_axes[0][0].set_ylim(0, 10)
    assert w.panel_axes[1][0].get_ylim()[1] > 100
    w.cursor_enabled.setChecked(True)
    w.cursor_motion(SimpleNamespace(inaxes=w.panel_axes[0][0], xdata=2, ydata=4))
    assert all(line.get_visible() and line.get_xdata()[0] == 2 for line in w.shared_cursor_lines)
    w.cursor_motion(SimpleNamespace(inaxes=None, xdata=None, ydata=None))
    assert not any(line.get_visible() for line in w.shared_cursor_lines)
    w.sync_x_control.setChecked(False)
    w.panel_axes[0][0].set_xlim(1, 2)
    assert w.panel_axes[1][0].get_xlim() != (1, 2)


def test_layout_roundtrip_and_export(window, tmp_path):
    w = window
    two_panels(w)
    w.create_view('Channels')
    w.remove_panel()
    w.restore_view('Channels')
    assert len(w.panels) == 2 and w.active_panel == 1
    assert w.current().ycol == 2
    assert w.y.currentIndex() == 2
    path = tmp_path / 'panels.h5'
    save_project(path, w.datasets, w.settings())
    _, settings = load_project(path)
    assert settings['panels'] == w.settings()['panels']
    w.open_project(path, confirm=False)
    assert len(w.panels) == 2
    out = tmp_path / 'panels.svg'
    w.figure.savefig(out)
    svg = out.read_text()
    assert 'voltage' in svg and 'current' in svg
    assert 'Panel 1' in svg and 'Panel 2' in svg


def test_missing_assignment_and_validation(window):
    w = window
    two_panels(w)
    settings = w.settings()
    broken = deepcopy(settings)
    broken['panels'][0]['channels'][w.current().id] = [-1, 2]
    with pytest.raises(ValueError):
        validate_view(broken)
    w.unassign_panel_channel()
    assert not w.panel_datasets(w.panels[1])
    w.assign_panel_channel()
    assert len(w.panel_datasets(w.panels[1])) == 1
    w.datasets.clear()
    w.redraw()


def test_panel_overlays_and_labels(window):
    w = window
    w.ylabel.setText('Potential (V)')
    w.labels_changed()
    two_panels(w)
    other = parse_text('time,other\n1,200\n2,400\n3,800')
    w.add_dataset(other)
    w.assign_panel_channel()
    assert len(w.panel_datasets(w.panels[1])) == 2
    w.activate_panel(0)
    assert w.ax.get_ylabel() == 'Potential (V)'
    w.activate_panel(1)
    assert w.ylabel.text() == ''
    assert w.ax.get_ylabel() == 'current, other'
