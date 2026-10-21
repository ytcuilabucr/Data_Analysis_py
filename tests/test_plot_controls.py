import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('MPLCONFIGDIR', '/tmp/rogi-matplotlib-tests')
from types import SimpleNamespace

import numpy as np
import pytest
from PySide6 import QtWidgets as W
from rogi.core import parse_text, fit_dataset
from rogi.project import save_project, load_project
from rogi.plotting import display_values
from rogi.ui import MainWindow


@pytest.fixture
def window():
    app = W.QApplication.instance() or W.QApplication([])
    window = MainWindow()
    yield window
    window.dirty = False
    window.close()


def apply(window, axis='x', scale='log', auto=True, limits=('1', '10')):
    combo, check, low, high = window.axis_controls[axis]
    combo.setCurrentText(scale)
    check.setChecked(auto)
    low.setText(limits[0])
    high.setText(limits[1])
    window.apply_axes()


def test_log_mask_is_display_only(window):
    raw = parse_text('x,y\n-1,-2\n0,1\n1,3\n2,5\n3,7\n4,')
    raw.fit = fit_dataset(raw, 'Linear', -1, 3, True)
    original = raw.values.copy()
    fit = raw.fit.copy()
    window.add_dataset(raw)
    window.show_fitting.setChecked(True)
    apply(window)
    x = window.ax.lines[0].get_xdata()
    assert np.isnan(x[:2]).all()
    assert '2 data row(s)' in window.log_notice.text()
    assert window.ax.get_xscale() == 'log'
    assert window.resax.get_xscale() == 'log'
    assert window.resax.get_yscale() == 'linear'
    np.testing.assert_equal(raw.values, original)
    assert not raw.values.flags.writeable
    assert raw.fit == fit
    apply(window, scale='linear')
    np.testing.assert_equal(window.ax.lines[0].get_xdata()[:5], original[:5, 0])


def test_all_invalid_and_empty_log_axes(window):
    window.add_dataset(parse_text('x,y\n-1,0\n0,-2\n,'))
    apply(window)
    apply(window, axis='y')
    assert all(v > 0 for v in window.ax.get_xlim() + window.ax.get_ylim())
    assert 'Log axes require positive values' in window.log_notice.text()
    assert window.view['x']['auto']
    W.QApplication.processEvents()
    assert window.view['x']['auto']


def test_zoom_survives_updates_and_marks_dirty(window):
    window.add_dataset(parse_text('x,y\n1,2\n2,4\n3,6'))
    window.dirty = False
    window.ax.set_xlim(1.2, 2.2)
    window.ax.set_ylim(2.2, 4.2)
    assert window.dirty
    assert not window.view['x']['auto'] and not window.view['y']['auto']
    window.title.setText('Title')
    window.labels_changed()
    window.legend_position.setCurrentText('lower left')
    window.set_color('#123456')
    window.marker.setCurrentText('Square')
    window.show_fitting.setChecked(True)
    window.search.setText('Imported')
    np.testing.assert_allclose(window.ax.get_xlim(), (1.2, 2.2))
    np.testing.assert_allclose(window.ax.get_ylim(), (2.2, 4.2))
    assert window.ax.lines[0].get_color() == '#123456'
    assert window.ax.lines[0].get_marker() == 's'
    window.dirty = False
    window.redraw()
    W.QApplication.processEvents()
    assert not window.dirty
    assert not window.view['x']['auto']


def test_manual_validation_atomic_and_automatic_reset(window):
    window.add_dataset(parse_text('x,y\n1,2\n2,4\n3,6'))
    apply(window, auto=False, limits=('1', '20'))
    np.testing.assert_allclose(window.ax.get_xlim(), (1, 20))
    saved = window.settings()
    with pytest.raises(ValueError):
        apply(window, auto=False, limits=('0', '20'))
    assert window.settings() == saved
    apply(window, scale='linear')
    assert window.view['x']['auto']
    assert window.ax.get_xlim()[1] < 5


@pytest.mark.parametrize('extension', ['json', 'h5'])
def test_plot_state_roundtrip(window, tmp_path, extension):
    window.add_dataset(parse_text('x,y\n1,2\n2,4\n3,6'))
    window.set_color('#abcdef')
    window.marker.setCurrentText('Diamond')
    window.legend_position.setCurrentText('hidden')
    window.cursor_enabled.setChecked(True)
    window.show_fitting.setChecked(True)
    apply(window, auto=False, limits=('1', '100'))
    window.resax.set_ylim(-2, 2)
    window.path = tmp_path / f'plot.{extension}'
    window.save()
    window.open_project(str(window.path))
    W.QApplication.processEvents()
    assert not window.dirty
    assert window.current().color == '#abcdef'
    assert window.current().marker == 'D'
    assert window.ax.get_xscale() == 'log'
    np.testing.assert_allclose(window.ax.get_xlim(), (1, 100))
    np.testing.assert_allclose(window.resax.get_ylim(), (-2, 2))
    assert window.ax.get_legend() is None
    assert window.cursor_enabled.isChecked()
    assert window.show_fitting.isChecked()
    window.dirty = False
    window.cursor_motion(SimpleNamespace(inaxes=window.ax, xdata=10., ydata=3.))
    assert 'X: 10' in window.coordinates.text()
    assert not window.dirty
    window.cursor_motion(SimpleNamespace(inaxes=None, xdata=None, ydata=None))
    assert window.coordinates.text() == ''


@pytest.mark.parametrize('settings', [
    {'xscale': 'bad'}, {'xscale': 'log', 'xlim': [0, 10]},
    {'yauto': False}, {'yauto': 'yes'}, {'legend': 'bogus'}, {'cursor': 1},
    {'xlim': [1, float('nan')]},
])
def test_invalid_saved_settings(tmp_path, settings):
    with pytest.raises(ValueError):
        save_project(tmp_path / 'bad.json', [], settings)


def test_legacy_defaults_and_zoom_history(window, tmp_path):
    raw = parse_text('x,y\n1,2\n2,4')
    path = tmp_path / 'old.json'
    save_project(path, [raw], {'xlim': [0, 8], 'ylim': [-1, 5]})
    window.open_project(str(path))
    assert window.ax.get_xscale() == 'linear'
    assert window.current().color == ''
    assert not window.view['x']['auto']
    window.navigation.push_current()
    window.ax.set_xlim(1, 2)
    window.navigation.push_current()
    window.navigation.back()
    np.testing.assert_allclose(window.ax.get_xlim(), (0, 8))
    assert window.dirty
    window.navigation.forward()
    np.testing.assert_allclose(window.ax.get_xlim(), (1, 2))

    window.navigation.home()
    np.testing.assert_allclose(window.ax.get_xlim(), (0, 8))


def test_automatic_roundtrip_and_redraw_stay_automatic(window, tmp_path):
    window.add_dataset(parse_text('x,y\n1,2\n2,4'))
    apply(window)
    window.path = tmp_path / 'auto.h5'
    window.save()
    window.open_project(str(window.path))
    window.redraw()
    W.QApplication.processEvents()
    assert window.view['x']['auto']
    assert window.view['y']['auto']
    assert not window.dirty
    window.add_dataset(parse_text('x,y\n10,20\n100,200'))
    assert window.ax.get_xlim()[1] > 100
    assert window.view['x']['auto']


def test_invalid_loaded_presentation(tmp_path):
    import json
    path = tmp_path / 'invalid.json'
    raw = parse_text('x,y\n1,2')
    save_project(path, [raw], {})
    payload = json.loads(path.read_text())
    payload['datasets'][0]['color'] = 'invalid color'
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match='color'):
        load_project(path)
    payload['datasets'][0]['color'] = ''
    payload['settings'] = {'xscale': 'log', 'xlim': [-1, 2]}
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match='positive'):
        load_project(path)
