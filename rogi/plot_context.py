"""Right-click menus for line-plot elements and the draggable legend.

Each element (title, axis labels, legend, legend entries, curves, the axes
background) opens a menu with the controls that apply to it. An axis label or
its tick labels opens the Format Axis dialog instead, on a right-click or a
double-click, and a right-click on the legend opens the Format Legend dialog. Edits go through
the same window state as the plot controls panel, so both stay in agreement.
"""
from PySide6 import QtGui as G, QtWidgets as W
from matplotlib.backend_bases import MouseButton
from matplotlib.legend import DraggableLegend as MatplotlibDraggableLegend
from .operations import dialog_parent
from .plotting import FONT_SIZES, MARKERS, PLOT_STYLE


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
    if window.navigation.mode:
        return  # zoom and pan use the right button themselves
    right = event.button == MouseButton.RIGHT
    if not right and not (event.button == MouseButton.LEFT and event.dblclick):
        return
    target = hit(window, event)
    if target is not None and target[0] in ('xlabel', 'ylabel'):
        window.guard(lambda: format_axis(window, target[0][0], target[1]))
    elif target is not None and target[0] == 'legend':
        if right:  # the left button drags the legend
            window.guard(lambda: format_legend(window, target[1], target[2]))
    elif right:
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
        if any(axes.get_visible() and on_tick_labels(window, axes, axes.xaxis, event) for axes in (ax, resax)):
            return 'xlabel', index, None
        if on_tick_labels(window, ax, ax.yaxis, event):
            return 'ylabel', index, None
        if event.inaxes is ax:
            curve = next((dataset_id for artist, dataset_id in window.curve_artists.get(ax, {}).items()
                          if artist.contains(event)[0]), None)
            return ('curve' if curve else 'axes'), index, curve
        if event.inaxes is resax and resax.get_visible():
            return 'axes', index, None
    return None


def on_tick_labels(window, axes, axis, event):
    """Whether the event is beside the axes, where this axis draws its ticks and tick labels."""
    box = axis.get_tightbbox(window.canvas.get_renderer())
    return box is not None and box.contains(event.x, event.y) and not axes.bbox.contains(event.x, event.y)


def legend_entry(window, ax, legend, event):
    for text, handle, dataset_id in zip(legend.texts, legend.legend_handles, window.legend_ids.get(ax, [])):
        if text.contains(event)[0] or (handle is not None and handle.contains(event)[0]):
            return dataset_id
    return None


def context_menu(window, event):
    target = hit(window, event)
    if target is None or target[0] in ('xlabel', 'ylabel', 'legend'):
        return None  # these open the Format Axis and Format Legend dialogs
    kind, index, dataset_id = target
    menu = W.QMenu(window.canvas)
    if kind == 'title':
        _title_actions(window, menu)
    elif kind == 'curve':
        _curve_actions(window, menu, _dataset(window, dataset_id), index)
    else:
        _add(window, menu, 'Format X axis…', lambda: format_axis(window, 'x', index))
        _add(window, menu, 'Format Y axis…', lambda: format_axis(window, 'y', index))
        _add(window, menu, 'Format legend…', lambda: format_legend(window, index))
        _add(window, menu, 'Edit plot title…', lambda: edit_title(window))
        _size_menu(window, menu, 'Title size', 'title_size')
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


def _legend_label_actions(window, menu, d):
    _add(window, menu, f'Legend label for {d.name}…', lambda: edit_legend_label(window, d))
    _add(window, menu, 'Reset legend label', lambda: set_legend_label(window, d, ''),
         enabled=d.id in window.legend_labels)


def _curve_actions(window, menu, d, index):
    header = menu.addAction(d.name)
    header.setEnabled(False)
    menu.addSeparator()
    _legend_label_actions(window, menu, d)
    _add(window, menu, 'Format legend…', lambda: format_legend(window, index, d.id))
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


def format_axis(window, axis, index):
    from .axis_format import format_axis  # the dialog builds on the plot workflows, which import this module
    format_axis(window, axis, index)


def format_legend(window, index, dataset_id=None):
    from .legend_format import format_legend
    format_legend(window, index, dataset_id)


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
