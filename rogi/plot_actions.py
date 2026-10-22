"""Plot workflows coordinated by MainWindow.

Functions receive the window explicitly to preserve ordering across history,
selection and presentation. They are not panel components; extracted panels
communicate with the window through their signals and data arguments.
"""
from copy import copy, deepcopy
import numpy as np
from PySide6 import QtCore as C, QtWidgets as W
from matplotlib.transforms import Bbox
from matplotlib.widgets import SpanSelector, Cursor, RectangleSelector
from .core import region_statistics
from .operations import dialog_parent
from .plotting import display_values
from .history import ChangeCommand
from . import plot_windows

# Above this many plotted points, legend placement "best" falls back to a fixed corner.
BEST_LEGEND_POINTS = 100_000


def panel_datasets(self, panel):
    if panel['channels'] is None:
        return self.datasets
    result = []
    for d in self.datasets:
        pair = panel['channels'].get(d.id)
        if pair and max(pair) < len(d.columns):
            plotted = copy(d)
            plotted.xcol, plotted.ycol = pair
            result.append(plotted)
    return result


def freeze_default_panel(self):
    for panel in self.panels:
        if panel['channels'] is None:
            panel['channels'] = {d.id: [d.xcol, d.ycol] for d in self.datasets}


def refresh_panels(self):
    with C.QSignalBlocker(self.panel_choice):
        self.panel_choice.clear()
        self.panel_choice.addItems([f'Panel {i + 1}' for i in range(len(self.panels))])
        self.panel_choice.setCurrentIndex(self.active_panel)
    self.view = self.panels[self.active_panel]['view']
    with C.QSignalBlocker(self.ylabel):
        self.ylabel.setText(self.panels[self.active_panel].get('ylabel', ''))


def add_panel(self):
    d = self.current()
    self.freeze_default_panel()
    channels = {d.id: [d.xcol, d.ycol]} if d else {}
    self.panels.append(dict(channels=channels, view={
        axis: dict(scale='linear', auto=True, limits=None) for axis in ('x', 'y', 'resy')}))
    self.activate_panel(len(self.panels) - 1)


def assign_panel_channel(self):
    d = self.current()
    if d:
        self.freeze_default_panel()
        self.panels[self.active_panel]['channels'][d.id] = [d.xcol, d.ycol]
        self.changed()
        self.redraw()


def unassign_panel_channel(self):
    d = self.current()
    if d:
        self.freeze_default_panel()
        self.panels[self.active_panel]['channels'].pop(d.id, None)
        self.changed()
        self.redraw()


def remove_panel(self):
    if len(self.panels) > 1:
        self.panels.pop(self.active_panel)
        self.activate_panel(min(self.active_panel, len(self.panels) - 1))


def activate_panel(self, index):
    if index < 0 or self.loading:
        return
    self.active_panel = index
    self.refresh_panels()
    channels = self.panels[index]['channels']
    d = self.current()
    if channels:
        if d is None or d.id not in channels:
            d = next((d for d in self.datasets if d.id in channels), None)
        if d and max(channels[d.id]) < len(d.columns):
            d.xcol, d.ycol = channels[d.id]
            self.activate_dataset(d.id)
            self.select(self.browser.currentRow())
    self.sync_axis_controls()
    self.navigation.update()
    self.changed()
    self.redraw()


def curve_label(d):
    return f"{d.name} — {d.columns[d.ycol]}" if d.ycol < len(d.columns) else d.name


def refresh_curves(self):
    plotted = [d for d in self.panel_datasets(self.panels[self.active_panel]) if d.visible]
    shown = {d.id for d in plotted}
    candidates = [d for d in self.datasets if d.id not in shown and len(d.columns) > 1]
    # Only the datasets to add follow the browser filter; plotted curves stay removable.
    hidden = self.browser_panel.hidden_ids() if self.plot_controls.match_browser_filter.isChecked() else set()
    self.plot_controls.set_curves(
        [(d.id, curve_label(d)) for d in plotted],
        [(d.id, curve_label(d)) for d in candidates if d.id not in hidden],
        filtered=sum(d.id in hidden for d in candidates))


def add_curve(self, dataset_id):
    """Show another dataset in the active panel, as checking it in the browser would; undoable."""
    d = next(d for d in self.datasets if d.id == dataset_id)
    channels = self.panels[self.active_panel]['channels']
    visible, pair = d.visible, channels.get(d.id) if channels is not None else None
    # Visibility is shared by all panels: a hidden dataset listed in other panels
    # would appear there too, so it leaves them while it joins this one.
    others = [] if channels is None or visible else [
        (panel['channels'], panel['channels'][d.id]) for panel in self.panels
        if panel['channels'] is not None and panel['channels'] is not channels and d.id in panel['channels']]
    def apply():
        d.visible = True
        if channels is not None:
            channels[d.id] = [d.xcol, d.ycol]
        for other, _ in others:
            other.pop(d.id, None)
    def revert():
        d.visible = visible
        if channels is not None:
            if pair is None:
                channels.pop(d.id, None)
            else:
                channels[d.id] = pair
        for other, other_pair in others:
            other[d.id] = other_pair
    self.history.push(ChangeCommand(self, f"Add curve {d.name}", apply, revert))
    # Its channels then appear in the axis controls, ready to change.
    self.activate_dataset(d.id)


def remove_curve(self, dataset_id):
    """Hide the curve; in a panel with its own channel list, only drop it from that panel."""
    d = next(d for d in self.datasets if d.id == dataset_id)
    channels = self.panels[self.active_panel]['channels']
    if channels is None:
        self.change_attributes([d], 'visible', False, f"Remove curve {d.name}")
        return
    pair = channels[d.id]
    self.history.push(ChangeCommand(self, f"Remove curve {d.name} from panel {self.active_panel + 1}",
                                    lambda: channels.pop(d.id, None),
                                    lambda: channels.__setitem__(d.id, pair)))


def set_sync_x(self, enabled):
    self.sync_x = enabled
    self.changed()
    self.redraw()


def restore_panels(self, settings):
    self.panels = deepcopy(settings.get('panels', [dict(channels=None, view=self.view, ylabel=settings.get('ylabel', ''))]))
    self.active_panel = settings.get('active_panel', 0)
    self.sync_x = settings.get('sync_x', False)
    with C.QSignalBlocker(self.sync_x_control):
        self.sync_x_control.setChecked(self.sync_x)
    self.refresh_panels()
    d = self.current()
    channels = self.panels[self.active_panel]['channels']
    if d and channels and d.id in channels and max(channels[d.id]) < len(d.columns):
        d.xcol, d.ycol = channels[d.id]
    if d:
        self.select(self.browser.currentRow())


def plot_options(self):
    if self.loading or not self.current():
        return
    d = self.current()
    x_changed = d.xcol != self.x.currentIndex()
    channels_changed = x_changed or d.ycol != self.y.currentIndex()
    d.xcol, d.ycol, d.style = self.x.currentIndex(), self.y.currentIndex(), self.style.currentText()
    if self.panels[self.active_panel]['channels'] is not None:
        self.panels[self.active_panel]['channels'][d.id] = [d.xcol, d.ycol]
    if channels_changed and not d.visible:
        previous = [(dataset, dataset.visible) for dataset in self.datasets]
        def show_only():
            for dataset, visible in previous:
                dataset.visible = dataset is d
        def restore_visibility():
            for dataset, visible in previous:
                dataset.visible = visible
        self.history.push(ChangeCommand(self, f"Show only {d.name} after channel change",
                                        show_only, restore_visibility))
        self.plot_status.showMessage(f'Showing only {d.name}. Check other datasets to compare.', 5000)
    if x_changed:
        self.reset_fit_range(d)
    self.changed()
    self.show_result()
    self.redraw()


def labels_changed(self):
    self.panels[self.active_panel]['ylabel'] = self.ylabel.text()
    self.changed()
    self.redraw()


def toggle_fitting(self, visible):
    if visible:
        plot_windows.ensure_plot(self, plot_windows.LINE)
    self.fit_panel.setVisible(visible)
    self.export_fit_action.setVisible(visible)
    if not visible:
        self.drag.setChecked(False)
    self.changed()
    self.redraw()


def toggle_span(self, active):
    if active:
        self.stats_drag.setChecked(False)
        self.disable_navigation()
    if hasattr(self, 'span'):
        self.span.set_active(active)


def disable_navigation(self):
    if self.navigation.mode == 'pan/zoom':
        self.navigation.pan()
    elif self.navigation.mode == 'zoom rect':
        self.navigation.zoom()


def toggle_statistics(self, visible):
    if visible:
        plot_windows.ensure_plot(self, plot_windows.LINE)
    self.stats_panel.setVisible(visible)
    if not visible:
        self.stats_drag.setChecked(False)
    self.refresh_statistics()
    self.redraw()


def statistics_mode_changed(self, *args):
    for field in self.stats_bounds[2:]:
        field.setEnabled(self.stats_mode.currentIndex() == 1)
    self.stats_region = None
    self.stats_result.setPlainText("Select a region or enter bounds, then calculate.")
    self.redraw()


def toggle_statistics_drag(self, active):
    if active:
        self.drag.setChecked(False)
        self.disable_navigation()
        d = self.current()
        if d and not d.visible:
            self.plot_status.showMessage("Check the active dataset to see its curve while selecting.", 5000)
    self.redraw()


def statistics_selected(self, lower, upper, ylower=None, yupper=None):
    bounds = (lower, upper, ylower, yupper)
    for field, value in zip(self.stats_bounds, bounds):
        if value is not None:
            field.setText(f"{value:.17g}")
    self.guard(self.calculate_statistics)


def statistics_rectangle_selected(self, press, release):
    if None not in (press.xdata, press.ydata, release.xdata, release.ydata):
        self.statistics_selected(*sorted((press.xdata, release.xdata)),
                                 *sorted((press.ydata, release.ydata)))


def calculate_statistics(self):
    d = self.current()
    if d is None:
        raise ValueError("Select an active dataset first.")
    bounds = [float(field.text()) for field in self.stats_bounds[:2]]
    bounds += ([float(field.text()) for field in self.stats_bounds[2:]]
               if self.stats_mode.currentIndex() else [None, None])
    # Validate before replacing a previous valid selection.
    region_statistics(d, *bounds, sample=self.stats_sample.currentIndex() == 0)
    self.stats_context = (d.id, d.xcol, d.ycol)
    self.stats_region = tuple(bounds)
    self.refresh_statistics()
    self.redraw()


def refresh_statistics(self, *args):
    d = self.current()
    context = (d.id, d.xcol, d.ycol) if d else None
    if context != self.stats_context:
        self.stats_context = context
        self.stats_region = None
        for field in self.stats_bounds:
            field.clear()
    if not d or self.stats_region is None:
        self.stats_result.setPlainText("Select a dataset and drag a region, or enter bounds and calculate.")
        return
    result = region_statistics(d, *self.stats_region, sample=self.stats_sample.currentIndex() == 0)
    lo, hi, ylo, yhi = self.stats_region
    lines = [d.name, f"Y: {d.columns[d.ycol]} · X: {d.columns[d.xcol]}",
             f"X range: [{lo:.8g}, {hi:.8g}] (inclusive)"]
    if ylo is not None:
        lines.append(f"Y range: [{ylo:.8g}, {yhi:.8g}] (inclusive)")
    lines += [f"Count: {result['count']}",
              f"Missing X (whole dataset): {result['missing_x']}",
              f"Missing Y within X range: {result['missing_y']}",
              "Std / variance: " + ("sample (N − 1)" if result['sample'] else "population (N)")]
    for key, label in (('minimum', 'Minimum'), ('maximum', 'Maximum'), ('mean', 'Mean'),
                       ('median', 'Median'), ('std', 'Standard deviation'), ('variance', 'Variance'),
                       ('sem', 'Standard error of mean'), ('sum', 'Sum'), ('rms', 'RMS'),
                       ('q1', '25th percentile'), ('q3', '75th percentile')):
        value = result[key]
        lines.append(f"{label}: " + (f"{value:.10g}" if value is not None else "N/A"))
    lines += ["N/A: insufficient observations or result outside numeric range.",
              "Stored values, not fitted/interpolated points. Log-hidden values are included if within bounds."]
    self.stats_result.setPlainText("\n".join(lines))


def apply_axes(self):
    proposed = self.plot_controls.read_axes()
    self.view.update(proposed)
    # Applying automatic axes also resets any residual-panel zoom.
    self.view['resy'] = dict(scale='linear', auto=True, limits=None)
    self.changed()
    self.redraw()
    self.navigation.update()


def choose_color(self):
    if self.current():
        color = W.QColorDialog.getColor(parent=dialog_parent(self), title="Dataset color")
        if color.isValid():
            self.set_color(color.name())


def set_color(self, color):
    if self.current() and self.current().color != color:
        self.current().color = color
        self.color.setText(color or "Automatic color")
        self.changed()
        self.redraw()


def appearance_changed(self):
    if not self.loading and self.current():
        self.current().marker = self.marker.currentData()
        self.changed()
        self.redraw()


def presentation_changed(self, *args):
    if not self.loading:
        self.changed()
        self.redraw()


def cursor_motion(self, event):
    if (self.cursor_enabled.isChecked() and event.inaxes in [a for pair in self.panel_axes for a in pair]
            and event.xdata is not None and event.ydata is not None):
        for line in getattr(self, 'shared_cursor_lines', []):
            line.set_xdata([event.xdata, event.xdata])
            line.set_visible(True)
        self.canvas.draw_idle()
        label = "Residual" if event.inaxes is self.resax else "Y"
        self.coordinates.setText(f"X: {event.xdata:.7g}   {label}: {event.ydata:.7g}")
    else:
        self.coordinates.clear()
        for line in getattr(self, 'shared_cursor_lines', []):
            line.set_visible(False)
        self.canvas.draw_idle()


def limits_changed(self, axis, axes):
    if self.drawing:
        return
    limits = list(axes.get_xlim() if axis == 'x' else axes.get_ylim())
    panel_index = next((i for i, pair in enumerate(self.panel_axes) if axes in pair), self.active_panel)
    state = self.panels[panel_index]['view'][axis]
    if axis == 'x' and self.sync_x:
        self.drawing = True
        try:
            for panel, pair in zip(self.panels, self.panel_axes):
                panel['view']['x'].update(auto=False, limits=limits)
                for target in pair:
                    if target is not axes:
                        target.set_xlim(limits)
        finally:
            self.drawing = False
        self.sync_axis_controls()
        self.changed()
    if state['limits'] != limits:
        state.update(auto=False, limits=limits)
        self.sync_axis_controls()
        self.changed()


def plot_tab_changed(self, index):
    plot_windows.update_titles(self)
    self.image_viewer.set_context(self.datasets, self.current())


def redraw(self):
    if getattr(self, 'redraw_deferred', False):
        return  # open_project redraws once after restoring the whole view.
    if plot_windows.plot_hidden(self):
        self.plot_stale = True  # drawn once the plot window opens
        return
    self.plot_stale = False
    self.image_viewer.set_context(self.datasets, self.current())
    self.drawing = True
    try:
        self.draw_plot()
    finally:
        self.drawing = False
    refresh_curves(self)
    plot_windows.update_titles(self)


def draw_plot(self):
    for axes, callback in self.limit_callbacks:
        axes.callbacks.disconnect(callback)
    self.limit_callbacks.clear()
    if hasattr(self, 'span'):
        self.span.disconnect_events()
    if hasattr(self, 'stats_selector'):
        self.stats_selector.disconnect_events()
    for cursor in getattr(self, 'cursors', []):
        cursor.disconnect_events()
    self.cursors = []
    if len(self.panel_axes) != len(self.panels):
        self.figure.clear()
        self.panel_grid = self.figure.add_gridspec(len(self.panels), 1)
        self.panel_axes = []
        self.panel_fit_specs = []
        for i in range(len(self.panels)):
            sub = self.panel_grid[i].subgridspec(2, 1, height_ratios=[3, 1])
            ax = self.figure.add_subplot(sub[0])
            resax = self.figure.add_subplot(sub[1], sharex=ax)
            self.panel_axes.append((ax, resax))
            self.panel_fit_specs.append(sub[0])
        self.navigation.update()
    self.panel_log_notices = []
    active_view = self.panels[self.active_panel]['view']
    if self.sync_x:
        for panel in self.panels:
            panel['view']['x'] = deepcopy(active_view['x'])
    for i in [j for j in range(len(self.panels)) if j != self.active_panel] + [self.active_panel]:
        self.ax, self.resax = self.panel_axes[i]
        self.view = self.panels[i]['view']
        self.fit_plot_spec = self.panel_fit_specs[i]
        self.full_plot_spec = self.panel_grid[i]
        self.draw_panel(i)
    if self.sync_x:
        limits = self.ax.get_xlim()
        for panel, pair in zip(self.panels, self.panel_axes):
            panel['view']['x']['limits'] = list(limits)
            pair[0].set_xlim(limits)
    self.log_notice.setText(("Log axes require positive values. Not drawn: "
                             + "; ".join(self.panel_log_notices)
                             + ". Stored data and fits are unchanged.") if self.panel_log_notices else "")
    self.log_notice.setVisible(bool(self.panel_log_notices))
    self.shared_cursor_lines = [ax.axvline(0, visible=False, color='gray', linewidth=.7)
                                for pair in self.panel_axes for ax in pair if ax.get_visible()]
    self.sync_axis_controls()
    self.canvas.draw_idle()


def draw_panel(self, panel_index):
    active = panel_index == self.active_panel
    plotted_datasets = self.panel_datasets(self.panels[panel_index])
    self.coordinates.clear()
    self.ax.clear()
    self.resax.clear()
    # Empty axes otherwise retain limits contributed by old cursor artists.
    self.ax.dataLim = Bbox.null()
    self.resax.dataLim = Bbox.null()
    fitting = self.show_fitting.isChecked() and active
    self.resax.set_visible(fitting)
    self.ax.set_subplotspec(self.fit_plot_spec if fitting else self.full_plot_spec)
    self.ax.tick_params(labelbottom=not fitting)
    _draw_datasets(self, panel_index, plotted_datasets, fitting)
    _draw_labels(self, panel_index, plotted_datasets, active, fitting)
    _apply_plot_axes(self)
    _build_interaction(self, active)


def _draw_datasets(self, panel_index, plotted_datasets, fitting):
    notices = []
    palette = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd',
               '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf']
    color_indices = {d.id: i for i, d in enumerate(self.datasets)}
    for d in plotted_datasets:
        if not d.visible:
            continue
        color = d.color or palette[color_indices[d.id] % len(palette)]
        x, y, excluded = display_values(d.values[:, d.xcol], d.values[:, d.ycol],
                                        self.view['x']['scale'], self.view['y']['scale'])
        if excluded:
            notices.append(f"{d.name}: {excluded} data row(s)")
        if d.style == 'Scatter':
            self.ax.scatter(x, y, s=14, label=d.name, color=color, marker=d.marker or 'o')
        else:
            self.ax.plot(x, y, label=d.name, color=color, marker=d.marker or 'None')
        if (d.analysis and d.analysis.get('version') == 2 and d.analysis.get('operation') == 'mean'
                and (d.xcol, d.ycol) == (0, 1)):
            sd = d.values[:, 2]
            lower, upper = y - sd, y + sd
            if self.view['y']['scale'] == 'log':
                lower = np.where(lower > 0, lower, np.nan)
                upper = np.where(upper > 0, upper, np.nan)
            self.ax.fill_between(x, lower, upper, color=color, alpha=.2, label=d.name + ' ±1 sample SD (not SEM)')
        if fitting and d.fit and (d.fit['xcol'], d.fit['ycol']) == (d.xcol, d.ycol):
            fit = d.fit
            order = np.argsort(fit['x'])
            fx, fy, count = display_values(np.array(fit['x'])[order], np.array(fit['predicted'])[order],
                                           self.view['x']['scale'], self.view['y']['scale'])
            if count:
                notices.append(f"{d.name}: {count} fit point(s)")
            self.ax.plot(fx, fy, '--', label=d.name + ' fit', color=color)
            rx, ry, _ = display_values(fit['x'], fit['residuals'], self.view['x']['scale'], 'linear')
            self.resax.scatter(rx, ry, s=10, label=d.name, color=color)
    self.panel_log_notices.extend(
        (f'Panel {panel_index + 1}: ' if len(self.panels) > 1 else '') + notice
        for notice in notices)


def _draw_labels(self, panel_index, plotted_datasets, active, fitting):
    panel_title = self.title.text()
    if len(self.panels) > 1:
        panel_title = f"Panel {panel_index + 1}" + (' (active)' if active else '') + (f' — {panel_title}' if panel_title else '')
    self.ax.set_title(panel_title)
    visible = [d for d in plotted_datasets if d.visible]
    x_label = ', '.join(dict.fromkeys(d.columns[d.xcol] for d in visible)) or 'X'
    y_label = ', '.join(dict.fromkeys(d.columns[d.ycol] for d in visible)) or 'Y'
    self.xlabel.setPlaceholderText(x_label)
    self.ylabel.setPlaceholderText(y_label)
    self.ax.set_ylabel(self.panels[panel_index].get('ylabel', self.ylabel.text() if len(self.panels) == 1 else '') or y_label)
    self.resax.set_xlabel(self.xlabel.text() or x_label)
    self.ax.set_xlabel("" if fitting else self.resax.get_xlabel())
    self.resax.set_ylabel("Residual")
    self.resax.axhline(0, color='gray', linewidth=0.8)


def _apply_plot_axes(self):
    # No positive data has a deterministic log view, without clipping values.
    for axis in ('x', 'y'):
        state = self.view[axis]
        if state['scale'] == 'log':
            interval = self.ax.dataLim.intervalx if axis == 'x' else self.ax.dataLim.intervaly
            if not np.isfinite(interval).all() or max(interval) <= 0:
                getattr(self.ax, 'set_' + axis + 'lim')(1, 10)
        getattr(self.ax, 'set_' + axis + 'scale')(state['scale'], **({'nonpositive': 'mask'} if state['scale'] == 'log' else {}))
    for axis, axes in (('x', self.ax), ('y', self.ax), ('resy', self.resax)):
        state = self.view[axis]
        coordinate = 'x' if axis == 'x' else 'y'
        if state['auto']:
            interval = axes.dataLim.intervalx if coordinate == 'x' else axes.dataLim.intervaly
            empty_log = state['scale'] == 'log' and (not np.isfinite(interval).all() or max(interval) <= 0)
            if empty_log:
                getattr(axes, 'set_' + coordinate + 'lim')(1, 10)
            else:
                getattr(axes, 'set_autoscale' + coordinate + '_on')(True)
                axes.autoscale_view(scalex=coordinate == 'x', scaley=coordinate == 'y')
        elif state['limits'] is not None:
            getattr(axes, 'set_' + coordinate + 'lim')(state['limits'])
        state['limits'] = list(getattr(axes, 'get_' + coordinate + 'lim')())
    for axes in (self.ax, self.resax):
        axes.grid(True, alpha=0.2)
        if axes.get_legend_handles_labels()[0] and self.legend_position.currentText() != 'hidden':
            loc = self.legend_position.currentText()
            # 'best' scans every plotted point on each draw (~0.5 s for a 1M-point scan).
            if loc == 'best' and sum(len(line.get_xdata()) for line in axes.get_lines()) > BEST_LEGEND_POINTS:
                loc = 'upper right'
            axes.legend(fontsize=8, loc=loc)
    # Interactive artists must not participate in automatic data limits.
    # Automatic ranges are recomputed explicitly on the next redraw.
    for axes in (self.ax, self.resax):
        axes.set_autoscalex_on(False)
        axes.set_autoscaley_on(False)


def _build_interaction(self, active):
    if active:
        self.refresh_statistics()
        self.span = SpanSelector(self.ax, self.range_selected, 'horizontal', useblit=True,
                                 interactive=True, props=dict(alpha=0.2, facecolor='tab:blue'))
        self.span.set_active(self.drag.isChecked())
        if self.stats_mode.currentIndex() == 0:
            self.stats_selector = SpanSelector(self.ax, self.statistics_selected, 'horizontal',
                                               useblit=True, interactive=True,
                                               props=dict(alpha=.18, facecolor='tab:green'))
        else:
            self.stats_selector = RectangleSelector(self.ax, self.statistics_rectangle_selected,
                                                    useblit=True, interactive=True,
                                                    props=dict(alpha=.18, facecolor='tab:green'))
        if self.stats_region is not None and self.show_statistics.isChecked():
            self.stats_selector.extents = (self.stats_region[:2] if self.stats_mode.currentIndex() == 0
                                           else self.stats_region)
            self.stats_selector.set_visible(True)
        self.stats_selector.set_active(self.stats_drag.isChecked() and self.show_statistics.isChecked())
    self.cursors += [Cursor(axes, useblit=False, color='gray', linewidth=.7) for axes in (self.ax, self.resax)]
    for cursor in self.cursors:
        cursor.set_active(self.cursor_enabled.isChecked())
    self.sync_axis_controls()
    for axis, axes, event in [('x', self.ax, 'xlim_changed'), ('x', self.resax, 'xlim_changed'),
                              ('y', self.ax, 'ylim_changed'), ('resy', self.resax, 'ylim_changed')]:
        callback = axes.callbacks.connect(event, lambda ax, key=axis: self.limits_changed(key, ax))
        self.limit_callbacks.append((axes, callback))
    self.canvas.draw_idle()




