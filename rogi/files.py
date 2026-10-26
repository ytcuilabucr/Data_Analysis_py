"""Finding and reading data files without Qt: folder listings, batch import and naming.

The Files panel, Open… and folder conversion share these readers, so a file
imports the same way whichever command brought it in.
"""
import csv
import io
import os
import re
from datetime import datetime
from pathlib import Path
import numpy as np
from .core import parse_text, parse_dat, spectrum_table
from .metadata import attach_spectrum_metadata
from .spm import load_spm
from .scanfile import bundle_channels

# Kind -> suffixes; the Files panel offers one type filter per kind.
KINDS = {'project': ('.h5', '.hdf5', '.json'),
         'dat': ('.dat',),
         'table': ('.csv', '.tsv', '.txt'),
         'spm': ('.spm',),
         'sxm': ('.sxm',)}
KIND_LABELS = {'project': 'Projects', 'dat': 'DAT', 'table': 'CSV/TSV/TXT', 'spm': 'SPM', 'sxm': 'SXM'}
DATA_SUFFIXES = {s for kind, suffixes in KINDS.items() if kind != 'project' for s in suffixes}
PROJECT_SUFFIXES = set(KINDS['project'])
SCAN_SUFFIXES = {'.spm', '.sxm'}
NAME_TOKENS = ('stem', 'n', 'num', 'folder')


def file_kind(path):
    suffix = Path(path).suffix.lower()
    return next((kind for kind, suffixes in KINDS.items() if suffix in suffixes), None)


def is_project(path):
    return Path(path).suffix.lower() in PROJECT_SUFFIXES


def natural_key(text):
    """Order run numbers numerically: sweep_2 before sweep_10."""
    return [(0, int(part), '') if part.isdigit() else (1, 0, part.lower())
            for part in re.split(r'(\d+)', str(text)) if part]


def scan_folder(folder, kinds=None, recursive=False):
    """Supported files in folder, naturally sorted by relative path.

    Directory symlinks are not followed and hidden files are skipped.
    """
    folder = Path(folder)
    if not folder.is_dir():
        raise ValueError(f'Folder does not exist: {folder}')
    kinds = set(KINDS) if kinds is None else set(kinds)
    suffixes = {s for kind in kinds for s in KINDS[kind]}
    found = []
    for directory, subdirectories, names in os.walk(folder, followlinks=False):
        subdirectories[:] = [d for d in subdirectories if not d.startswith('.')] if recursive else []
        found += [Path(directory) / name for name in names
                  if not name.startswith('.') and Path(name).suffix.lower() in suffixes]
    return sorted(found, key=lambda path: natural_key(path.relative_to(folder).as_posix()))


def resolved(path):
    try:
        return str(Path(path).resolve())
    except OSError:
        return str(path)


def loaded_sources(datasets):
    """Resolved source paths of datasets already in the project."""
    return {resolved(d.source) for d in datasets if d.source}


def read_text_import(path):
    path = Path(path)
    text = path.read_bytes().decode('utf-8')
    table = spectrum_table(text) if path.suffix.lower() == '.dat' else None
    return text, table


def parse_text_import(path, text, table_text, delimiter, header, selected):
    path = Path(path)
    dataset = parse_text(table_text, delimiter, header, selected, path.stem, resolved(path))
    dataset.source_text = text
    if path.suffix.lower() == '.dat':
        attach_spectrum_metadata(dataset, text)
    return dataset


def read_data_file(path):
    """Read one file with every channel and an automatically detected delimiter."""
    path = Path(path)
    if path.suffix.lower() in SCAN_SUFFIXES:
        return bundle_channels(load_spm(path), name=path.stem)
    text = path.read_bytes().decode('utf-8')
    if path.suffix.lower() == '.dat':
        dataset = parse_dat(text, name=path.stem, source=resolved(path))
    else:
        try:
            delimiter = csv.Sniffer().sniff(text[:65536], delimiters=',\t;').delimiter
        except csv.Error:
            delimiter = ',' if path.suffix.lower() == '.csv' else '\t'
        dataset = parse_text(text, delimiter=delimiter, name=path.stem, source=resolved(path))
    dataset.source_text = text
    return dataset


def column_names(table_text, delimiter, header):
    first = next(csv.reader(io.StringIO(table_text.removeprefix('﻿')), delimiter=delimiter), None)
    if first is None:
        raise ValueError('The file is empty.')
    return [c.strip() or f'Column {i+1}' for i, c in enumerate(first)] if header else \
        [f'Column {i+1}' for i in range(len(first))]


def channel_key(channel):
    """'2: Height (forward)' from a scan channel named '<file> — 2: Height (forward)'."""
    return channel.name.split(' — ', 1)[-1]


def read_with_template(path, template):
    """Read a file with the columns or channels chosen in another file's preview.

    A text template is {'delimiter', 'header', 'columns'}; a scan template is
    {'channels'}. Every chosen name must exist in the file.
    """
    path = Path(path)
    if 'channels' in template:
        if path.suffix.lower() not in SCAN_SUFFIXES:
            raise ValueError('The preview settings are for SPM/SXM scans; this is a text file.')
        by_name = {channel_key(d): d for d in load_spm(path)}
        missing = [name for name in template['channels'] if name not in by_name]
        if missing:
            raise ValueError(f'Missing channel(s): {", ".join(missing)}')
        return bundle_channels([by_name[name] for name in template['channels']], name=path.stem)
    if path.suffix.lower() in SCAN_SUFFIXES:
        raise ValueError('The preview settings are for text files; this is an SPM/SXM scan.')
    text, table = read_text_import(path)
    table_text = table if table is not None else text.removeprefix('﻿')
    delimiter, header = ('\t', True) if table is not None else (template['delimiter'], template['header'])
    names = column_names(table_text, delimiter, header)
    missing = [name for name in template['columns'] if name not in names]
    if missing:
        raise ValueError(f'Missing column(s): {", ".join(missing)}')
    return parse_text_import(path, text, table_text, delimiter, header,
                             [names.index(name) for name in template['columns']])


def format_name(pattern, path, number):
    """Display name from a pattern such as 'Scan_{n}' or 'BG_{num}'.

    {stem} is the file name without extension, {n} the running number, {num}
    the last digit run in the file name and {folder} the parent folder name.
    A blank pattern keeps the file name.
    """
    path = Path(path)
    if not pattern.strip():
        return path.stem
    digits = re.findall(r'\d+', path.stem)
    fields = dict(stem=path.stem, n=number, num=digits[-1] if digits else '', folder=path.parent.name)
    try:
        name = pattern.format_map(fields).strip()
    except (KeyError, IndexError, ValueError) as error:
        raise ValueError(f'Unknown name pattern {pattern!r}. Use {{{"}, {".join(NAME_TOKENS)}}}.') from error
    if not name:
        raise ValueError('The name pattern gives a blank name.')
    return name


def sort_by_x(dataset):
    """Order rows by the X channel (stable; missing X last). Returns True if rows moved."""
    if dataset.instrument_metadata.get('channels'):
        return False  # Scans keep their pixel and segment order.
    order = np.argsort(dataset.values[:, dataset.xcol], kind='stable')
    if np.array_equal(order, np.arange(len(order))):
        return False
    writeable = dataset.values.flags.writeable
    dataset.values = dataset.values[order]
    dataset.values.setflags(write=writeable)
    note = f'Rows sorted by {dataset.columns[dataset.xcol]} at import.'
    dataset.comments = f'{dataset.comments}\n{note}'.strip()
    return True


def folder_group(path, folder):
    """Relative subfolder of path below folder, '' for files at its top level."""
    try:
        relative = Path(path).parent.relative_to(folder)
    except ValueError:
        return ''
    return '' if relative == Path('.') else relative.as_posix()


def size_text(size):
    return f'{size} B' if size < 1024 else f'{size / 1024:.1f} KB' if size < 1024 ** 2 else f'{size / 1024 ** 2:.1f} MB'


def describe_contents(path):
    """('Spectrum DAT · 41 rows', channel names, image or None) without importing the file.

    The image is the first raster channel of a scan whose values vary, for a thumbnail.
    """
    path = Path(path)
    if path.suffix.lower() in SCAN_SUFFIXES:
        channels = load_spm(path)
        first = channels[0]
        kind = 'Nanonis SXM' if first.instrument_metadata.get('format') == 'nanonis_sxm' else 'Bruker SPM'
        image = None
        if first.columns[1:3] == ['X pixel', 'Y pixel']:
            width = int(first.values[:, 1].max()) + 1
            def varies(channel):
                signal = channel.values[:, 3]
                signal = signal[np.isfinite(signal)]
                return signal.size and signal.max() > signal.min()
            shown = next((d for d in channels if varies(d) and len(d.values) == len(first.values)), first)
            image = shown.values[:, 3].reshape(-1, width)
            kind += f' · {width}×{len(image)} px'
        return f'{kind} · {len(channels)} channels', [channel_key(d) for d in channels], image
    text, table = read_text_import(path)
    if table is not None:
        table_text, delimiter, kind = table, '\t', 'Spectrum DAT'
    else:
        table_text = text.removeprefix('﻿')
        try:
            delimiter = csv.Sniffer().sniff(table_text[:65536], delimiters=',\t;').delimiter
        except csv.Error:
            delimiter = ',' if path.suffix.lower() == '.csv' else '\t'
        kind = {',': 'Comma', '\t': 'Tab', ';': 'Semicolon'}[delimiter] + '-separated table'
    rows = sum(1 for line in table_text.splitlines()[1:] if line.strip())
    return f'{kind} · {rows} rows', column_names(table_text, delimiter, True), None


def file_preview(path, lines=14, limit=64 * 1024 ** 2):
    """Preview text and an optional thumbnail image for the highlighted file.

    The text gives size, modification time, detected kind, channels and the
    readable start of the file. Files above limit bytes are not parsed.
    """
    path = Path(path)
    try:
        stat = path.stat()
    except OSError as error:
        return str(error), None
    modified = datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
    head = [f'{path.name}', f'{size_text(stat.st_size)} · modified {modified}']
    if is_project(path):
        return '\n'.join(head + ['Rogi project: double-click or Open to open it.']), None
    image = None
    if stat.st_size <= limit:
        try:
            kind, channels, image = describe_contents(path)
            head += [kind, 'Channels: ' + ', '.join(channels)]
        except (ValueError, OSError, UnicodeError, csv.Error) as error:
            head.append(f'Cannot be loaded: {error}')
    try:
        with path.open('rb') as stream:
            start = stream.read(8192)
    except OSError as error:
        return '\n'.join(head + [str(error)]), image
    text = []
    # Instrument headers are text even in binary scans; stop at the first binary line.
    for raw in start.splitlines()[:lines]:
        line = raw.decode('utf-8', errors='replace')
        if '�' in line or '\x00' in line:
            break
        text.append(line[:160])
    return '\n'.join(head + [''] + text), image
