"""Bruker/NanoScope binary raster and force-curve import, retaining uncalibrated ADC counts.

Layout reference: NanoScope Software User Guide, File Formats / Parameters.
Physical calibration and force-volume layouts are not inferred.
"""
from collections import Counter
from copy import deepcopy
from pathlib import Path
import re

import numpy as np

from .core import Dataset
from .metadata import metadata_value


def parse_spm(data, name='Imported SPM', source=''):
    """Return one read-only table per raster or force-curve channel in a NanoScope file."""
    if data.startswith(b':NANONIS_VERSION:'):
        from .nanonis import parse_sxm
        return parse_sxm(data, name=name, source=source)
    if not data.startswith((b'\\*File list', b'\\*Force file list')):
        raise ValueError('Unsupported SPM format. Expected a Bruker/NanoScope binary image or force-curve file.')
    end = data.find(b'\\*File list end')
    if end < 0:
        raise ValueError('Incomplete SPM header: missing File list end.')
    end += len(b'\\*File list end')
    header = data[:end].decode('latin-1')
    sections, unparsed, counts = [], [], Counter()
    section = None
    for number, line in enumerate(header.splitlines(), 1):
        if line.startswith('\\*'):
            title = line[2:].strip()
            counts[title] += 1
            section = dict(name=title, occurrence=counts[title], source_line=number, entries=[])
            sections.append(section)
        else:
            match = re.match(r'\\(@\d+:)?([^:]+):(.*)', line)
            if match and section is not None:
                key = (match[1] or '') + match[2].strip()
                raw = match[3]
                value, unit = metadata_value(raw)
                section['entries'].append(dict(key=key, raw_value=raw, value=value,
                                               unit=unit, source_line=number))
            elif line.strip():
                unparsed.append(dict(source_line=number, text=line))
    images = [s for s in sections if s['name'].lower() in ('ciao image list', 'image list')]
    forces = [s for s in sections if s['name'].lower() == 'ciao force image list']
    if images and forces:
        raise ValueError('SPM force-volume files are not supported yet.')
    images = images or forces
    if not images:
        raise ValueError('No supported image or force-curve channels found in the SPM file.')
    version_match = re.search(r'^\\Version:\s*(0x[0-9a-fA-F]+)', header, re.MULTILINE)
    version = int(version_match[1], 16) if version_match else 0
    datasets, spans = [], []
    for index, section in enumerate(images, 1):
        fields = {e['key']: e['raw_value'].strip() for e in section['entries']}

        def integer(key):
            try:
                return int(fields[key])
            except (KeyError, ValueError):
                raise ValueError(f'SPM channel {index}: missing or invalid {key}.') from None

        offset, length = integer('Data offset'), integer('Data length')
        is_force = section in forces
        segments = []
        if is_force:
            try:
                segments = [int(v) for v in fields['Samps/line'].split()]
            except (KeyError, ValueError):
                raise ValueError(f'SPM channel {index}: invalid force segment lengths.') from None
            if not segments or any(v <= 0 for v in segments):
                raise ValueError(f'SPM channel {index}: invalid force segment lengths.')
            width, height = sum(segments), 1
        else:
            width = integer('Samps/line' if 'Samps/line' in fields else 'Samples/line')
            height = integer('Number of lines')
        size = integer('Bytes/pixel')
        if size not in (2, 4):
            raise ValueError(f'SPM channel {index}: only 16-bit and 32-bit integer images are supported.')
        # NanoScope >= 9.2 stores 32-bit samples even when Bytes/pixel says 2.
        # https://github.com/pycroscopy/pycroscopy/issues/204
        if version >= 0x09200000:
            size = 4
        if width <= 0 or height <= 0 or length != width * height * size:
            raise ValueError(f'SPM channel {index}: image dimensions and data length disagree; unsupported layout.')
        if offset < end or offset + length > len(data):
            raise ValueError(f'SPM channel {index}: image data is truncated or overlaps the header.')
        if any(offset < stop and offset + length > start for start, stop in spans):
            raise ValueError(f'SPM channel {index}: overlapping image data blocks.')
        spans.append((offset, offset + length))
        label = fields.get('@4:Image Data' if is_force else '@2:Image Data', fields.get('Image Data', f'Channel {index}'))
        quoted = re.findall(r'"([^"]+)"', label)
        label = quoted[-1] if quoted else label
        if fields.get('Line Direction'):
            label += f" ({fields['Line Direction']})"
        signal = np.frombuffer(data, dtype=f'<i{size}', count=width * height, offset=offset)
        sample = np.arange(len(signal))
        if is_force:
            values = np.column_stack((sample, np.repeat(np.arange(len(segments)), segments),
                                      np.concatenate([np.arange(n) for n in segments]), signal))
            columns = ['Sample', 'Segment', 'Sample in segment', f'{label} (raw counts)']
        else:
            values = np.column_stack((sample, sample % width, sample // width, signal))
            columns = ['Sample', 'X pixel', 'Y pixel', f'{label} (raw counts)']
        dataset = Dataset(f'{name} — {index}: {label}',
                          columns,
                          values, source=source, source_text=header, ycol=3,
                          column_units=['', '', '', 'raw counts'])
        dataset.instrument_metadata = dict(format='nanoscope', version=1,
            source_dataset_id=dataset.id, sections=deepcopy(sections), unparsed=deepcopy(unparsed))
        if not is_force:
            dataset.instrument_metadata['image_channel_index'] = index - 1
        datasets.append(dataset)
    return datasets


def load_spm(path):
    path = Path(path)
    return parse_spm(path.read_bytes(), name=path.stem, source=str(path.resolve()))
