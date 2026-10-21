"""Portable, data-independent single-signal pipeline presets."""
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
from .analysis import POLICIES, validate_operations, analyze


def make_preset(operations):
    validate_operations(operations)
    return dict(version=1, operations=deepcopy(operations), policies=deepcopy(POLICIES))


def validate_presets(presets):
    if not isinstance(presets, dict):
        raise ValueError('Invalid pipeline presets.')
    for name, preset in presets.items():
        if not isinstance(name, str) or not name.strip() or name != name.strip():
            raise ValueError('Preset names must be nonempty and trimmed.')
        if (not isinstance(preset, dict) or set(preset) != {'version', 'operations', 'policies'}
                or type(preset['version']) is not int or preset['version'] != 1
                or preset['policies'] != POLICIES):
            raise ValueError('Unsupported pipeline preset or numerical policies.')
        validate_operations(preset['operations'])


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
