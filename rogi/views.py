"""Named presentation snapshots, independent of dataset order and contents."""
from .plotting import validate_view
import numpy as np


def validate_saved_views(views):
    try:
        _validate_saved_views(views)
    except (KeyError, TypeError, AttributeError, OverflowError) as error:
        raise ValueError(f'Invalid saved view: {error}') from error


def _validate_saved_views(views):
    if not isinstance(views, dict):
        raise ValueError('Invalid saved views.')
    for name, view in views.items():
        if not isinstance(name, str) or not name.strip() or not isinstance(view, dict):
            raise ValueError('Invalid saved view name or snapshot.')
        if view.get('kind') == 'spectrum_map':
            from .maps import validate_recipe
            validate_recipe(view.get('recipe'))
            continue
        plot = view['plot']
        validate_view(plot)
        for key in ('title', 'xlabel', 'ylabel'):
            if not isinstance(plot.get(key, ''), str):
                raise ValueError('Invalid saved view label.')
        if view['mode'] not in (0, 1):
            raise ValueError('Invalid saved view mode.')
        if view['active'] is not None and not isinstance(view['active'], str):
            raise ValueError('Invalid active dataset ID.')
        if not isinstance(view['datasets'], dict):
            raise ValueError('Invalid saved dataset state.')
        for identifier, state in view['datasets'].items():
            if not isinstance(identifier, str) or not isinstance(state['visible'], bool):
                raise ValueError('Invalid saved dataset visibility.')
            for key in ('xcol', 'ycol'):
                if type(state[key]) is not int or state[key] < 0:
                    raise ValueError('Invalid saved channel.')
        image = view['image']
        if image['palette'] not in ('viridis', 'gray', 'afmhot', 'inferno', 'magma', 'plasma', 'cividis', 'coolwarm'):
            raise ValueError('Invalid saved image palette.')
        if image['mode'] not in ('Full range', 'Percentile', 'Manual'):
            raise ValueError('Invalid saved image contrast.')
        low, high = float(image['low']), float(image['high'])
        if not np.isfinite([low, high]).all():
            raise ValueError('Invalid saved image limits.')
        if image['mode'] == 'Manual' and low >= high:
            raise ValueError('Invalid saved image limits.')
        if image['mode'] == 'Percentile' and not 0 <= low < high <= 100:
            raise ValueError('Invalid saved percentiles.')
        if type(image.get('gamma', 0)) is not int or not -100 <= image.get('gamma', 0) <= 100:
            raise ValueError('Invalid saved image gamma.')
        if not isinstance(image.get('invert', False), bool):
            raise ValueError('Invalid saved image color inversion.')
        if image['compare'] is not None and not isinstance(image['compare'], str):
            raise ValueError('Invalid image comparison ID.')
        if not isinstance(image['channels'], dict) or not all(
                isinstance(k, str) and isinstance(v, str) for k, v in image['channels'].items()):
            raise ValueError('Invalid image channels.')
        if not isinstance(image['zoom'], dict):
            raise ValueError('Invalid image zoom.')
        for identifier, limits in image['zoom'].items():
            if not isinstance(identifier, str) or not isinstance(limits, dict):
                raise ValueError('Invalid image zoom.')
            if limits.get('xlim') is None or limits.get('ylim') is None:
                raise ValueError('Image zoom requires both axis limits.')
            validate_view(limits)
