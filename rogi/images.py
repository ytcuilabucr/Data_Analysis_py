"""Non-destructive raster presentation for imported SPM channel tables."""
from .spatial import image_geometry
from .scanfile import channel_views
import textwrap
from copy import deepcopy
from .core import Dataset, export_data
from pathlib import Path
import numpy as np
from PySide6 import QtCore as C, QtWidgets as W
from matplotlib.figure import Figure
from matplotlib.patches import Rectangle
from mpl_toolkits.axes_grid1 import make_axes_locatable
from .navigation import PlotNavigationToolbar
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg


def is_image(dataset):
    if dataset is not None and 'channels' in dataset.instrument_metadata:
        return any(is_image(view) for view in channel_views(dataset))
    return (dataset is not None and len(dataset.columns) == 4
            and dataset.columns[:3] == ['Sample', 'X pixel', 'Y pixel'])


def comparison_key(dataset):
    """Match the signal (including direction/units) and original file format."""
    if dataset is None:
        return None
    extension = Path(dataset.source).suffix.lower()
    if extension not in ('.spm', '.sxm'):
        return None
    return extension, dataset.instrument_metadata.get('format'), dataset.columns[3].strip()


def raster(dataset):
    """Reconstruct by pixel coordinates, rejecting edited or incomplete grids."""
    if dataset is not None and 'channels' in dataset.instrument_metadata:
        views = [view for view in channel_views(dataset) if is_image(view)]
        dataset = next((v for v in views if v.id == f'{dataset.id}:{dataset.ycol}'), views[0] if views else None)
    if not is_image(dataset):
        raise ValueError('Select an SPM image channel. Spectra and force curves use the Line plot tab.')
    xy = dataset.values[:, 1:3]
    if not np.isfinite(xy).all() or (xy < 0).any() or (xy != np.floor(xy)).any():
        raise ValueError('Image pixel coordinates must be nonnegative whole numbers.')
    width, height = (int(xy[:, i].max()) + 1 for i in range(2))
    if width * height != len(xy):
        raise ValueError('Image coordinates do not form a complete rectangular grid.')
    x, y = xy[:, 0].astype(int), xy[:, 1].astype(int)
    indices = y * width + x
    if np.unique(indices).size != len(indices):
        raise ValueError('Image contains duplicate pixel coordinates.')
    result = np.empty((height, width))
    result[y, x] = dataset.values[:, 3]
    return result


def contrast_limits(values, mode, lower=2, upper=98):
    finite = values[np.isfinite(values)]
    if mode == 'Manual':
        if not np.isfinite([lower, upper]).all() or lower >= upper:
            raise ValueError('Color minimum and maximum must be finite, with minimum < maximum.')
        return float(lower), float(upper)
    if mode == 'Percentile' and not 0 <= lower < upper <= 100:
        raise ValueError('Percentiles must satisfy 0 ≤ low < high ≤ 100.')
    if not finite.size:
        return 0., 1.
    lo, hi = (np.percentile(finite, [lower, upper]) if mode == 'Percentile'
              else (finite.min(), finite.max()))
    if lo == hi:
        delta = max(abs(float(lo)) * 1e-6, 1e-12)
        lo, hi = float(lo) - delta, float(hi) + delta
    return float(lo), float(hi)


def extract_profile(dataset, axis, index, parent=None):
    """Extract along original X or Y at a pixel centre without interpolation."""
    array = raster(dataset)
    e, xl, yl = image_geometry(dataset, array.shape)
    if axis not in ('X', 'Y'):
        raise ValueError('Profile axis must be X or Y.')
    along_x = axis == 'X'
    if not isinstance(index, (int, np.integer)) or not 0 <= index < array.shape[0 if along_x else 1]:
        raise ValueError('Profile position is outside the image.')
    x = e[0] + (np.arange(array.shape[1]) + .5) * (e[1]-e[0]) / array.shape[1]
    y = e[2] + (np.arange(array.shape[0]) + .5) * (e[3]-e[2]) / array.shape[0]
    metadata = deepcopy(dataset.instrument_metadata) or dict(
        format='spectrum', version=1, source_dataset_id=parent or dataset.id, sections=[], unparsed=[])
    metadata.pop('channels', None)
    metadata['profile_extraction'] = dict(
        source_dataset_id=parent or dataset.id, source_channel_id=dataset.id,
        source_channel=dataset.columns[3], source_revision=dataset.revision,
        axis=axis, position_axis='Y' if along_x else 'X', pixel_index=int(index),
        position=float(y[index] if along_x else x[index]),
        position_label=yl if along_x else xl, sampling='pixel centre')
    return Dataset(f'{dataset.name} — {axis} profile at pixel {index}',
                   [xl if along_x else yl, dataset.columns[3]],
                   np.column_stack((x if along_x else y, array[index, :] if along_x else array[:, index])),
                   raw=False, parent=parent or dataset.id, source=dataset.source,
                   group=dataset.group, group_path=deepcopy(dataset.group_path), instrument_metadata=metadata)


class ImageViewer(W.QWidget):
    profile_created = C.Signal(object)
    preview_requested = C.Signal(str)
    def __init__(self, parent=None):
        super().__init__(parent)
        self.datasets, self.current = [], None
        self.signature = None
        self.channel_choices = {}
        self.file_current = None
        self.file_channels = []
        self.panels = {}
        self.cursor_positions = {}
        self.cursor_lines = []
        self.second_positions = {}
        self.cursor_markers = []
        self.region_patch = None
        self.cut_axes = None
        self.drag_axis = None
        layout = W.QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(5)
        controls = W.QHBoxLayout()
        self.palette = W.QComboBox()
        self.palette.addItems(['viridis', 'gray', 'inferno', 'magma', 'cividis', 'coolwarm'])
        self.palette.setAccessibleName('Image color palette')
        self.mode = W.QComboBox()
        self.mode.addItems(['Full range', 'Percentile', 'Manual'])
        self.mode.setAccessibleName('Image contrast mode')
        self.low = W.QLineEdit('2')
        self.high = W.QLineEdit('98')
        for widget, name in ((self.low, 'Lower image contrast limit'), (self.high, 'Upper image contrast limit')):
            widget.setMaximumWidth(85)
            widget.setAccessibleName(name)
        self.apply = W.QPushButton('Apply')
        for widget in (W.QLabel('Colors'), self.palette, W.QLabel('Contrast'), self.mode,
                       W.QLabel('Low'), self.low, W.QLabel('High'), self.high, self.apply):
            controls.addWidget(widget)
        controls.addStretch()
        layout.addLayout(controls)
        channel_row = W.QHBoxLayout()
        self.channel = W.QComboBox()
        self.channel.setAccessibleName('2D map channel')
        self.channel.setMinimumContentsLength(25)
        self.channel.setSizeAdjustPolicy(W.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        channel_row.addWidget(W.QLabel('Channel'))
        channel_row.addWidget(self.channel, 1)
        comparison = channel_row
        self.compare = W.QComboBox()
        self.compare.setAccessibleName('Compare image channel')
        self.compare.setMinimumContentsLength(25)
        self.compare.setSizeAdjustPolicy(W.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        comparison.addWidget(W.QLabel('Compare with'))
        comparison.addWidget(self.compare, 1)
        layout.addLayout(comparison)
        preview_scroll = W.QScrollArea()
        preview_scroll.setWidgetResizable(True)
        preview_scroll.setMaximumHeight(68)
        preview_scroll.setVerticalScrollBarPolicy(C.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        preview_widget = W.QWidget()
        self.preview_buttons = W.QHBoxLayout(preview_widget)
        self.preview_buttons.setContentsMargins(0, 0, 0, 0)
        preview_scroll.setWidget(preview_widget)
        layout.addWidget(preview_scroll)
        self.set_presets({})
        profile_row = W.QHBoxLayout()
        self.transpose = W.QCheckBox('Transpose display')
        self.cursor_choice = W.QComboBox()
        self.cursor_choice.addItems(['□ Cursor 1', '○ Cursor 2'])
        self.profile_axis = W.QComboBox()
        self.profile_axis.addItems(['X profile', 'Y profile'])
        self.export_profile_button = W.QPushButton('Export profile CSV…')
        self.create_profile_button = W.QPushButton('Create profile dataset')
        for widget in (self.transpose, self.cursor_choice, self.profile_axis, self.export_profile_button, self.create_profile_button):
            profile_row.addWidget(widget)
        layout.addLayout(profile_row)
        region_row = W.QHBoxLayout()
        self.select_region = W.QCheckBox('Select rectangle between cursors')
        self.create_region_button = W.QPushButton('Create region dataset')
        self.region_summary = W.QLabel()
        region_row.addWidget(self.select_region)
        region_row.addWidget(self.create_region_button)
        region_row.addWidget(self.region_summary, 1)
        layout.addLayout(region_row)
        self.select_region.toggled.connect(self.refresh_region)
        self.create_region_button.clicked.connect(lambda: self.profile_created.emit(self.selected_region()))
        self.transpose.toggled.connect(lambda: self.render(reset=True))
        self.export_profile_button.clicked.connect(self.export_profile)
        self.create_profile_button.clicked.connect(lambda: self.profile_created.emit(self.selected_profile()))
        self.note = W.QLabel('Axes use scan dimensions when available; otherwise pixel indices. Stored orientation is preserved.\n'
                             'Drag square/circle markers freely in X and Y; drag a crosshair line to move one axis. '
                             'X/Y profiles always refer to the original axes, including when transposed.\n'
                             'Each map has its own color bar; manual limits apply to both maps.')
        self.note.setWordWrap(True)
        self.note.hide()
        self.figure = Figure(figsize=(8, 6))
        self.figure.subplots_adjust(left=.09, right=.91, bottom=.1, top=.92, wspace=.5)
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.navigation = PlotNavigationToolbar(self.canvas, self)
        navigation_row = W.QHBoxLayout()
        navigation_row.addWidget(self.navigation)
        navigation_row.addStretch()
        self.show_table = W.QCheckBox('Show data table')
        navigation_row.addWidget(self.show_table)
        layout.addLayout(navigation_row)
        self.canvas.setToolTip(self.note.text())
        layout.addWidget(self.canvas, 3)
        self.message = W.QLabel()
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        self.readout = W.QLabel('Move the pointer over a pixel to inspect its value.')
        self.readout.setWordWrap(True)
        self.readout.setTextInteractionFlags(C.Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.readout)
        self.canvas.mpl_connect('motion_notify_event', self.motion)
        self.canvas.mpl_connect('button_press_event', self.press)
        self.canvas.mpl_connect('button_release_event', self.release)
        self.channel.currentIndexChanged.connect(self.select_channel)
        self.palette.currentTextChanged.connect(self.render)
        self.compare.currentIndexChanged.connect(lambda: self.render(reset=True))
        self.mode.currentTextChanged.connect(self.mode_changed)
        self.apply.clicked.connect(self.render)
        self.low.returnPressed.connect(self.render)
        self.high.returnPressed.connect(self.render)
        self.mode_changed()

    def set_presets(self, presets):
        while self.preview_buttons.count():
            item = self.preview_buttons.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.preview_buttons.addWidget(W.QLabel('Temporary image preview:'))
        if not presets:
            self.preview_buttons.addWidget(W.QLabel('Save or import a preset in Analysis pipeline… first.'))
        for name in presets:
            button = W.QPushButton(name)
            button.setToolTip('Click once to display this preset on the current image channel without saving a dataset.')
            button.clicked.connect(lambda checked=False, n=name: self.preview_requested.emit(n))
            self.preview_buttons.addWidget(button)
        self.preview_buttons.addStretch()

    def mode_changed(self, *args):
        mode = self.mode.currentText()
        self.low.setToolTip('Lower percentile (0–100)' if mode == 'Percentile' else 'Minimum displayed signal value')
        self.high.setToolTip('Upper percentile (0–100)' if mode == 'Percentile' else 'Maximum displayed signal value')
        self.low.setEnabled(mode != 'Full range')
        self.high.setEnabled(mode != 'Full range')
        if mode == 'Percentile':
            self.low.setText('2')
            self.high.setText('98')
        elif mode == 'Manual':
            limits = next((panel[2].get_clim() for panel in self.panels.values()), (0, 1))
            self.low.setText(f'{limits[0]:.12g}')
            self.high.setText(f'{limits[1]:.12g}')
        self.render()

    def set_context(self, datasets, current):
        signature = (current.id if current else None,
                     tuple((d.id, d.revision, d.name, tuple(d.columns)) for d in datasets))
        if signature == self.signature:
            return
        self.signature = signature
        self.datasets = [v for d in datasets for v in channel_views(d) if is_image(v)]
        self.file_current = current
        self.file_channels = [v for v in channel_views(current) if is_image(v)] if current else []
        choice = self.channel_choices.get(current.id) if current else None
        if choice is None and current is not None:
            choice = f'{current.id}:{current.ycol}'
        with C.QSignalBlocker(self.channel):
            self.channel.clear()
            for view in self.file_channels:
                self.channel.addItem(view.name.split(' — ', 1)[-1], view.id)
            self.channel.setCurrentIndex(max(0, self.channel.findData(choice)))
        self.channel.setEnabled(bool(self.file_channels))
        self.select_channel()

    def select_channel(self, *args):
        old_current = self.current.id if self.current else None
        self.current = next((v for v in self.file_channels if v.id == self.channel.currentData()), None)
        if self.current is not None:
            self.channel_choices[self.file_current.id] = self.current.id
        previous = self.compare.currentData()
        with C.QSignalBlocker(self.compare):
            self.compare.clear()
            self.compare.addItem('None', None)
            key = comparison_key(self.current)
            for view in self.datasets:
                if key is not None and view.id != self.current.id and comparison_key(view) == key:
                    self.compare.addItem(view.name, view.id)
            self.compare.setCurrentIndex(max(0, self.compare.findData(previous)))
        self.compare.setEnabled(self.compare.count() > 1)
        self.compare.setToolTip('Same channel, direction, units, and file type only.'
                                if self.compare.count() > 1 else 'No other matching channels in this file type.')
        self.render(reset=old_current != (self.current.id if self.current else None))

    def render(self, *args, reset=False):
        self.drag_axis = None
        self.export_profile_button.setEnabled(False)
        self.create_profile_button.setEnabled(False)
        self.create_region_button.setEnabled(False)
        self.region_summary.clear()
        if self.current is None or not is_image(self.current):
            self.figure.clear()
            self.panels = {}
            self.cut_axes = None
            self.message.setText('Select an SPM/SXM file, then choose its image channel above. Spectra and force curves use Line plot.')
            self.readout.clear()
            self.canvas.draw_idle()
            self.navigation.update()
            return
        selected = [self.current]
        other = next((d for d in self.datasets if d.id == self.compare.currentData()), None)
        if other is not None:
            selected.append(other)
        try:
            mode = self.mode.currentText()
            lo, hi = (float(self.low.text()), float(self.high.text())) if mode != 'Full range' else (0, 100)
            arrays = [raster(d) for d in selected]
            limits = [contrast_limits(a, mode, lo, hi) for a in arrays]
            geometries = [image_geometry(d, a.shape) for d, a in zip(selected, arrays)]
            if self.transpose.isChecked():
                arrays = [a.T for a in arrays]
                geometries = [((e[2], e[3], e[0], e[1]), yl, xl) for e, xl, yl in geometries]
        except ValueError as error:
            # An invalid grid must never leave a stale image presented as current.
            self.figure.clear()
            self.panels = {}
            self.cut_axes = None
            self.readout.clear()
            self.message.setText(str(error))
            self.canvas.draw_idle()
            self.navigation.update()
            return
        existing = list(self.panels.values())
        same = (not reset and [p[0].id for p in existing] == [d.id for d in selected]
                and [p[1].shape for p in existing] == [a.shape for a in arrays]
                and all(tuple(p[2].get_extent()) == g[0] for p, g in zip(existing, geometries)))
        if same:
            for (d, old, artist), array, clim in zip(existing, arrays, limits):
                artist.set_data(np.ma.masked_invalid(array))
                artist.set_cmap(self.palette.currentText())
                artist.set_clim(*clim)
                artist.axes.set_title(textwrap.fill(d.name, 38), fontsize=9)
                self.panels[artist.axes] = (d, array, artist)
        else:
            self.figure.clear()
            self.panels = {}
            self.cut_axes = None
            axes = self.figure.subplots(1, len(selected), squeeze=False)[0]
            for ax, d, array, clim, geometry in zip(axes, selected, arrays, limits, geometries):
                extent, xlabel, ylabel = geometry
                artist = ax.imshow(np.ma.masked_invalid(array), origin='lower', interpolation='nearest',
                                   cmap=self.palette.currentText(), vmin=clim[0], vmax=clim[1], aspect='equal', extent=extent)
                ax.set_title(textwrap.fill(d.name, 38), fontsize=9)
                ax.set_xlabel(xlabel)
                ax.set_ylabel(ylabel)
                divider = make_axes_locatable(ax)
                if d is self.current:
                    below = divider.append_axes('bottom', size='30%', pad=.55, sharex=ax)
                    right = divider.append_axes('right', size='30%', pad=.6, sharey=ax)
                    self.cut_axes = (below, right)
                    below.tick_params(axis='x', labelsize=8)
                    right.tick_params(axis='y', labelleft=False)
                cax = divider.append_axes('right', size='4%', pad=.55)
                self.figure.colorbar(artist, cax=cax, orientation='vertical', label=('Raw counts' if d.columns[3].endswith('(raw counts)')
                                            else textwrap.fill(d.columns[3], 20)))
                self.panels[ax] = (d, array, artist)
            self.navigation.update()
        self.update_profiles()
        self.message.setText(' · '.join(f'Map {i}: {a.shape[1]} × {a.shape[0]} pixels, '
                                       f'{np.count_nonzero(~np.isfinite(a))} missing'
                                       for i, a in enumerate(arrays, 1)))
        self.readout.setText('Move the pointer over a pixel to inspect its value.')
        self.canvas.draw_idle()

    def snapshot(self):
        return dict(palette=self.palette.currentText(), mode=self.mode.currentText(),
                    low=self.low.text(), high=self.high.text(), compare=self.compare.currentData(),
                    channels=dict(self.channel_choices), transpose=self.transpose.isChecked(),
                    cursor_positions=deepcopy(self.cursor_positions),
                    second_positions=deepcopy(self.second_positions),
                    active_cursor=self.cursor_choice.currentIndex(), region_selected=self.select_region.isChecked(),
                    zoom={d.id: dict(xlim=list(ax.get_xlim()), ylim=list(ax.get_ylim()))
                          for ax, (d, _, _) in self.panels.items()})

    def restore_snapshot(self, state, datasets, current):
        self.channel_choices = dict(state['channels'])
        self.cursor_positions = deepcopy(state.get('cursor_positions', {}))
        self.second_positions = deepcopy(state.get('second_positions', {}))
        self.cursor_choice.setCurrentIndex(state.get('active_cursor', 0))
        with C.QSignalBlocker(self.select_region):
            self.select_region.setChecked(state.get('region_selected', False))
        with C.QSignalBlocker(self.transpose):
            self.transpose.setChecked(state.get('transpose', False))
        self.signature = None
        self.set_context(datasets, current)
        for widget, value in ((self.palette, state['palette']), (self.mode, state['mode'])):
            with C.QSignalBlocker(widget):
                widget.setCurrentText(value)
        self.low.setText(str(state['low']))
        self.high.setText(str(state['high']))
        self.low.setEnabled(state['mode'] != 'Full range')
        self.high.setEnabled(state['mode'] != 'Full range')
        with C.QSignalBlocker(self.compare):
            self.compare.setCurrentIndex(max(0, self.compare.findData(state['compare'])))
        self.render(reset=True)
        for ax, (dataset, _, _) in self.panels.items():
            limits = state['zoom'].get(dataset.id)
            if limits:
                ax.set_xlim(limits['xlim'])
                ax.set_ylim(limits['ylim'])
        self.navigation.update()
        self.canvas.draw_idle()

    def selected_profile(self):
        axis = 'X' if self.profile_axis.currentIndex() == 0 else 'Y'
        positions = self.second_positions if self.cursor_choice.currentIndex() else self.cursor_positions
        x, y = positions[self.current.id]
        return extract_profile(self.current, axis, y if axis == 'X' else x, self.file_current.id)

    def export_profile(self):
        profile = self.selected_profile()
        path, _ = W.QFileDialog.getSaveFileName(self, 'Export profile', '', 'CSV (*.csv)')
        if path:
            try:
                export_data(profile, path)
            except OSError as error:
                W.QMessageBox.warning(self, 'Profile export failed', str(error))

    def selected_region(self):
        d = self.current
        array = raster(d)
        x0, y0 = self.cursor_positions[d.id]
        x1, y1 = self.second_positions[d.id]
        x0, x1 = sorted((x0, x1))
        y0, y1 = sorted((y0, y1))
        xp = extract_profile(d, 'X', y0, self.file_current.id)
        yp = extract_profile(d, 'Y', x0, self.file_current.id)
        x, y = np.meshgrid(xp.values[x0:x1+1, 0], yp.values[y0:y1+1, 0])
        values = array[y0:y1+1, x0:x1+1].ravel()
        metadata = deepcopy(xp.instrument_metadata)
        metadata.pop('profile_extraction')
        metadata['region_extraction'] = dict(source_dataset_id=self.file_current.id,
            source_channel_id=d.id, source_channel=d.columns[3], source_revision=d.revision,
            pixel_bounds=[x0, x1, y0, y1], bounds_inclusive=True,
            coordinate_bounds=[float(x.min()), float(x.max()), float(y.min()), float(y.max())],
            coordinate_labels=[xp.columns[0], yp.columns[0]])
        return Dataset(d.name + ' — cursor rectangle',
            ['Region sample', xp.columns[0], yp.columns[0], d.columns[3]],
            np.column_stack((np.arange(len(values)), x.ravel(), y.ravel(), values)),
            raw=False, parent=self.file_current.id, source=d.source, xcol=1, ycol=3,
            group=d.group, group_path=deepcopy(d.group_path), instrument_metadata=metadata)

    def refresh_region(self, *args):
        if self.region_patch is not None and self.region_patch.axes is not None:
            self.region_patch.remove()
        self.region_patch = None
        enabled = bool(self.panels) and self.select_region.isChecked()
        self.create_region_button.setEnabled(enabled)
        self.region_summary.clear()
        if enabled:
            region = self.selected_region()
            values = region.values[:, 3]
            finite = values[np.isfinite(values)]
            mean = f'{finite.mean():.6g}' if len(finite) else 'missing'
            self.region_summary.setText(f'{len(values)} pixels · {len(values)-len(finite)} missing · mean {mean}')
            x0, x1, y0, y1 = region.instrument_metadata['region_extraction']['pixel_bounds']
            ax = next(iter(self.panels))
            _, array, artist = self.panels[ax]
            if self.transpose.isChecked():
                x0, x1, y0, y1 = y0, y1, x0, x1
            l, r, b, t = artist.get_extent()
            dx, dy = (r-l)/array.shape[1], (t-b)/array.shape[0]
            self.region_patch = Rectangle((l+x0*dx, b+y0*dy), (x1-x0+1)*dx, (y1-y0+1)*dy,
                                          facecolor='gold', edgecolor='gold', alpha=.2)
            ax.add_patch(self.region_patch)
        self.canvas.draw_idle()

    def update_profiles(self):
        for line in self.cursor_lines + self.cursor_markers:
            if line.axes is not None:
                line.remove()
        self.cursor_lines, self.cursor_markers = [], []
        ax, (d, displayed, artist) = next(iter(self.panels.items()))
        array = displayed.T if self.transpose.isChecked() else displayed
        below, right = self.cut_axes
        # Remove curves without clearing the shared spatial axes or their zoom.
        for pax in self.cut_axes:
            for line in list(pax.lines):
                line.remove()
        for number, (positions, marker, color) in enumerate(zip(
                (self.cursor_positions, self.second_positions), ('s', 'o'), ('#00a8b5', '#e87800'))):
            default = (array.shape[1] // 2, array.shape[0] // 2) if number == 0 else (array.shape[1] // 4, array.shape[0] // 4)
            x, y = positions.get(d.id, default)
            x, y = min(max(x, 0), array.shape[1]-1), min(max(y, 0), array.shape[0]-1)
            positions[d.id] = [x, y]
            profiles = [extract_profile(d, 'X', y), extract_profile(d, 'Y', x)]
            xc, yc = profiles[0].values[x, 0], profiles[1].values[y, 0]
            if self.transpose.isChecked():
                xc, yc = yc, xc
                profiles.reverse()
            self.cursor_lines.extend([ax.axvline(xc, color=color, linewidth=1), ax.axhline(yc, color=color, linewidth=1)])
            self.cursor_markers.extend(ax.plot([xc], [yc], marker=marker, markersize=9,
                                               markerfacecolor='none', markeredgewidth=2, color=color, zorder=5))
            below.plot(profiles[0].values[:, 0], profiles[0].values[:, 1], color=color)
            right.plot(profiles[1].values[:, 1], profiles[1].values[:, 0], color=color)
        below.set_xlabel(profiles[0].columns[0])
        below.set_ylabel(textwrap.fill(d.columns[3], 20), fontsize=8)
        right.set_xlabel(textwrap.fill(d.columns[3], 20), fontsize=8)
        below.relim(); below.autoscale_view(scalex=False, scaley=True)
        right.relim(); right.autoscale_view(scalex=True, scaley=False)
        self.export_profile_button.setEnabled(True)
        self.create_profile_button.setEnabled(True)
        self.refresh_region()

    def press(self, event):
        if self.navigation.mode or event.button != 1 or not self.panels:
            return
        ax = next(iter(self.panels))
        if event.inaxes is not ax or event.xdata is None or event.ydata is None:
            return
        # Prefer the selected cursor if markers overlap.
        order = [self.cursor_choice.currentIndex(), 1-self.cursor_choice.currentIndex()]
        for i in order:
            marker = self.cursor_markers[i]
            mx, my = ax.transData.transform((marker.get_xdata()[0], marker.get_ydata()[0]))
            if np.hypot(event.x-mx, event.y-my) <= 12:
                self.cursor_choice.setCurrentIndex(i)
                self.drag_axis = 2
                return
        distances = []
        for line in self.cursor_lines:
            if len(distances) % 2 == 0:
                pos = ax.transData.transform((line.get_xdata()[0], event.ydata))[0]
                distances.append(abs(event.x-pos))
            else:
                pos = ax.transData.transform((event.xdata, line.get_ydata()[0]))[1]
                distances.append(abs(event.y-pos))
        if min(distances) <= 8:
            nearest = int(np.argmin(distances))
            self.cursor_choice.setCurrentIndex(nearest // 2)
            self.drag_axis = nearest % 2

    def release(self, event):
        self.drag_axis = None

    def motion(self, event):
        panel = self.panels.get(event.inaxes)
        if panel is None or event.xdata is None or event.ydata is None:
            self.readout.setText('Move the pointer over a pixel to inspect its value.')
            return
        d, array, artist = panel
        left, right, bottom, top = artist.get_extent()
        x = int(np.floor((event.xdata - left) / (right - left) * array.shape[1]))
        y = int(np.floor((event.ydata - bottom) / (top - bottom) * array.shape[0]))
        if not (0 <= x < array.shape[1] and 0 <= y < array.shape[0]):
            self.readout.clear()
            return
        value = array[y, x]
        if self.drag_axis is not None and event.inaxes is next(iter(self.panels)):
            positions = self.second_positions if self.cursor_choice.currentIndex() else self.cursor_positions
            if self.drag_axis == 2:
                positions[d.id] = [y, x] if self.transpose.isChecked() else [x, y]
            else:
                original_axis = 1-self.drag_axis if self.transpose.isChecked() else self.drag_axis
                positions[d.id][original_axis] = x if self.drag_axis == 0 else y
            self.update_profiles()
            self.canvas.draw_idle()
        if self.transpose.isChecked():
            x, y = y, x
        text = f'{value:.8g}' if np.isfinite(value) else 'missing'
        position = ''
        if not event.inaxes.get_xlabel().endswith('pixel'):
            xc = left + ((y if self.transpose.isChecked() else x) + .5) * (right - left) / array.shape[1]
            yc = bottom + ((x if self.transpose.isChecked() else y) + .5) * (top - bottom) / array.shape[0]
            position = f' | {event.inaxes.get_xlabel()} {xc:.6g}, {event.inaxes.get_ylabel()} {yc:.6g}'
        self.readout.setText(f'{d.name} | X pixel {x}, Y pixel {y}{position} | {d.columns[3]}: {text}')
