"""Right-click menus for line-plot elements and the draggable legend.

Each element (title, axis labels, legend, legend entries, curves, the axes
background) opens a menu with the controls that apply to it. Edits go through
the same window state as the plot controls panel, so both stay in agreement.
"""
from PySide6 import QtGui as G, QtWidgets as W
from matplotlib.backend_bases import MouseButton
from matplotlib.legend import DraggableLegend as MatplotlibDraggableLegend
from .operations import dialog_parent
from .plotting import FONT_SIZES, LEGENDS, MARKERS, PLOT_STYLE


class DraggableLegend(MatplotlibDraggableLegend):
    """Left-drag the legend; the dropped position is stored on its panel."""

    def __init__(self, window, legend, panel_index):
        super().__init__(legend, use_blit=True, update='loc')
        legend._draggable = self  # the legend keeps its dragger alive and disconnects it on removal
        self.window, self.panel_index = window, panel_index

    def on_pick(self, evt):
        if evt.mouseevent.button == MouseButton.LEFT and not drag_blocked(self.window):
            super().on_pick(evt)

    def on_release(self, event):
        moved = self.got_artist and (event.x, event.y) != (self.mouse_x, self.mouse_y)
        super().on_release(event)
        if moved and self.panel_index < len(self.window.panels):
            self.window.panels[self.panel_index]['legend_anchor'] = [float(v) for v in self.legend._loc]
            self.window.changed()


def drag_blocked(window):
    """Zoom, pan, and drag-to-select tools own the left button while active."""
    return bool(window.navigation.mode or window.drag.isChecked()
                or (window.stats_drag.isChecked() and window.show_statistics.isChecked()))


def canvas_pressed(window, event):
    if event.button != MouseButton.RIGHT or window.navigation.mode:
        return  # zoom and pan use the right button themselves
    menu = context_menu(window, event)
    if menu is not None:
        menu.exec(G.QCursor.pos())


def legend_position_changed(window):
    if not window.loading:
        clear_anchors(window)
        window.changed()
        window.redraw()


def hit(window, event):
    """(kind, panel index, dataset id or None) for the plot element under a mouse event."""
    for index, (ax, resax) in enumerate(window.panel_axes):
        legend = ax.get_legend()
        if legend is not None and legend.contains(event)[0]:
            return 'legend', index, legend_entry(window, ax, legend, event)
        if ax.title.get_text() and ax.title.contains(event)[0]:
            return 'title', index, None
        if any(axes.get_visible() and axes.xaxis.label.get_text() and axes.xaxis.label.contains(event)[0]
               for axes in (ax, resax)):
            return 'xlabel', index, None
        if ax.yaxis.label.contains(event)[0]:
            return 'ylabel', index, None
        if event.inaxes is ax:
            curve = next((dataset_id for artist, dataset_id in window.curve_artists.get(ax, {}).items()
                          if artist.contains(event)[0]), None)
            return ('curve' if curve else 'axes'), index, curve
        if event.inaxes is resax and resax.get_visible():
            return 'axes', index, None
    return None


def legend_entry(window, ax, legend, event):
    artists = window.curve_artists.get(ax, {})
    handles = ax.get_legend_handles_labels()[0]
    for text, handle, artist in zip(legend.texts, legend.legend_handles, handles):
        if text.contains(event)[0] or (handle is not None and handle.contains(event)[0]):
            return artists.get(artist)
    return None


def context_menu(window, event):
    target = hit(window, event)
    if target is None:
        return None
    kind, index, dataset_id = target
    menu = W.QMenu(window.canvas)
    if kind == 'title':
        _title_actions(window, menu)
    elif kind in ('xlabel', 'ylabel'):
        _label_actions(window, menu, kind, index)
    elif kind == 'legend':
        if dataset_id:
            _legend_label_actions(window, menu, _dataset(window, dataset_id))
            menu.addSeparator()
        _legend_actions(window, menu, index)
    elif kind == 'curve':
        _curve_actions(window, menu, _dataset(window, dataset_id), index)
    else:
        _add(window, menu, 'Edit plot title…', lambda: edit_title(window))
        _add(window, menu, 'Edit X label…', lambda: edit_label(window, 'xlabel', index))
        _add(window, menu, 'Edit Y label…', lambda: edit_label(window, 'ylabel', index))
        menu.addSeparator()
        _size_menu(window, menu, 'Title size', 'title_size')
        _size_menu(window, menu, 'Axis label size', 'label_size')
        _size_menu(window, menu, 'Tick label size', 'tick_size')
        menu.addSeparator()
        if window.legend_position.currentText() == 'hidden':
            _add(window, menu, 'Show legend', lambda: choose_legend_position(window, 'best'))
        else:
            _legend_actions(window, menu.addMenu('Legend'), index)
    return menu


def _dataset(window, dataset_id):
    return next(d for d in window.datasets if d.id == dataset_id)


def _add(window, menu, text, function, *, checked=None, enabled=True):
    action = menu.addAction(text)
    action.setEnabled(enabled)
    if checked is not None:
        action.setCheckable(True)
        action.setChecked(checked)
    action.triggered.connect(lambda *_: window.guard(function))
    return action


def _title_actions(window, menu):
    _add(window, menu, 'Edit plot title…', lambda: edit_title(window))
    _add(window, menu, 'Clear title', lambda: set_title(window, ''), enabled=bool(window.title.text()))
    _size_menu(window, menu, 'Title size', 'title_size')


def _label_actions(window, menu, kind, index):
    axis = kind[0].upper()
    _add(window, menu, f'Edit {axis} label…', lambda: edit_label(window, kind, index))
    _add(window, menu, f'Use automatic {axis} label', lambda: set_label(window, kind, index, ''),
         enabled=bool(label_text(window, kind, index).strip()))
    _size_menu(window, menu, 'Axis label size', 'label_size')
    _size_menu(window, menu, 'Tick label size', 'tick_size')


def _legend_label_actions(window, menu, d):
    _add(window, menu, f'Legend label for {d.name}…', lambda: edit_legend_label(window, d))
    _add(window, menu, 'Reset legend label', lambda: set_legend_label(window, d, ''),
         enabled=d.id in window.legend_labels)


def _legend_actions(window, menu, index):
    anchor = window.panels[index].get('legend_anchor')
    current = window.legend_position.currentText()
    positions = menu.addMenu('Position')
    group = G.QActionGroup(positions)
    for loc in LEGENDS[:-1]:
        group.addAction(_add(window, positions, loc, lambda loc=loc: choose_legend_position(window, loc),
                             checked=anchor is None and loc == current))
    _add(window, menu, 'Reset dragged position', lambda: reset_anchor(window, index), enabled=anchor is not None)
    _size_menu(window, menu, 'Font size', 'legend_size')
    columns = menu.addMenu('Columns')
    group = G.QActionGroup(columns)
    for count in range(1, 5):
        group.addAction(_add(window, columns, str(count), lambda count=count: set_style(window, 'legend_columns', count),
                             checked=window.plot_style['legend_columns'] == count))
    _add(window, menu, 'Frame', lambda: set_style(window, 'legend_frame', not window.plot_style['legend_frame']),
         checked=window.plot_style['legend_frame'])
    menu.addSeparator()
    _add(window, menu, 'Hide legend', lambda: choose_legend_position(window, 'hidden'))


def _curve_actions(window, menu, d, index):
    header = menu.addAction(d.name)
    header.setEnabled(False)
    menu.addSeparator()
    _legend_label_actions(window, menu, d)
    menu.addSeparator()
    _add(window, menu, 'Color…', lambda: choose_curve_color(window, d))
    _add(window, menu, 'Automatic color', lambda: set_curve(window, d, 'color', ''), enabled=bool(d.color))
    markers = menu.addMenu('Marker')
    group = G.QActionGroup(markers)
    for label, value in MARKERS.items():
        group.addAction(_add(window, markers, label, lambda value=value: set_curve(window, d, 'marker', value),
                             checked=d.marker == value))
    menu.addSeparator()
    _add(window, menu, 'Remove from plot', lambda: remove_curve(window, d, index))


def _size_menu(window, menu, title, key):
    sizes = menu.addMenu(title)
    group = G.QActionGroup(sizes)
    for size in ((None,) if PLOT_STYLE[key] is None else ()) + FONT_SIZES:
        group.addAction(_add(window, sizes, 'Default' if size is None else f'{size} pt',
                             lambda size=size: set_style(window, key, size),
                             checked=window.plot_style[key] == size))
    return sizes


def _ask(window, title, prompt, text):
    value, ok = W.QInputDialog.getText(dialog_parent(window), title, prompt, text=text)
    return value if ok else None


def edit_title(window):
    text = _ask(window, 'Plot title', 'Title:', window.title.text())
    if text is not None:
        set_title(window, text)


def set_title(window, text):
    window.title.setText(text)
    window.labels_changed()


def label_text(window, kind, index):
    if kind == 'xlabel':
        return window.xlabel.text()
    return window.ylabel.text() if index == window.active_panel else window.panels[index].get('ylabel', '')


def edit_label(window, kind, index):
    axis = kind[0].upper()
    text = _ask(window, f'{axis} label', f'{axis} label (leave empty for the automatic label):',
                label_text(window, kind, index))
    if text is not None:
        set_label(window, kind, index, text)


def set_label(window, kind, index, text):
    if kind == 'xlabel' or index == window.active_panel:
        getattr(window, kind).setText(text)
        window.labels_changed()
    else:
        window.panels[index]['ylabel'] = text
        window.changed()
        window.redraw()


def edit_legend_label(window, d):
    text = _ask(window, 'Legend label', f'Legend label for {d.name} (leave empty for the dataset name):',
                window.legend_labels.get(d.id, d.name))
    if text is not None:
        set_legend_label(window, d, text)


def set_legend_label(window, d, text):
    text = text.strip()
    if text and text != d.name:
        window.legend_labels[d.id] = text
    else:
        window.legend_labels.pop(d.id, None)
    window.changed()
    window.redraw()


def set_style(window, key, value):
    if window.plot_style[key] != value:
        window.plot_style[key] = value
        window.changed()
        window.redraw()


def clear_anchors(window):
    for panel in window.panels:
        panel.pop('legend_anchor', None)


def reset_anchor(window, index):
    window.panels[index].pop('legend_anchor', None)
    window.changed()
    window.redraw()


def choose_legend_position(window, loc):
    if window.legend_position.currentText() != loc:
        window.legend_position.setCurrentText(loc)  # legend_position_changed clears anchors and redraws
    else:
        legend_position_changed(window)


def choose_curve_color(window, d):
    color = W.QColorDialog.getColor(G.QColor(d.color) if d.color else G.QColor('white'),
                                    dialog_parent(window), 'Dataset color')
    if color.isValid():
        set_curve(window, d, 'color', color.name())


def set_curve(window, d, attribute, value):
    if d is window.current():
        if attribute == 'color':
            window.set_color(value)
        else:
            window.marker.setCurrentIndex(window.marker.findData(value))  # appearance_changed redraws
        return
    if getattr(d, attribute) != value:
        setattr(d, attribute, value)
        window.changed()
        window.redraw()


def remove_curve(window, d, index):
    if index != window.active_panel:
        window.activate_panel(index)
    window.remove_curve(d.id)
