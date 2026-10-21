"""One dataset per instrument file, with independently addressable channels."""
from collections import defaultdict
from copy import copy, deepcopy
from pathlib import Path
import re
import numpy as np
from .core import Dataset
from .grouping import group_path, path_key


def bundle_channels(channels, name=None):
    if not channels:
        raise ValueError('Select at least one channel.')
    first = channels[0]
    count = max(len(d.values) for d in channels)
    columns, arrays, layouts = [], [], []
    coordinates = []

    def append(label, values):
        base, suffix = label, 2
        while label in columns:
            label = f'{base} [{suffix}]'
            suffix += 1
        columns.append(label)
        padded = np.full(count, np.nan)
        padded[:len(values)] = values
        arrays.append(padded)
        return len(columns) - 1

    for d in channels:
        if len(d.columns) != 4:
            raise ValueError('Expected a four-column instrument channel.')
        coord = d.values[:, :3]
        indices = next((indices for names, values, indices in coordinates
                        if names == d.columns[:3] and np.array_equal(values, coord, equal_nan=True)), None)
        if indices is None:
            indices = [append(label, coord[:, i]) for i, label in enumerate(d.columns[:3])]
            coordinates.append((d.columns[:3], coord, indices))
        signal = append(d.columns[3], d.values[:, 3])
        layouts.append(dict(signal_column=signal, coordinate_columns=indices,
                            coordinate_names=d.columns[:3], label=d.columns[3], rows=len(d.values),
                            image_channel_index=d.instrument_metadata.get('image_channel_index')))
    metadata = deepcopy(first.instrument_metadata)
    metadata.pop('image_channel_index', None)
    metadata['channels'] = layouts
    result = Dataset(name or (Path(first.source).stem if first.source else first.name.split(' — ')[0]),
                     columns, np.column_stack(arrays), source=first.source, source_text=first.source_text,
                     group=first.group, group_path=deepcopy(first.group_path),
                     ycol=layouts[0]['signal_column'], instrument_metadata=metadata)
    result.instrument_metadata['source_dataset_id'] = result.id
    return result


def channel_views(dataset):
    """Lightweight read-only views for plotting; table editing stays on the file."""
    layouts = dataset.instrument_metadata.get('channels')
    if layouts is None:
        return [dataset]
    views = []
    for layout in layouts:
        view = copy(dataset)
        column = layout['signal_column']
        view.id = f'{dataset.id}:{column}'
        view.name = f'{dataset.name} — {dataset.columns[column]}'
        view.columns = layout['coordinate_names'] + [layout['label']]
        if dataset.column_units:
            view.column_units = [dataset.column_units[i] for i in layout['coordinate_columns'] + [column]]
        view.values = dataset.values[:layout['rows'], layout['coordinate_columns'] + [column]]
        view.values.setflags(write=False)
        view.xcol, view.ycol = 0, 3
        view.instrument_metadata = dict(dataset.instrument_metadata)
        view.instrument_metadata.pop('channels', None)
        index = layout.get('image_channel_index')
        if index is not None:
            view.instrument_metadata['image_channel_index'] = index
        views.append(view)
    return views


def consolidate_legacy(datasets, selected_id=None):
    """Combine pristine legacy channel imports; retain edited/fitted dependencies."""
    grouped = defaultdict(list)
    protected = {d.parent for d in datasets if d.parent}
    for d in datasets:
        if (d.source and Path(d.source).suffix.lower() in ('.spm', '.sxm')
                and d.instrument_metadata.get('format') in ('nanoscope', 'nanonis_sxm')):
            grouped[(d.source, path_key(group_path(d)))].append(d)
    replacements, consumed = {}, set()
    for members in grouped.values():
        if any(not d.raw or d.fit or d.edits or d.revision or d.id in protected
               or 'channels' in d.instrument_metadata or len(d.columns) != 4 for d in members):
            continue
        # Repeated imports of the same file must not be silently conflated.
        numbers = [re.search(r' — (\d+):', d.name) for d in members]
        if not all(numbers) or len({m[1] for m in numbers}) != len(members):
            continue
        if any(d.source_text != members[0].source_text for d in members):
            continue
        result = bundle_channels(members)
        result.id = members[0].id
        result.instrument_metadata['source_dataset_id'] = result.id
        result.visible = any(d.visible for d in members)
        result.color, result.marker, result.style = members[0].color, members[0].marker, members[0].style
        selected = next((i for i, d in enumerate(members) if d.id == selected_id), None)
        if selected is not None:
            selected_id = result.id
            result.ycol = result.instrument_metadata['channels'][selected]['signal_column']
        replacements[members[0].id] = result
        consumed.update(d.id for d in members[1:])
    return [replacements.get(d.id, d) for d in datasets if d.id not in consumed], selected_id
