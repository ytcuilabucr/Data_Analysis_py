"""Portable, data-independent single-signal pipeline presets."""
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import numpy as np
from .analysis import POLICIES, validate_operations, analyze

PALETTES = ('viridis', 'gray', 'afmhot', 'inferno', 'magma', 'plasma', 'cividis', 'coolwarm')
DEFAULT_DISPLAY = dict(palette='viridis', invert=False, brightness=0, contrast=0, gamma=1.)


def validate_display(display):
    """Image display settings; brightness/contrast are relative to each map's data range."""
    if not isinstance(display, dict) or set(display) != set(DEFAULT_DISPLAY):
        raise ValueError('Invalid image display settings.')
    if display['palette'] not in PALETTES or type(display['invert']) is not bool:
        raise ValueError('Unknown image palette or invert flag.')
    for key in ('brightness', 'contrast'):
        if type(display[key]) is not int or not -100 <= display[key] <= 100:
            raise ValueError(f'Image {key} must be an integer from -100 to 100.')
    if type(display['gamma']) not in (int, float) or not .25 <= display['gamma'] <= 4:
        raise ValueError('Image gamma must be between 0.25 and 4.')


def display_limits(values, display):
    """Color limits from the finite data range, matching the 2D Map Brightness/Contrast sliders."""
    finite = values[np.isfinite(values)]
    s0, s1 = (float(finite.min()), float(finite.max())) if finite.size else (0., 1.)
    if s0 == s1:
        delta = max(abs(s0) * 1e-6, 1e-12)
        s0, s1 = s0 - delta, s1 + delta
    centre = s0 + (s1 - s0) * (.5 - display['brightness'] / 200)
    half = (s1 - s0) * 2 ** (-display['contrast'] / 50) / 2
    return centre - half, centre + half


def make_preset(operations, display=None):
    validate_operations(operations)
    preset = dict(version=1, operations=deepcopy(operations), policies=deepcopy(POLICIES))
    if display is not None:
        validate_display(display)
        preset.update(version=2, display=deepcopy(display))
    return preset


def validate_presets(presets):
    if not isinstance(presets, dict):
        raise ValueError('Invalid pipeline presets.')
    for name, preset in presets.items():
        if not isinstance(name, str) or not name.strip() or name != name.strip() or '\x00' in name:
            raise ValueError('Preset names must be nonempty, trimmed, and free of NUL characters.')
        # Version 2 adds image display settings; version 1 presets remain valid.
        keys = {'version', 'operations', 'policies'}
        if (not isinstance(preset, dict) or type(preset.get('version')) is not int
                or preset['version'] not in (1, 2)
                or set(preset) != (keys | {'display'} if preset['version'] == 2 else keys)
                or preset['policies'] != POLICIES):
            raise ValueError('Unsupported pipeline preset or numerical policies.')
        validate_operations(preset['operations'])
        if preset['version'] == 2:
            validate_display(preset['display'])


def save_presets(path, presets):
    validate_presets(presets)
    content = json.dumps(dict(format='rogi-pipeline-presets', version=1, presets=presets),
                         indent=2, allow_nan=False)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=Path(path).parent, delete=False) as stream:
            temporary = stream.name
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def load_presets(path):
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(data, dict) or data.get('format') != 'rogi-pipeline-presets' or data.get('version') != 1:
        raise ValueError('Unsupported pipeline preset file.')
    presets = data.get('presets')
    validate_presets(presets)
    return presets


def apply_preset(datasets, preset, name):
    """Compute every result before returning; callers commit the batch together."""
    validate_presets({name: preset})
    if not datasets:
        raise ValueError('Select at least one dataset.')
    results = []
    for dataset in datasets:
        try:
            results.append(analyze(dataset, preset['operations'], name=f'{dataset.name} ({name})'))
        except ValueError as error:
            raise ValueError(f'{dataset.name}: {error}') from error
    return results


DESTINATIONS = ('source', 'subgroup', 'group')


def place_results(sources, results, destination='source', name=''):
    """Assign result groups in place: 'source' keeps each input's group, 'subgroup'
    nests results under it, 'group' collects all results in one manual group."""
    from .grouping import group_path, path_label
    if destination not in DESTINATIONS:
        raise ValueError('Unknown result destination.')
    name = name.strip()
    if destination != 'source' and not name:
        raise ValueError('Enter a group name for the results.')
    for source, result in zip(sources, results, strict=True):
        if destination == 'group':
            result.group, result.group_path = name, []
        elif destination == 'subgroup':
            path = group_path(source)
            if path:
                result.group_path = path + [{'field': None, 'value': name}]
                result.group = path_label(result.group_path)
            else:
                result.group, result.group_path = name, []
    return results
