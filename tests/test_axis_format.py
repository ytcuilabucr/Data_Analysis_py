import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('MPLCONFIGDIR', '/tmp/rogi-matplotlib-tests')

import numpy as np
import pytest
from matplotlib.backend_bases import MouseButton, MouseEvent
from rogi import plot_context
from rogi.axis_format import FormatAxisDialog
from rogi.core import parse_text
from rogi.plotting import AXIS_STYLE, full_plot_style, validate_view
from rogi.ui import MainWindow


@pytest.fixture
def window():
    window = MainWindow()
    a = parse_text('Bias (V),Current (nA)\n1,2\n2,4\n3,6')
    b = parse_text('Bias (V),Current (nA)\n1,3\n2,5\n3,9')
    a.name, b.name = 'Run A', 'Run B'
    window.add_dataset(a)
    window.add_dataset(b)
    for d in window.datasets:
        d.visible = True
    window.redraw()
    window.canvas.draw()
    window.dirty = window.external_dirty = False
    window.history.clear()  # the datasets above are not what these tests undo
    yield window
    window.dirty = False
    window.close()


def dialog(window, axis='y', index=0):
    return FormatAxisDialog(window, axis, index)


def test_preview_then_ok_is_one_undo_step(window):
    before_label = window.ax.get_ylabel()
    d = dialog(window)
    d.text.setText('Tunnel current')
    d.label_size.setCurrentIndex(d.label_size.findData(16))
    d.tick_size.setCurrentIndex(d.tick_size.findData(7))
    d.bold.setChecked(True)
    d.set_color('#aa0000')
    d.auto.setChecked(False)
    d.low.setText('0')
    d.high.setText('20')
    d.preview()
    label = window.ax.yaxis.label
    assert label.get_text() == 'Tunnel current (nA)'
    assert label.get_fontsize() == 16 and label.get_weight() == 'bold' and label.get_color() == '#aa0000'
    assert window.ax.yaxis.get_ticklabels()[0].get_fontsize() == 7
    np.testing.assert_allclose(window.ax.get_ylim(), [0, 20])
    assert window.history.count() == 0  # previews are not history
    d.accept()
    assert window.history.count() == 1 and window.history.undoText() == 'Format Y axis'
    assert window.dirty
    window.history.undo()
    assert window.ax.get_ylabel() == before_label
    assert window.plot_style['y_axis'] == AXIS_STYLE and window.view['y']['auto']
    assert window.ylabel.text() == ''
    window.history.redo()
    assert window.ax.get_ylabel() == 'Tunnel current (nA)'
    np.testing.assert_allclose(window.ax.get_ylim(), [0, 20])


def test_cancel_restores_and_records_nothing(window):
    limits = window.ax.get_xlim()
    d = dialog(window, 'x')
    d.text.setText('Sample bias')
    d.family.setCurrentIndex(d.family.findData('serif'))
    d.scale.setCurrentText('log')
    d.preview()
    assert window.ax.get_xscale() == 'log' and window.xlabel.text() == 'Sample bias'
    d.reject()
    assert window.ax.get_xscale() == 'linear' and window.xlabel.text() == ''
    assert window.plot_style['x_axis']['family'] == ''
    np.testing.assert_allclose(window.ax.get_xlim(), limits)
    assert window.history.count() == 0 and not window.dirty


def test_ok_without_changes_records_nothing(window):
    dialog(window).accept()
    assert window.history.count() == 0


def test_unit_option_and_math_text(window):
    d = dialog(window)
    assert '(nA)' in d.unit.text()
    d.text.setText('I$_{tip}$')
    d.unit.setChecked(False)
    d.preview()
    assert window.ax.get_ylabel() == 'I$_{tip}$'
    d.text.setText('I$_{tip$')
    assert d.preview() is None
    assert 'Cannot draw' in d.status.text()
    assert not d.buttons.button(d.buttons.StandardButton.Ok).isEnabled()
    assert window.ax.get_ylabel() == 'I$_{tip}$'  # the last valid preview stays
    d.reject()


@pytest.mark.parametrize('scale, low, high, message', [
    ('linear', '5', '1', 'less than'), ('linear', 'abc', '1', 'number'), ('log', '-1', '10', 'positive')])
def test_invalid_range_keeps_the_plot(window, scale, low, high, message):
    limits = window.ax.get_ylim()
    d = dialog(window)
    d.scale.setCurrentText(scale)
    d.auto.setChecked(False)
    d.low.setText(low)
    d.high.setText(high)
    assert d.preview() is None and message in d.status.text()
    d.accept()  # refused while invalid
    assert d.result() == 0 and window.history.count() == 0
    np.testing.assert_allclose(window.ax.get_ylim(), limits)
    d.reject()


def test_y_axis_belongs_to_its_panel_and_synchronized_x_to_all(window):
    window.add_panel()
    window.activate_panel(1)
    d = dialog(window, 'y', 0)
    d.text.setText('Left only')
    d.auto.setChecked(False)
    d.low.setText('-1')
    d.high.setText('1')
    d.accept()
    first, second = (pair[0] for pair in window.panel_axes)
    assert first.get_ylabel() == 'Left only (nA)' and second.get_ylabel() != 'Left only (nA)'
    np.testing.assert_allclose(first.get_ylim(), [-1, 1])
    assert window.panels[1]['view']['y']['auto']
    window.sync_x_control.setChecked(True)
    d = dialog(window, 'x', 0)
    d.auto.setChecked(False)
    d.low.setText('1.5')
    d.high.setText('2.5')
    d.accept()
    for pair in window.panel_axes:
        np.testing.assert_allclose(pair[0].get_xlim(), [1.5, 2.5])


def test_style_roundtrip_legacy_sizes_and_validation(window, tmp_path):
    window.plot_style['x_axis'].update(family='serif', italic=True, unit=False)
    window.path = tmp_path / 'axes.h5'
    window.save()
    window.plot_style['x_axis'].update(AXIS_STYLE)
    window.open_project(str(window.path))
    assert window.plot_style['x_axis']['family'] == 'serif' and window.plot_style['x_axis']['italic']
    assert window.plot_style['y_axis'] == AXIS_STYLE
    assert window.plot_style['x_axis'] is not window.plot_style['y_axis']
    legacy = full_plot_style({'label_size': 14, 'tick_size': 9, 'title_size': 12})
    assert legacy['x_axis']['label_size'] == legacy['y_axis']['label_size'] == 14
    assert legacy['y_axis']['tick_size'] == 9 and 'label_size' not in legacy
    validate_view({'plot_style': {'label_size': 14}})
    for bad in ({'x_axis': {'color': 'not a color'}}, {'y_axis': {'bold': 1}},
                {'x_axis': {'label_size': 200}}, {'x_axis': {'bogus': 1}}):
        with pytest.raises(ValueError):
            validate_view({'plot_style': bad})


def test_right_click_or_double_click_on_an_axis_opens_the_dialog(window, monkeypatch):
    renderer = window.canvas.get_renderer()
    opened = []
    monkeypatch.setattr(plot_context, 'format_axis', lambda w, axis, index: opened.append((axis, index)))

    def press(artist, **options):
        box = artist.get_window_extent(renderer)
        event = MouseEvent('button_press_event', window.canvas, (box.x0 + box.x1) / 2, (box.y0 + box.y1) / 2,
                           **options)
        plot_context.canvas_pressed(window, event)
        return event

    event = press(window.ax.yaxis.get_ticklabels()[1], button=MouseButton.RIGHT)
    assert plot_context.hit(window, event) == ('ylabel', 0, None)
    assert plot_context.context_menu(window, event) is None
    press(window.ax.xaxis.label, button=MouseButton.RIGHT)
    press(window.ax.yaxis.label, button=MouseButton.LEFT, dblclick=True)
    press(window.ax.yaxis.label, button=MouseButton.LEFT)  # a single left click does nothing
    assert opened == [('y', 0), ('x', 0), ('y', 0)]
    x, y = window.ax.transAxes.transform((.98, .02))
    background = MouseEvent('button_press_event', window.canvas, x, y, button=MouseButton.RIGHT)
    texts = [a.text() for a in plot_context.context_menu(window, background).actions()]
    assert texts[:2] == ['Format X axis…', 'Format Y axis…'] and 'Edit X label…' not in texts


def test_automatic_button_clears_the_label(window):
    d = dialog(window)
    d.text.setText('Custom')
    next(b for b in d.findChildren(type(d.color_button)) if b.text() == 'Automatic' and b is not d.color_button).click()
    assert d.text.text() == ''
    d.reject()


def test_ticks_tab_sets_direction_length_minor_format_and_spacing(window):
    d = dialog(window, 'x')
    d.direction.setCurrentIndex(d.direction.findData('in'))
    d.length.setCurrentIndex(d.length.findData(7))
    d.minor.setCurrentIndex(d.minor.findData('on'))
    d.number_format.setCurrentIndex(d.number_format.findData('fixed'))
    d.decimals.setValue(3)
    d.fixed_step.setChecked(True)
    d.step.setText('0.5')
    d.grid.setChecked(False)
    d.accept()
    window.canvas.draw()
    axis = window.ax.xaxis
    tick = axis.get_major_ticks()[0]
    assert tick._tickdir == 'in' and tick.tick1line.get_markersize() == 7
    assert type(axis.get_minor_locator()).__name__ == 'AutoMinorLocator'
    np.testing.assert_allclose(np.diff(axis.get_majorticklocs()), 0.5)
    labels = [t.get_text() for t in window.ax.xaxis.get_ticklabels() if t.get_text()]
    assert labels and all(label.split('.')[-1].isdigit() and len(label.split('.')[-1]) == 3 for label in labels)
    assert not any(line.get_visible() for line in axis.get_gridlines())
    assert any(line.get_visible() for line in window.ax.yaxis.get_gridlines())


def test_scientific_format_and_too_dense_spacing_falls_back(window):
    d = dialog(window)
    d.number_format.setCurrentIndex(d.number_format.findData('scientific'))
    d.auto.setChecked(False)
    d.low.setText('0')
    d.high.setText('2000')
    d.fixed_step.setChecked(True)
    d.step.setText('1e-9')
    d.accept()
    window.canvas.draw()
    assert '10^{3}' in window.ax.yaxis.get_offset_text().get_text()  # the ×10³ multiplier
    assert len(window.ax.yaxis.get_majorticklocs()) < 50
    d = dialog(window)
    d.step.setText('-1')
    assert d.preview() is None and 'positive' in d.status.text()
    d.step.setText('x')
    assert d.preview() is None and 'number' in d.status.text()
    d.reject()


def test_spacing_is_disabled_on_log_scales(window):
    d = dialog(window)
    d.scale.setCurrentText('log')
    assert not d.fixed_step.isEnabled() and not d.step.isEnabled()
    assert not d.decimals.isEnabled()
    d.number_format.setCurrentIndex(d.number_format.findData('fixed'))
    assert d.decimals.isEnabled()
    d.reject()


def test_invert_keeps_limits_ascending_and_survives_zoom(window):
    d = dialog(window)
    d.invert.setChecked(True)
    d.accept()
    low, high = window.ax.get_ylim()
    assert low > high and window.view['y']['limits'][0] < window.view['y']['limits'][1]
    window.ax.set_ylim(5, 1)  # a zoom on the inverted axis
    assert window.view['y']['limits'] == [1, 5]
    window.redraw()
    assert window.ax.get_ylim() == (5, 1)
    window.history.undo()
    assert window.ax.get_ylim()[0] < window.ax.get_ylim()[1]


def test_copy_style_to_other_axis_in_the_same_step(window):
    d = dialog(window, 'x')
    d.family.setCurrentIndex(d.family.findData('serif'))
    d.direction.setCurrentIndex(d.direction.findData('inout'))
    d.unit.setChecked(False)
    d.fixed_step.setChecked(True)
    d.step.setText('0.5')
    d.invert.setChecked(True)
    d.copy_style.setChecked(True)
    d.preview()
    y = window.plot_style['y_axis']
    assert y['family'] == 'serif' and y['tick_direction'] == 'inout'
    assert y['unit'] and y['tick_step'] is None and not y['invert']  # value settings stay per axis
    d.accept()
    assert window.history.count() == 1
    window.history.undo()
    assert window.plot_style['y_axis'] == AXIS_STYLE and window.plot_style['x_axis'] == AXIS_STYLE
    d = dialog(window, 'x')
    d.family.setCurrentIndex(d.family.findData('serif'))
    d.copy_style.setChecked(True)
    d.preview()
    d.copy_style.setChecked(False)
    d.preview()
    assert window.plot_style['y_axis']['family'] == ''
    d.reject()


def test_tick_settings_roundtrip_and_validation(window, tmp_path):
    window.plot_style['y_axis'].update(tick_direction='in', tick_length=5, minor_ticks='off',
                                       number_format='fixed', decimals=1, tick_step=2.0, grid=False, invert=True)
    saved = dict(window.plot_style['y_axis'])
    window.path = tmp_path / 'ticks.json'
    window.save()
    window.plot_style['y_axis'].update(AXIS_STYLE)
    window.open_project(str(window.path))
    assert window.plot_style['y_axis'] == saved
    for bad in (dict(tick_direction='up'), dict(minor_ticks=True), dict(number_format='eng'),
                dict(decimals=2.5), dict(decimals=20), dict(tick_step=0), dict(tick_step=float('inf')),
                dict(tick_length=-1), dict(grid='yes'), dict(invert=1)):
        with pytest.raises(ValueError):
            validate_view({'plot_style': {'y_axis': bad}})
