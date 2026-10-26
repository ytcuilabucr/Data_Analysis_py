import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('MPLCONFIGDIR', '/tmp/rogi-matplotlib-tests')

import numpy as np
import pytest
from PySide6 import QtWidgets as W
from matplotlib.backend_bases import MouseButton, MouseEvent, PickEvent
from rogi import plot_context
from rogi.core import parse_text
from rogi.plotting import validate_view
from rogi.ui import MainWindow


@pytest.fixture
def window():
    window = MainWindow()
    a = parse_text('x,y\n1,2\n2,4\n3,6')
    b = parse_text('x,y\n1,3\n2,5\n3,9')
    a.name, b.name = 'Run A', 'Run B'
    window.add_dataset(a)
    window.add_dataset(b)
    for d in window.datasets:
        d.visible = True
    window.title.setText('Title')
    window.labels_changed()
    window.canvas.draw()
    yield window
    window.dirty = False
    window.close()


def event_at(window, artist, button=MouseButton.RIGHT, name='button_press_event'):
    box = artist.get_window_extent(window.canvas.get_renderer())
    return MouseEvent(name, window.canvas, (box.x0 + box.x1) / 2, (box.y0 + box.y1) / 2, button=button)


def actions(menu):
    found = {}
    for action in menu.actions():
        if action.menu():
            found.update({f'{action.text()}/{k}': v for k, v in actions(action.menu()).items()})
        elif action.text():
            found[action.text()] = action
    return found


def menu_for(window, artist):
    window.canvas.draw()
    return actions(plot_context.context_menu(window, event_at(window, artist)))


def test_hit_testing_finds_each_element(window):
    ax = window.ax
    legend = ax.get_legend()
    assert plot_context.hit(window, event_at(window, ax.title))[0] == 'title'
    assert plot_context.hit(window, event_at(window, ax.xaxis.label))[0] == 'xlabel'
    assert plot_context.hit(window, event_at(window, ax.yaxis.label))[0] == 'ylabel'
    entry = plot_context.hit(window, event_at(window, legend.texts[1]))
    assert entry == ('legend', 0, window.datasets[1].id)
    line = ax.lines[0]
    x, y = ax.transData.transform((line.get_xdata()[1], line.get_ydata()[1]))
    event = MouseEvent('button_press_event', window.canvas, x, y, button=MouseButton.RIGHT)
    assert plot_context.hit(window, event) == ('curve', 0, window.datasets[0].id)


def test_title_menu_edits_the_plot(window, monkeypatch):
    monkeypatch.setattr(W.QInputDialog, 'getText', lambda *a, **k: ('New title', True))
    menu_for(window, window.ax.title)['Edit plot title…'].trigger()
    assert window.title.text() == 'New title'
    assert window.ax.get_title() == 'New title'
    menu_for(window, window.ax.title)['Title size/18 pt'].trigger()
    assert window.ax.title.get_fontsize() == 18


def test_legend_menu_controls_and_entry_label(window, monkeypatch):
    monkeypatch.setattr(W.QInputDialog, 'getText', lambda *a, **k: ('Sample B', True))
    menu = menu_for(window, window.ax.get_legend().texts[1])
    menu['Legend label for Run B…'].trigger()
    assert window.ax.get_legend_handles_labels()[1] == ['Run A', 'Sample B']
    assert window.datasets[1].name == 'Run B'
    legend = window.ax.get_legend()
    menu_for(window, legend)['Columns/2'].trigger()
    menu_for(window, window.ax.get_legend())['Font size/12 pt'].trigger()
    menu_for(window, window.ax.get_legend())['Frame'].trigger()
    legend = window.ax.get_legend()
    assert legend._ncols == 2 and legend.texts[0].get_fontsize() == 12 and not legend.get_frame_on()
    menu_for(window, legend)['Position/lower left'].trigger()
    assert window.legend_position.currentText() == 'lower left'
    menu_for(window, window.ax.get_legend())['Hide legend'].trigger()
    assert window.ax.get_legend() is None
    x, y = window.ax.transAxes.transform((.98, .02))
    background = MouseEvent('button_press_event', window.canvas, x, y, button=MouseButton.RIGHT)
    actions(plot_context.context_menu(window, background))['Show legend'].trigger()
    assert window.ax.get_legend() is not None


def test_curve_menu_sets_appearance_of_that_curve(window):
    other = window.datasets[0] if window.current() is not window.datasets[0] else window.datasets[1]
    line = next(artist for artist, i in window.curve_artists[window.ax].items() if i == other.id)
    x, y = window.ax.transData.transform((line.get_xdata()[1], line.get_ydata()[1]))
    window.canvas.draw()
    menu = actions(plot_context.context_menu(window, MouseEvent(
        'button_press_event', window.canvas, x, y, button=MouseButton.RIGHT)))
    menu['Marker/Square'].trigger()
    assert other.marker == 's'
    redrawn = next(artist for artist, i in window.curve_artists[window.ax].items() if i == other.id)
    assert redrawn.get_marker() == 's'


def test_legend_drag_is_stored_and_reset_by_position_choice(window, tmp_path):
    legend = window.ax.get_legend()
    dragger = legend._draggable
    press = event_at(window, legend, MouseButton.LEFT)
    dragger.on_pick(PickEvent('pick_event', window.canvas, press, legend))
    dragger.on_motion(MouseEvent('motion_notify_event', window.canvas, press.x - 120, press.y - 80))
    dragger.on_release(MouseEvent('button_release_event', window.canvas, press.x - 120, press.y - 80,
                                  button=MouseButton.LEFT))
    anchor = window.panels[0]['legend_anchor']
    assert window.dirty and len(anchor) == 2
    window.redraw()
    np.testing.assert_allclose(window.ax.get_legend()._loc, anchor)
    window.path = tmp_path / 'plot.json'
    window.save()
    window.open_project(str(window.path))
    np.testing.assert_allclose(window.panels[0]['legend_anchor'], anchor)
    window.legend_position.setCurrentText('upper left')
    assert 'legend_anchor' not in window.panels[0]
    assert window.ax.get_legend()._loc == 2  # 'upper left'


def test_right_button_and_active_tools_do_not_drag_the_legend(window):
    legend = window.ax.get_legend()
    dragger = legend._draggable
    dragger.on_pick(PickEvent('pick_event', window.canvas, event_at(window, legend), legend))
    assert not dragger.got_artist
    window.drag.setChecked(True)
    legend = window.ax.get_legend()
    legend._draggable.on_pick(PickEvent('pick_event', window.canvas,
                                        event_at(window, legend, MouseButton.LEFT), legend))
    assert not legend._draggable.got_artist


def test_style_settings_roundtrip_and_validation(window, tmp_path):
    window.plot_style.update(title_size=16, legend_columns=3)
    window.legend_labels[window.datasets[0].id] = 'Custom'
    window.path = tmp_path / 'plot.h5'
    window.save()
    window.plot_style.update(title_size=None)
    window.legend_labels.clear()
    window.open_project(str(window.path))
    assert window.plot_style['title_size'] == 16 and window.plot_style['legend_columns'] == 3
    assert window.ax.get_legend_handles_labels()[1][0] == 'Custom'
    for bad in ({'plot_style': {'title_size': 1}}, {'plot_style': {'legend_columns': 0}},
                {'plot_style': {'bogus': 1}}, {'legend_labels': {'a': 1}}):
        with pytest.raises(ValueError):
            validate_view(bad)
