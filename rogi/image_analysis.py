"""Temporary image processing using the single-signal pipeline's numerical rules."""
from copy import deepcopy
import numpy as np
from .analysis import analyze, validate_operations, channel_unit
from .core import Dataset


def process_image(values, operations, *, axis='X', spacing=1., coordinate_unit='pixel', signal_unit=''):
    """Global centering/normalization; local steps along original image X or Y.

    No flattening across scan-line boundaries for local operations. Missing
    pixels remain missing; local windows/derivatives never bridge missing gaps.
    Coordinates are pixel centres separated by spacing (in coordinate_unit).
    Returns independent arrays, never a project dataset.
    """
    validate_operations(operations)
    array = np.array(values, dtype=float, copy=True)
    if array.ndim != 2 or not array.size or np.isinf(array).any():
        raise ValueError('Preview needs a nonempty 2D image with finite or missing pixels.')
    if axis not in ('X', 'Y') or not np.isfinite(spacing) or spacing <= 0:
        raise ValueError('Choose X or Y and a positive finite pixel spacing.')
    unit = signal_unit
    for step in operations:
        if not np.isfinite(array).any():
            raise ValueError('Operation has no finite image pixels.')
        if step['operation'] in ('mean_subtract', 'normalize'):
            flat = array.ravel()
            # The global steps do not use coordinate distances.
            temporary = Dataset('Image pixels', ['Index', 'Signal'],
                                np.column_stack((np.arange(flat.size), flat)))
            result = analyze(temporary, [step], xunit='1', yunit=unit)
            array = result.values[:, 1].reshape(array.shape).copy()
            unit = result.column_units[1]
        else:
            lines = array if axis == 'X' else array.T
            output = np.full(lines.shape, np.nan)
            coordinates = np.arange(lines.shape[1], dtype=float) * spacing
            output_unit = unit
            for index, line in enumerate(lines):
                if not np.isfinite(line).any():
                    continue
                temporary = Dataset('Image line', ['Coordinate', 'Signal'], np.column_stack((coordinates, line)))
                result = analyze(temporary, [step], xunit=coordinate_unit, yunit=unit)
                output[index] = result.values[:, 1]
                output_unit = result.column_units[1]
            array = output if axis == 'X' else output.T.copy()
            unit = output_unit
    return array, unit


# Kept separate from the main image viewer: no dataset creation or save hooks.
from PySide6 import QtWidgets as W
from matplotlib.figure import Figure
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from .navigation import PlotNavigationToolbar
from .images import raster, contrast_limits
from .spatial import image_geometry
from .screen import fit_to_screen


class ImagePreviewDialog(W.QDialog):
    def __init__(self, source, preset, preset_name, parent=None, palette='viridis', transpose=False):
        super().__init__(parent)
        self.setWindowTitle(f'Temporary image preview — {preset_name}')
        fit_to_screen(self, 1050, 740)
        self.input = raster(source).copy()
        self.operations = deepcopy(preset['operations'])
        self.geometry = image_geometry(source, self.input.shape)
        self.input_unit = channel_unit(source, 3)
        self.palette, self.transposed = palette, transpose
        self.result = None
        self.output_unit = None
        layout = W.QVBoxLayout(self)
        info = W.QLabel(f'{source.name} · revision {source.revision}\n'
                       'Temporary snapshot only: no dataset is created and no processed values are saved with the project.')
        info.setWordWrap(True)
        layout.addWidget(info)
        labels = dict(mean_subtract='Subtract mean', normalize='Normalize',
                      moving_average='Moving average', differentiate='Differentiate')
        recipe = W.QLabel(' → '.join(labels[step['operation']] +
                          (' (' + ', '.join(f'{k}={v}' for k, v in step['parameters'].items()) + ')'
                           if step['parameters'] else '') for step in self.operations))
        recipe.setWordWrap(True)
        layout.addWidget(recipe)
        row = W.QHBoxLayout()
        row.addWidget(W.QLabel('Smoothing / differentiation axis'))
        self.axis = W.QComboBox()
        self.axis.addItems(['X — original rows', 'Y — original columns'])
        row.addWidget(self.axis)
        row.addStretch()
        layout.addLayout(row)
        rules = W.QLabel('Mean and normalization use all finite image pixels. Local operations stay within each row/column, '
                        'preserve missing gaps and clip smoothing windows at boundaries. Derivatives use calibrated pixel spacing '
                        '(pixel units when unavailable), one-sided endpoint slopes and missing values for singletons. '
                        'No resampling. Each map uses its own full-range color scale.')
        rules.setWordWrap(True)
        layout.addWidget(rules)
        self.figure = Figure(figsize=(9, 5), tight_layout=True)
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.navigation = PlotNavigationToolbar(self.canvas, self)
        layout.addWidget(self.navigation)
        layout.addWidget(self.canvas, 1)
        self.status = W.QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        close = W.QPushButton('Close preview')
        close.clicked.connect(self.reject)
        layout.addWidget(close)
        self.axis.currentIndexChanged.connect(self.preview)
        self.preview()

    def preview(self, *_):
        self.result, self.output_unit = None, None
        self.figure.clear()
        self.navigation.update()
        extent, xlabel, ylabel = self.geometry
        along_x = self.axis.currentIndex() == 0
        span = extent[1]-extent[0] if along_x else extent[3]-extent[2]
        count = self.input.shape[1 if along_x else 0]
        label = xlabel if along_x else ylabel
        coordinate_unit = label.split('(', 1)[1].rstrip(')') if '(' in label else 'pixel'
        try:
            self.result, self.output_unit = process_image(self.input, self.operations,
                axis='X' if along_x else 'Y', spacing=span/count,
                coordinate_unit=coordinate_unit, signal_unit=self.input_unit)
        except ValueError as error:
            self.status.setText(str(error))
            self.canvas.draw_idle()
            return
        if self.transposed:
            extent = (extent[2], extent[3], extent[0], extent[1])
            xlabel, ylabel = ylabel, xlabel
        for ax, array, title, unit in zip(self.figure.subplots(1, 2),
                [self.input, self.result], ['Input', 'Temporary result'], [self.input_unit, self.output_unit]):
            lo, hi = contrast_limits(array, 'Full range')
            artist = ax.imshow(np.ma.masked_invalid(array.T if self.transposed else array),
                extent=extent, origin='lower', interpolation='nearest', aspect='equal',
                cmap=self.palette, vmin=lo, vmax=hi)
            ax.set_title(title)
            ax.set_xlabel(xlabel)
            ax.set_ylabel(ylabel)
            self.figure.colorbar(artist, ax=ax, label=unit or 'unknown unit', shrink=.75)
        self.status.setText(f'Output units: {self.output_unit or "unknown"}. '
                            f'{np.count_nonzero(~np.isfinite(self.result))} missing pixels. Close to discard this preview.')
        self.canvas.draw_idle()
