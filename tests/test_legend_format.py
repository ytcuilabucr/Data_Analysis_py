import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('MPLCONFIGDIR', '/tmp/rogi-matplotlib-tests')

import pytest
from PySide6 import QtCore as C
from matplotlib.backend_bases import MouseButton, MouseEvent
from matplotlib.colors import to_hex
from rogi import plot_context
from rogi.core import fit_dataset, parse_text
from rogi.legend_format import NAME, SHOW, TEXT, FormatLegendDialog
from rogi.plotting import PLOT_STYLE, validate_view
from rogi.ui import MainWindow


@pytest.fixture
def window():
    window = MainWindow()
    for name, values in (('Run A', '1,2\n2,4\n3,6'), ('Run B', '1,3\n2,5\n3,9'), ('Run C', '1,1\n2,1\n3,2')):
        d = parse_text('x,y\n' + values)
        d.name = name
        window.add_dataset(d)
    for d in window.datasets:
        d.visible = True
    window.title.setText('Title')
    window.labels_changed()
    window.canvas.draw()
    window.history.clear()
    window.dirty = window.external_dirty = False
    yield window
    window.dirty = False
    window.close()


def labels(axes):
    legend = axes.get_legend()
    return [t.get_text() for t in legend.texts] if legend else []


def row_of(d, name):
    return next(r for r in range(d.table.rowCount()) if d.table.item(r, NAME).text() == name)


def center(window, artist):
    box = artist.get_window_extent(window.canvas.get_renderer())
    return (box.x0 + box.x1) / 2, (box.y0 + box.y1) / 2


def test_right_click_opens_the_dialog_on_the_clicked_entry(window, monkeypatch):
    opened = []
    monkeypatch.setattr(plot_context, 'format_legend', lambda w, index, dataset_id=None: opened.append((index, dataset_id)))
    legend = window.ax.get_legend()
    for artist, button in ((legend.texts[1], MouseButton.RIGHT), (legend.texts[1], MouseButton.LEFT)):
        plot_context.canvas_pressed(window, MouseEvent('button_press_event', window.canvas,
                                                       *center(window, artist), button=button))
    assert opened == [(0, window.datasets[1].id)]  # the left button drags instead
    event = MouseEvent('button_press_event', window.canvas, *center(window, legend), button=MouseButton.RIGHT)
    assert plot_context.context_menu(window, event) is None
    x, y = window.ax.transAxes.transform((.5, .02))
    background = MouseEvent('button_press_event', window.canvas, x, y, button=MouseButton.RIGHT)
    assert 'Format legend…' in [a.text() for a in plot_context.context_menu(window, background).actions()]
    d = FormatLegendDialog(window, 0, window.datasets[1].id)
    assert d.table.currentRow() == row_of(d, 'Run B') and d.table.currentColumn() == TEXT
    d.reject()


def test_entries_rename_hide_and_reorder_as_one_undo_step(window):
    d = FormatLegendDialog(window, 0)
    d.table.item(row_of(d, 'Run B'), TEXT).setText('Sample B')
    d.table.item(row_of(d, 'Run A'), SHOW).setCheckState(C.Qt.CheckState.Unchecked)
    d.table.selectRow(row_of(d, 'Run C'))
    d.move(-1)
    d.move(-1)
    d.move(-1)  # already first: nothing happens
    d.preview()
    assert labels(window.ax) == ['Run C', 'Sample B']
    assert window.history.count() == 0
    d.accept()
    assert window.history.count() == 1 and window.history.undoText() == 'Format legend'
    assert [x.name for x in window.datasets] == ['Run A', 'Run B', 'Run C']
    # Right-clicking an entry still finds its dataset after reordering.
    window.canvas.draw()
    entry = plot_context.hit(window, MouseEvent('button_press_event', window.canvas,
                                                *center(window, window.ax.get_legend().texts[1])))
    assert entry == ('legend', 0, window.datasets[1].id)
    window.history.undo()
    assert labels(window.ax) == ['Run A', 'Run B', 'Run C']
    assert window.legend_labels == {} and window.legend_hidden == [] and window.legend_order == []
    window.history.redo()
    assert labels(window.ax) == ['Run C', 'Sample B']


def test_cancel_restores_and_ok_without_changes_records_nothing(window):
    window.panels[0]['legend_anchor'] = [.3, .4]
    window.redraw()
    d = FormatLegendDialog(window, 0)
    d.table.item(0, TEXT).setText('Renamed')
    d.position.setCurrentText('lower left')
    d.title.setText('Runs')
    d.columns.setValue(3)
    d.preview()
    assert window.ax.get_legend().get_title().get_text() == 'Runs'
    assert 'legend_anchor' not in window.panels[0]  # a chosen position replaces a dragged one
    d.reject()
    assert labels(window.ax) == ['Run A', 'Run B', 'Run C']
    assert window.panels[0]['legend_anchor'] == [.3, .4]
    assert window.legend_position.currentText() == 'best' and window.plot_style['legend_columns'] == 1
    assert window.history.count() == 0 and not window.dirty
    FormatLegendDialog(window, 0).accept()
    assert window.history.count() == 0


def test_show_legend_and_dragged_position(window):
    window.panels[0]['legend_anchor'] = [.3, .4]
    window.redraw()
    d = FormatLegendDialog(window, 0)
    assert d.reset_drag.isEnabled()
    d.reset_drag.click()
    d.show_legend.setChecked(False)
    assert not d.position.isEnabled()
    d.accept()
    assert window.ax.get_legend() is None and window.legend_position.currentText() == 'hidden'
    assert 'legend_anchor' not in window.panels[0]
    d = FormatLegendDialog(window, 0)
    d.show_legend.setChecked(True)
    d.accept()
    assert window.ax.get_legend() is not None and window.legend_position.currentText() == 'best'


def test_outside_positions_leave_the_plot_and_the_title_clear(window):
    renderer = window.canvas.get_renderer()
    d = FormatLegendDialog(window, 0)
    d.position.setCurrentText('outside right')
    d.accept()
    window.canvas.draw()
    assert window.ax.get_legend().get_window_extent(renderer).x0 >= window.ax.bbox.x1
    d = FormatLegendDialog(window, 0)
    d.position.setCurrentText('outside top')
    d.accept()
    window.canvas.draw()
    legend = window.ax.get_legend().get_window_extent(renderer)
    assert legend.y0 >= window.ax.bbox.y1
    assert window.ax.title.get_window_extent(renderer).y0 >= legend.y1 - 1


def test_appearance_settings_reach_the_legend(window):
    d = FormatLegendDialog(window, 0)
    d.title.setText('Runs')
    d.size.setCurrentIndex(d.size.findData(12))
    d.color.set_color('#0000ff')
    d.columns.setValue(2)
    d.marker_scale.setValue(2)
    d.spacing.setValue(1)
    d.frame_color.set_color('#ff0000')
    d.background.set_color('#ffffe0')
    d.opacity.setValue(50)
    d.rounded.setChecked(False)
    d.accept()
    legend = window.ax.get_legend()
    assert legend.get_title().get_text() == 'Runs' and to_hex(legend.get_title().get_color()) == '#0000ff'
    assert legend.texts[0].get_fontsize() == 12 and to_hex(legend.texts[0].get_color()) == '#0000ff'
    assert legend._ncols == 2 and legend.markerscale == 2 and legend.labelspacing == 1
    frame = legend.get_frame()
    assert frame.get_edgecolor()[:3] == (1, 0, 0) and frame.get_alpha() == .5
    assert frame.get_boxstyle().__class__.__name__ == 'Square'
    d = FormatLegendDialog(window, 0)
    d.default_appearance()
    d.accept()
    assert {k: v for k, v in window.plot_style.items() if k.startswith('legend_')} == \
        {k: v for k, v in PLOT_STYLE.items() if k.startswith('legend_')}


def test_fit_entries_and_residual_legend(window):
    d0 = window.current()
    d0.fit = fit_dataset(d0, 'Linear', 1, 3, True)
    window.show_fitting.setChecked(True)
    assert f'{d0.name} fit' in labels(window.ax) and window.resax.get_legend() is not None
    d = FormatLegendDialog(window, 0)
    d.fit_entries.setChecked(False)
    d.residuals.setChecked(False)
    d.accept()
    assert f'{d0.name} fit' not in labels(window.ax) and window.resax.get_legend() is None
    d = FormatLegendDialog(window, 0)
    d.fit_entries.setChecked(True)
    d.table.item(row_of(d, d0.name), TEXT).setText('Renamed')
    d.accept()
    assert 'Renamed fit' in labels(window.ax)


def test_order_hidden_and_style_roundtrip_and_validation(window, tmp_path):
    d = FormatLegendDialog(window, 0)
    d.table.item(row_of(d, 'Run B'), SHOW).setCheckState(C.Qt.CheckState.Unchecked)
    d.table.selectRow(row_of(d, 'Run C'))
    d.move(-1)
    d.position.setCurrentText('outside right')
    d.opacity.setValue(30)
    d.accept()
    window.path = tmp_path / 'legend.h5'
    window.save()
    window.legend_order, window.legend_hidden = [], []
    window.open_project(str(window.path))
    assert labels(window.ax) == ['Run A', 'Run C']
    assert window.legend_position.currentText() == 'outside right' and window.plot_style['legend_alpha'] == .3
    for bad in ({'legend_order': 'a'}, {'legend_hidden': [1]}, {'legend': 'outside left'},
                {'plot_style': {'legend_alpha': 2}}, {'plot_style': {'legend_color': 'nope'}},
                {'plot_style': {'legend_title': 3}}, {'plot_style': {'legend_marker_scale': 0}},
                {'plot_style': {'legend_residuals': 'no'}}):
        with pytest.raises(ValueError):
            validate_view(bad)
