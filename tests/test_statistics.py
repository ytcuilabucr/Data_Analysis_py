import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('MPLCONFIGDIR', '/tmp/rogi-matplotlib-tests')
from types import SimpleNamespace
import numpy as np
import pytest
from PySide6 import QtWidgets as W
from rogi.core import parse_text, region_statistics
from rogi.ui import MainWindow


def test_statistics_inclusive_unsorted_duplicates_and_missing():
    d = parse_text('x,y\n3,6\n1,2\n2,4\n2,8\n2,\n,10\n4,99')
    original = d.values.copy()
    result = region_statistics(d, 1, 3)
    assert result['rows'] == [0, 1, 2, 3]
    assert result['count'] == 4
    assert result['missing_x'] == 1 and result['missing_y'] == 1
    for key, expected in dict(minimum=2, maximum=8, mean=5, median=5, sum=20,
                              variance=20/3, std=np.sqrt(20/3), sem=np.sqrt(20/3)/2,
                              rms=np.sqrt(30), q1=3.5, q3=6.5).items():
        assert result[key] == pytest.approx(expected)
    assert region_statistics(d, 1, 3, sample=False)['variance'] == pytest.approx(5)
    rectangle = region_statistics(d, 1, 3, 4, 6)
    assert rectangle['rows'] == [0, 2]
    np.testing.assert_equal(d.values, original)
    assert not d.values.flags.writeable
    assert d.edits == [] and d.revision == 0


def test_empty_singleton_and_invalid_bounds():
    d = parse_text('x,y\n1,2\n2,')
    empty = region_statistics(d, 4, 5)
    assert empty['count'] == 0 and empty['mean'] is None
    single = region_statistics(d, 1, 1)
    assert single['mean'] == 2 and single['std'] is None
    assert region_statistics(d, 1, 1, sample=False)['std'] == 0
    for bounds in [(3, 1), (0, np.inf), (0, 3, 4, 2), (0, 3, 1, None)]:
        with pytest.raises(ValueError):
            region_statistics(d, *bounds)


@pytest.fixture
def window():
    app = W.QApplication.instance() or W.QApplication([])
    w = MainWindow()
    w.add_dataset(parse_text('x,y,z\n1,2,10\n2,4,20\n3,6,30\n4,,40'))
    w.show_statistics.setChecked(True)
    yield w
    w.dirty = False
    w.close()


def test_selection_statistics_zoom_and_context(window):
    window.ax.set_xlim(1, 3)
    window.dirty = False
    window.statistics_selected(1, 3)
    assert 'Mean: 4' in window.stats_result.toPlainText()
    assert 'Count: 3' in window.stats_result.toPlainText()
    assert not window.dirty
    np.testing.assert_allclose(window.ax.get_xlim(), [1, 3])
    window.redraw()
    assert window.stats_region == (1, 3, None, None)
    np.testing.assert_allclose(window.stats_selector.extents, [1, 3])
    window.stats_mode.setCurrentText('Rectangle')
    window.statistics_rectangle_selected(SimpleNamespace(xdata=3, ydata=6),
                                         SimpleNamespace(xdata=1, ydata=3))
    assert 'Count: 2' in window.stats_result.toPlainText()
    assert 'Mean: 5' in window.stats_result.toPlainText()
    window.y.setCurrentText('z')
    assert window.stats_region is None
    assert 'Mean:' not in window.stats_result.toPlainText()


def test_stats_refresh_after_edit_and_mutually_exclusive_tools(window):
    window.make_copy()
    window.statistics_selected(1, 3)
    window.table_model.setData(window.table_model.index(0, 1), '8')
    assert 'Mean: 6' in window.stats_result.toPlainText()
    window.navigation.pan()
    window.stats_drag.setChecked(True)
    assert not window.navigation.mode
    assert window.stats_selector.active
    window.drag.setChecked(True)
    assert not window.stats_drag.isChecked()
    assert window.span.active
    window.stats_drag.setChecked(True)
    assert not window.drag.isChecked()
    window.show_statistics.setChecked(False)
    assert not window.stats_selector.active


def test_invalid_manual_entry_retains_previous_result(window):
    window.statistics_selected(1, 3)
    result = window.stats_result.toPlainText()
    window.stats_bounds[0].setText('nan')
    with pytest.raises(ValueError):
        window.calculate_statistics()
    assert window.stats_region == (1, 3, None, None)
    assert window.stats_result.toPlainText() == result
    window.browser.clearSelection()
    assert 'Mean:' not in window.stats_result.toPlainText()


def test_statistics_uses_stored_log_hidden_values(window):
    d = window.current()
    window.make_copy()
    window.current().edit(0, 1, '-2')
    window.axis_controls['y'][0].setCurrentText('log')
    window.apply_axes()
    window.statistics_selected(1, 3)
    assert 'Mean: 2.666666667' in window.stats_result.toPlainText()
    assert 'Log-hidden values are included' in window.stats_result.toPlainText()
    assert d.values[0, 1] == 2


@pytest.mark.parametrize('mode', ['X range', 'Rectangle'])
def test_mouse_drag_selects_region(window, mode):
    from matplotlib.backend_bases import MouseEvent
    window.stats_mode.setCurrentText(mode)
    window.stats_drag.setChecked(True)
    window.show()
    W.QApplication.processEvents()
    window.canvas.draw()
    for name, point in [('button_press_event', (1.1, 2.1)),
                        ('motion_notify_event', (3.1, 6.1)),
                        ('button_release_event', (3.1, 6.1))]:
        px, py = window.ax.transData.transform(point)
        event = MouseEvent(name, window.canvas, px, py, button=1)
        window.canvas.callbacks.process(name, event)
    assert window.stats_region is not None
    assert 'Count: 2' in window.stats_result.toPlainText()
    assert 'Mean: 5' in window.stats_result.toPlainText()


def test_statistics_does_not_expand_automatic_view(window):
    before = window.ax.get_xlim(), window.ax.get_ylim()
    window.statistics_selected(1, 3)
    for _ in range(3):
        window.redraw()
    np.testing.assert_allclose(window.ax.get_xlim(), before[0])
    np.testing.assert_allclose(window.ax.get_ylim(), before[1])
    assert window.view['x']['auto'] and window.view['y']['auto']
