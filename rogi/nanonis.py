"""Nanonis SXM scans; preserve stored values, units, and acquisition order.

Layout reference: https://github.com/ethz-micro/matlab_nanonis/blob/master/Manual/sxm.tex
"""
from copy import deepcopy
import re
import numpy as np
from .core import Dataset


def parse_sxm(data, name='Imported scan', source=''):
    end = data.find(b':SCANIT_END:')
    if end < 0:
        raise ValueError('Incomplete Nanonis SXM header: missing SCANIT_END.')
    end += len(b':SCANIT_END:')
    start = data.find(b'\x1a\x04', end)
    if start < 0 or data[end:start].strip():
        raise ValueError('Missing Nanonis SXM binary data marker.')
    header = data[:end].decode('latin-1')
    tags, sections = {}, []
    current = None
    for number, line in enumerate(header.splitlines(), 1):
        if re.fullmatch(r':[^:]+:', line.strip()):
            current = line.strip()[1:-1]
            if current in tags:
                raise ValueError(f'Duplicate Nanonis header field: {current}.')
            tags[current] = []
            sections.append(dict(name=current, occurrence=1, source_line=number, entries=[]))
        elif current is not None and line.strip():
            tags[current].append(line)
            sections[-1]['entries'].append(dict(key='Value', raw_value=line, value=line,
                                                unit=None, source_line=number))
    try:
        width, height = map(int, ' '.join(tags['SCAN_PIXELS']).split())
        encoding = ' '.join(tags['SCANIT_TYPE']).split()
        rows = tags['DATA_INFO']
        def split(line):
            return [v.strip() for v in line.strip().split('\t')] if '\t' in line else line.split()
        fields = split(rows[0])
        names = [fields.index(key) for key in ('Name', 'Unit', 'Direction')]
    except (KeyError, ValueError, IndexError):
        raise ValueError('Missing or invalid Nanonis SCAN_PIXELS, SCANIT_TYPE, or DATA_INFO.') from None
    if width <= 0 or height <= 0:
        raise ValueError('Nanonis scan dimensions must be positive.')
    if encoding not in (['FLOAT', 'MSBFIRST'], ['FLOAT', 'LSBFIRST']):
        raise ValueError('Only Nanonis FLOAT MSBFIRST/LSBFIRST scans are supported.')
    channels = []
    for row in rows[1:]:
        cells = split(row)
        if len(cells) != len(fields):
            raise ValueError('Invalid Nanonis DATA_INFO channel row.')
        label, unit, direction = (cells[i] for i in names)
        if direction not in ('both', 'forward', 'backward'):
            raise ValueError(f'Unsupported Nanonis channel direction: {direction}.')
        for scan_direction in ('forward', 'backward') if direction == 'both' else (direction,):
            channels.append((label, unit, scan_direction))
    if not channels:
        raise ValueError('No Nanonis scan channels found.')
    offset, count = start + 2, width * height
    if len(data) - offset != count * 4 * len(channels):
        raise ValueError('Nanonis scan data length disagrees with dimensions/channels; file may be incomplete.')
    dtype = '>f4' if encoding[1] == 'MSBFIRST' else '<f4'
    values = np.frombuffer(data, dtype=dtype, offset=offset).reshape(len(channels), count)
    datasets = []
    sample = np.arange(count)
    for i, (label, unit, direction) in enumerate(channels):
        title = f'{label} ({direction})'
        signal_label = f'{title} ({unit})' if unit else title
        dataset = Dataset(f'{name} — {i+1}: {title}',
                          ['Sample', 'X pixel', 'Y pixel', signal_label],
                          np.column_stack((sample, sample % width, sample // width, values[i])),
                          source=source, source_text=header, ycol=3, column_units=['', '', '', unit])
        dataset.instrument_metadata = dict(format='nanonis_sxm', version=1,
            source_dataset_id=dataset.id, sections=deepcopy(sections), unparsed=[])
        datasets.append(dataset)
    return datasets
