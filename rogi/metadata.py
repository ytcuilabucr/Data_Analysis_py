"""Spectrum metadata from observed section/key-value headers; no inferred units."""
from collections import Counter
from datetime import datetime
import math
import re

NUMBER = re.compile(r'^([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)(?:\s+(.+))?$')
MISSING = ('', 'na', 'nan', 'n/a')


def metadata_value(raw):
    token = raw.strip()
    if not token:
        return None, None
    match = NUMBER.fullmatch(token)
    if match:
        number = float(match[1])
        if math.isfinite(number):
            return number, match[2]
    return token, None


def attach_spectrum_metadata(dataset, text):
    lines = text.removeprefix('\ufeff').splitlines()
    marker = next((i for i, line in enumerate(lines) if line.strip() == '[Data]'), None)
    if marker is None:
        return
    sections, unparsed = [], []
    occurrences = Counter()
    section = None
    for number, line in enumerate(lines[:marker], 1):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith('[') and stripped.endswith(']'):
            name = stripped[1:-1]
            occurrences[name] += 1
            section = dict(name=name, occurrence=occurrences[name], source_line=number, entries=[])
            sections.append(section)
        elif ':' in line and section is not None:
            key, raw = line.split(':', 1)
            value, unit = metadata_value(raw)
            section['entries'].append(dict(key=key.strip(), raw_value=raw, value=value,
                                           unit=unit, source_line=number))
        else:
            unparsed.append(dict(source_line=number, text=line))
    dataset.instrument_metadata = dict(format='spectrum', version=1, source_dataset_id=dataset.id,
                                       sections=sections, unparsed=unparsed)
    body = [(i + 1, line.split('\t')) for i, line in enumerate(lines[marker + 1:], marker + 1) if line.strip()]
    if not body:
        return
    headers = body[0][1]
    while headers and not headers[-1].strip():
        headers.pop()
    streams = []
    for column, header in enumerate(headers):
        name = header.strip()
        if name not in ('Time', 'Time_Timestamp'):
            continue
        raw = [row[column] for _, row in body[1:]]
        def is_number(token):
            try:
                float(token)
                return True
            except ValueError:
                return False
        numeric = name == 'Time_Timestamp' or all(
            value.strip().lower() in MISSING or is_number(value.strip()) for value in raw)
        parsed, invalid = [], []
        for row, token in enumerate(raw, 1):
            token = token.strip()
            value = None
            if token.lower() not in MISSING:
                try:
                    if numeric:
                        value = float(token)
                        if not math.isfinite(value):
                            raise ValueError()
                    else:
                        value = datetime.strptime(token, '%Y/%m/%d_%H:%M:%S').isoformat()
                except ValueError:
                    value = None
                    invalid.append(row)
            parsed.append(value)
        streams.append(dict(name=name, source_column=column + 1,
                            kind='numeric' if numeric else 'datetime',
                            raw=raw, values=parsed, invalid_rows=invalid))
    dataset.timestamps = streams
    validate_metadata(dataset)


def validate_metadata(dataset):
    metadata, streams = dataset.instrument_metadata, dataset.timestamps
    if not isinstance(metadata, dict) or not isinstance(streams, list):
        raise ValueError("Invalid dataset metadata/timestamps.")
    if metadata:
        if (metadata.get('format') not in ('spectrum', 'nanoscope', 'nanonis_sxm') or metadata.get('version') != 1
                or not isinstance(metadata.get('source_dataset_id'), str)
                or not isinstance(metadata.get('sections'), list)
                or not isinstance(metadata.get('unparsed'), list)):
            raise ValueError("Invalid instrument metadata schema.")
        if 'channels' in metadata:
            channels = metadata['channels']
            if not isinstance(channels, list) or not channels:
                raise ValueError('Invalid instrument channel layout.')
            signals = set()
            for channel in channels:
                if not isinstance(channel, dict):
                    raise ValueError('Invalid instrument channel layout.')
                signal = channel.get('signal_column')
                coords = channel.get('coordinate_columns')
                rows = channel.get('rows')
                names = channel.get('coordinate_names')
                index = channel.get('image_channel_index')
                if (type(signal) is not int or not 0 <= signal < len(dataset.columns)
                        or signal in signals or not isinstance(coords, list) or len(coords) != 3
                        or any(type(c) is not int or not 0 <= c < len(dataset.columns) for c in coords)
                        or len(set(coords + [signal])) != 4
                        or type(rows) is not int or not 0 < rows <= len(dataset.values)
                        or not isinstance(names, list) or len(names) != 3
                        or not all(isinstance(n, str) for n in names)
                        or not isinstance(channel.get('label'), str)
                        or (index is not None and (type(index) is not int or index < 0))):
                    raise ValueError('Invalid instrument channel layout.')
                signals.add(signal)
        for section in metadata['sections']:
            if (not isinstance(section, dict) or not isinstance(section.get('name'), str)
                    or not isinstance(section.get('occurrence'), int) or section['occurrence'] < 1
                    or not isinstance(section.get('source_line'), int) or section['source_line'] < 1
                    or not isinstance(section.get('entries'), list)):
                raise ValueError("Invalid instrument metadata section.")
            for entry in section['entries']:
                if (not isinstance(entry, dict) or not isinstance(entry.get('key'), str)
                        or not isinstance(entry.get('raw_value'), str)
                        or not isinstance(entry.get('source_line'), int) or entry['source_line'] < 1
                        or (entry.get('unit') is not None and not isinstance(entry['unit'], str))
                        or not scalar(entry.get('value'))):
                    raise ValueError("Invalid instrument metadata field.")
        for line in metadata['unparsed']:
            if (not isinstance(line, dict) or not isinstance(line.get('text'), str)
                    or not isinstance(line.get('source_line'), int) or line['source_line'] < 1):
                raise ValueError("Invalid unparsed metadata line.")
    for stream in streams:
        if (not isinstance(stream, dict) or not isinstance(stream.get('name'), str)
                or not isinstance(stream.get('source_column'), int) or stream['source_column'] < 1
                or stream.get('kind') not in ('numeric', 'datetime')
                or not isinstance(stream.get('raw'), list) or not isinstance(stream.get('values'), list)
                or len(stream['raw']) != len(dataset.values) or len(stream['values']) != len(dataset.values)
                or not all(isinstance(value, str) for value in stream['raw'])
                or not isinstance(stream.get('invalid_rows'), list)
                or any(not isinstance(row, int) or not 1 <= row <= len(dataset.values) for row in stream['invalid_rows'])):
            raise ValueError("Invalid timestamp stream or row alignment.")
        for value in stream['values']:
            if value is not None:
                if stream['kind'] == 'numeric':
                    if not isinstance(value, (int, float)) or not math.isfinite(value):
                        raise ValueError("Invalid numeric timestamp.")
                else:
                    if not isinstance(value, str):
                        raise ValueError("Invalid parsed timestamp.")
                    try:
                        datetime.strptime(value, '%Y-%m-%dT%H:%M:%S')
                    except ValueError as error:
                        raise ValueError("Invalid parsed timestamp.") from error


def scalar(value):
    return value is None or isinstance(value, str) or (isinstance(value, (int, float)) and math.isfinite(value))


def metadata_fields(dataset):
    """Unambiguous section/field occurrences, suitable for search and grouping."""
    fields = {}
    for section in dataset.instrument_metadata.get('sections', []):
        counts = Counter()
        for entry in section['entries']:
            counts[entry['key']] += 1
            key = f"{section['name']}[{section['occurrence']}].{entry['key']}[{counts[entry['key']]}]"
            if entry['raw_value'].strip():
                fields[key] = entry['raw_value'].strip()
    for stream in dataset.timestamps:
        key = f"{stream['name']} (source column {stream['source_column']})"
        for suffix, index in (('first', 0), ('last', -1)):
            if stream['raw'] and stream['raw'][index].strip().lower() not in MISSING:
                fields[f"{key}.{suffix}"] = stream['raw'][index].strip()
        if stream['kind'] == 'datetime' and stream['values'] and stream['values'][0] is not None:
            fields[f"{key}.date (first row)"] = stream['values'][0][:10]
    return fields


def metadata_search_text(dataset):
    fields = metadata_fields(dataset)
    parts = [f"{key}={value}" for key, value in fields.items()]
    for section in dataset.instrument_metadata.get('sections', []):
        parts.append(section['name'])
        parts.extend(f"{entry['key']}={entry['value']} {entry['unit'] or ''}"
                     for entry in section['entries'] if entry['value'] is not None)
    for stream in dataset.timestamps:
        parts.extend(stream['raw'])
        parts.extend(str(value) for value in stream['values'] if value is not None)
    return ' '.join(parts)


def metadata_sort_key(value):
    """Numeric values (including units) sort numerically; other values alphabetically."""
    match = NUMBER.fullmatch(value)
    if match and math.isfinite(float(match[1])):
        return (0, float(match[1]), (match[2] or '').casefold(), value)
    return (1, value.casefold(), value)


def acquisition_timestamp(dataset):
    """Earliest parsed instrument datetime; never infer a numeric epoch or use stat()."""
    values = [value for stream in dataset.timestamps if stream['kind'] == 'datetime'
              for value in stream['values'] if value is not None]
    return min(values) if values else None


def channel_count(dataset):
    """Stored signal channels for scans; stored table columns for other datasets."""
    return len(dataset.instrument_metadata.get('channels') or dataset.columns)
