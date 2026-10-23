"""Resolve physical scan extents from retained instrument headers."""
import re
import numpy as np

NUMBER = r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?'
UNITS = {'m': 1., 'mm': 1e-3, 'um': 1e-6, 'µm': 1e-6, 'μm': 1e-6,
         '~m': 1e-6, 'nm': 1e-9, 'pm': 1e-12}


def _fields(section):
    return {e['key'].lower(): e['raw_value'].strip() for e in section['entries']}


def _size(fields):
    text = fields.get('scan size', '')
    match = re.fullmatch(rf'({NUMBER})\s+(?:({NUMBER})\s+)?([^\s]+)', text)
    if not match or match[3] not in UNITS:
        return None
    x = float(match[1])
    if match[2] is not None:
        y = float(match[2])
    else:
        ratio = fields.get('aspect ratio', '')
        parts = ratio.split(':')
        try:
            aspect = float(parts[0]) / float(parts[1]) if len(parts) == 2 else float(ratio)
            if not np.isfinite(aspect) or aspect <= 0:
                return None
            y = x / aspect
        except (ValueError, ZeroDivisionError):
            return None
    return x * UNITS[match[3]], y * UNITS[match[3]]


def scan_dimensions(dataset):
    """Return scan widths in metres, or None when calibration is unknown.

    New Bruker imports identify the channel's header section explicitly. Older
    projects can resolve it from the unchanged signal column, including direction.
    """
    if 'channels' in dataset.instrument_metadata:
        from .scanfile import channel_views
        views = channel_views(dataset)
        selected = next((v for v in views if v.id == f'{dataset.id}:{dataset.ycol}'), views[0])
        return scan_dimensions(selected)
    metadata = dataset.instrument_metadata
    sections = metadata.get('sections', [])
    dimensions = None
    if metadata.get('format') == 'nanonis_sxm':
        ranges = [s for s in sections if s['name'] == 'SCAN_RANGE']
        if len(ranges) == 1:
            try:
                dimensions = tuple(float(v) for e in ranges[0]['entries']
                                   for v in e['raw_value'].split())
            except ValueError:
                return None
    elif metadata.get('format') == 'nanoscope':
        images = [s for s in sections if s['name'].lower() in ('ciao image list', 'image list')]
        index = metadata.get('image_channel_index')
        candidates = []
        if isinstance(index, int) and 0 <= index < len(images):
            candidates = [images[index]]
        else:
            for section in images:
                fields = _fields(section)
                label = fields.get('@2:image data', fields.get('image data', ''))
                quoted = re.findall(r'"([^"]+)"', label)
                label = quoted[-1] if quoted else label
                if fields.get('line direction'):
                    label += f" ({fields['line direction']})"
                if dataset.columns[-1] == f'{label} (raw counts)':
                    candidates.append(section)
        sizes = [_size(_fields(s)) for s in candidates]
        if sizes and all(size is not None and size == sizes[0] for size in sizes):
            dimensions = sizes[0]
        elif candidates and not any('scan size' in _fields(s) for s in candidates):
            # Use a shared scan size only if the channel does not specify one.
            scans = [_size(_fields(s)) for s in sections if s['name'].lower() == 'ciao scan list']
            if len(scans) == 1:
                dimensions = scans[0]
    if dimensions is None or len(dimensions) != 2:
        return None
    if not np.isfinite(dimensions).all() or min(dimensions) <= 0:
        return None
    return dimensions


def _length_display(dimensions):
    largest = max(dimensions)
    return ((1., 'm') if largest >= 1 else (1e-3, 'mm') if largest >= 1e-3
            else (1e-6, 'µm') if largest >= 1e-6 else (1e-9, 'nm'))


def image_geometry(dataset, shape):
    """Return pixel-edge extent and axis labels; do not resample observations."""
    dimensions = scan_dimensions(dataset)
    if dimensions is None:
        height, width = shape
        return (-.5, width-.5, -.5, height-.5), 'X pixel', 'Y pixel'
    scale, unit = _length_display(dimensions)
    return (0., dimensions[0]/scale, 0., dimensions[1]/scale), f'X ({unit})', f'Y ({unit})'


def coordinate_unit(dataset):
    """Unit of image_geometry's extent: a length unit, or 'pixel' without calibration."""
    dimensions = scan_dimensions(dataset)
    return 'pixel' if dimensions is None else _length_display(dimensions)[1]
