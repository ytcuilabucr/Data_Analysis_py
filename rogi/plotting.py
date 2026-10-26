"""Plot presentation validation and non-destructive logarithmic masking."""
from copy import deepcopy
import numpy as np
from matplotlib.colors import is_color_like

MARKERS = {'Auto': '', 'None': 'None', 'Circle': 'o', 'Square': 's',
           'Triangle': '^', 'Diamond': 'D', 'Plus': '+', 'Cross': 'x'}
LEGENDS = ('best', 'upper right', 'upper left', 'lower left', 'lower right',
           'center left', 'center right', 'lower center', 'upper center', 'center',
           'outside right', 'outside top', 'hidden')
FONT_SIZES = (6, 7, 8, 9, 10, 11, 12, 14, 16, 18, 20, 24)
# None keeps Matplotlib's default size for that text; '' keeps its default family or color.
# family and color apply to the axis label and its tick labels; unit appends the
# axis unit to a typed label. tick_step is a fixed major tick spacing on linear
# axes (None: automatic); invert and grid apply to the axis in every panel.
AXIS_STYLE = dict(label_size=None, tick_size=None, family='', color='', bold=False, italic=False, unit=True,
                  tick_direction='out', tick_length=None, minor_ticks='auto', number_format='auto',
                  decimals=2, tick_step=None, grid=True, invert=False)
TICK_DIRECTIONS = {'Outside': 'out', 'Inside': 'in', 'Both sides': 'inout'}
MINOR_TICKS = {'Automatic': 'auto', 'On': 'on', 'Off': 'off'}
NUMBER_FORMATS = {'Automatic': 'auto', 'Plain': 'plain', 'Scientific': 'scientific', 'Fixed decimals': 'fixed'}
# Settings that describe one axis's values rather than its look stay with that axis.
AXIS_OWN_KEYS = ('unit', 'tick_step', 'invert')
# Legend colors '' keep Matplotlib's defaults; alpha is the frame's opacity.
PLOT_STYLE = dict(title_size=None, legend_size=8, legend_columns=1, legend_frame=True,
                  legend_title='', legend_color='', legend_frame_color='', legend_background='',
                  legend_alpha=0.8, legend_rounded=True, legend_marker_scale=1.0, legend_spacing=0.5,
                  legend_fit_entries=True, legend_sd_entries=True, legend_residuals=True,
                  x_axis=AXIS_STYLE, y_axis=AXIS_STYLE)
# Projects saved before per-axis styles stored one label and tick size for both axes.
LEGACY_AXIS_KEYS = ('label_size', 'tick_size')


def validate_appearance(color, marker):
    if not isinstance(color, str) or (color and not is_color_like(color)):
        raise ValueError("Invalid dataset color.")
    if marker not in MARKERS.values():
        raise ValueError("Invalid dataset marker.")


def validate_view(settings):
    validate_panels(settings)
    for axis in ('x', 'y', 'resy'):
        scale = settings.get(axis + 'scale', 'linear')
        if scale not in ('linear', 'log') or (axis == 'resy' and scale != 'linear'):
            raise ValueError("Invalid axis scale.")
        if axis + 'auto' in settings and not isinstance(settings[axis + 'auto'], bool):
            raise ValueError("Invalid automatic axis mode.")
        limits = settings.get(axis + 'lim')
        if limits is not None:
            if (not isinstance(limits, list) or len(limits) != 2
                    or not np.isfinite(limits).all() or limits[0] == limits[1]
                    or (scale == 'log' and min(limits) <= 0)):
                raise ValueError("Axis limits must be finite and distinct; log limits must be positive.")
        if settings.get(axis + 'auto') is False and limits is None:
            raise ValueError("Manual axes require explicit limits.")
    if settings.get('legend', 'best') not in LEGENDS:
        raise ValueError("Invalid legend position.")
    validate_plot_style(settings.get('plot_style', PLOT_STYLE))
    labels = settings.get('legend_labels', {})
    if not isinstance(labels, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in labels.items()):
        raise ValueError("Invalid legend labels.")
    for key in ('legend_order', 'legend_hidden'):
        ids = settings.get(key, [])
        if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
            raise ValueError("Invalid legend entries.")
    for key in ('cursor', 'show_fitting'):
        if key in settings and not isinstance(settings[key], bool):
            raise ValueError("Invalid plot toggle.")


def full_plot_style(saved=None):
    """A complete, independent style: defaults, then legacy shared sizes, then saved per-axis values."""
    saved = dict(saved or {})
    legacy = {key: saved.pop(key) for key in LEGACY_AXIS_KEYS if key in saved}
    style = {**deepcopy(PLOT_STYLE), **{k: v for k, v in saved.items() if not k.endswith('_axis')}}
    for key in ('x_axis', 'y_axis'):
        style[key] = {**AXIS_STYLE, **legacy, **saved.get(key, {})}
    return style


def _validate_size(size):
    if size is not None and (type(size) not in (int, float) or not 4 <= size <= 72):
        raise ValueError("Invalid plot font size.")


def validate_axis_style(style):
    if not isinstance(style, dict) or set(style) - set(AXIS_STYLE):
        raise ValueError("Invalid axis style.")
    for key in ('label_size', 'tick_size'):
        _validate_size(style.get(key))
    if not isinstance(style.get('family', ''), str):
        raise ValueError("Invalid axis font.")
    color = style.get('color', '')
    if not isinstance(color, str) or (color and not is_color_like(color)):
        raise ValueError("Invalid axis color.")
    if not all(isinstance(style.get(key, True), bool) for key in ('bold', 'italic', 'unit', 'grid', 'invert')):
        raise ValueError("Invalid axis style setting.")
    if (style.get('tick_direction', 'out') not in TICK_DIRECTIONS.values()
            or style.get('minor_ticks', 'auto') not in MINOR_TICKS.values()
            or style.get('number_format', 'auto') not in NUMBER_FORMATS.values()):
        raise ValueError("Invalid axis tick setting.")
    length = style.get('tick_length')
    if length is not None and (type(length) not in (int, float) or not 0 <= length <= 30):
        raise ValueError("Tick length must be between 0 and 30 points.")
    decimals = style.get('decimals', 2)
    if type(decimals) is not int or not 0 <= decimals <= 12:
        raise ValueError("Decimals must be a whole number from 0 to 12.")
    step = style.get('tick_step')
    if step is not None and (type(step) not in (int, float) or not np.isfinite(step) or step <= 0):
        raise ValueError("Tick spacing must be a positive number.")


def validate_plot_style(style):
    if not isinstance(style, dict) or set(style) - set(PLOT_STYLE) - set(LEGACY_AXIS_KEYS):
        raise ValueError("Invalid plot style.")
    for key in ('title_size', 'legend_size') + LEGACY_AXIS_KEYS:
        _validate_size(style.get(key))
    for key in ('x_axis', 'y_axis'):
        validate_axis_style(style.get(key, AXIS_STYLE))
    columns = style.get('legend_columns', 1)
    if type(columns) is not int or not 1 <= columns <= 6:
        raise ValueError("Invalid legend column count.")
    if not all(isinstance(style.get(key, True), bool) for key in
               ('legend_frame', 'legend_rounded', 'legend_fit_entries', 'legend_sd_entries', 'legend_residuals')):
        raise ValueError("Invalid legend setting.")
    if not isinstance(style.get('legend_title', ''), str):
        raise ValueError("Invalid legend title.")
    for key in ('legend_color', 'legend_frame_color', 'legend_background'):
        color = style.get(key, '')
        if not isinstance(color, str) or (color and not is_color_like(color)):
            raise ValueError("Invalid legend color.")
    for key, low, high in (('legend_alpha', 0, 1), ('legend_marker_scale', .25, 4), ('legend_spacing', 0, 3)):
        value = style.get(key, PLOT_STYLE[key])
        if type(value) not in (int, float) or not low <= value <= high:
            raise ValueError(f"Legend {key.removeprefix('legend_').replace('_', ' ')} must be from {low:g} to {high:g}.")


def check_label(text):
    """Raise ValueError when Matplotlib cannot draw the text, such as unbalanced $…$ math."""
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure
    figure = Figure()
    figure.text(0, 0, text)
    try:
        FigureCanvasAgg(figure).draw()
    except Exception as error:
        raise ValueError(f"Cannot draw this label: {str(error).splitlines()[-1].strip() or error}") from None


def display_values(x, y, xscale, yscale):
    """Mask whole display rows, leaving gaps and all stored arrays untouched."""
    x, y = np.array(x, dtype=float, copy=True), np.array(y, dtype=float, copy=True)
    invalid = ((np.isfinite(x) & (x <= 0)) if xscale == 'log' else np.zeros(x.shape, bool))
    invalid |= ((np.isfinite(y) & (y <= 0)) if yscale == 'log' else np.zeros(y.shape, bool))
    count = int(invalid.sum())
    invalid |= ~np.isfinite(x) | ~np.isfinite(y)
    x[invalid] = np.nan
    y[invalid] = np.nan
    return x, y, count


def validate_panels(settings):
    """Validate optional layouts while accepting pre-panel projects and views."""
    if 'panels' not in settings:
        return
    panels = settings['panels']
    if not isinstance(panels, list) or not panels:
        raise ValueError('A layout requires at least one panel.')
    active = settings.get('active_panel', 0)
    if type(active) is not int or not 0 <= active < len(panels):
        raise ValueError('Invalid active panel.')
    if not isinstance(settings.get('sync_x', False), bool):
        raise ValueError('Invalid synchronized X mode.')
    for panel in panels:
        if not isinstance(panel, dict) or not isinstance(panel.get('view'), dict):
            raise ValueError('Invalid panel state.')
        if not isinstance(panel.get('ylabel', ''), str):
            raise ValueError('Invalid panel label.')
        anchor = panel.get('legend_anchor')
        if anchor is not None and (not isinstance(anchor, list) or len(anchor) != 2
                                   or any(type(v) not in (int, float) for v in anchor)
                                   or not np.isfinite(anchor).all()):
            raise ValueError('Invalid legend position.')
        channels = panel.get('channels')
        if channels is not None:
            if not isinstance(channels, dict):
                raise ValueError('Invalid panel channels.')
            for identifier, pair in channels.items():
                if (not isinstance(identifier, str) or not isinstance(pair, list)
                        or len(pair) != 2 or any(type(c) is not int or c < 0 for c in pair)):
                    raise ValueError('Invalid panel channel assignment.')
        axes = panel['view']
        flattened = {}
        for axis in ('x', 'y', 'resy'):
            state = axes.get(axis)
            if not isinstance(state, dict):
                raise ValueError('Invalid panel axes.')
            flattened.update({axis + 'scale': state.get('scale'),
                              axis + 'auto': state.get('auto'),
                              axis + 'lim': state.get('limits')})
        validate_view(flattened)
