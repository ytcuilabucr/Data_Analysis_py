"""Plot presentation validation and non-destructive logarithmic masking."""
import numpy as np
from matplotlib.colors import is_color_like

MARKERS = {'Auto': '', 'None': 'None', 'Circle': 'o', 'Square': 's',
           'Triangle': '^', 'Diamond': 'D', 'Plus': '+', 'Cross': 'x'}
LEGENDS = ('best', 'upper right', 'upper left', 'lower left', 'lower right',
           'center left', 'center right', 'lower center', 'upper center', 'center', 'hidden')


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
    for key in ('cursor', 'show_fitting'):
        if key in settings and not isinstance(settings[key], bool):
            raise ValueError("Invalid plot toggle.")


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
