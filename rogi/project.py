"""Portable, versioned project files. Writes replace the destination atomically."""
from dataclasses import asdict
import json
import csv
import os
from pathlib import Path
import tempfile
import numpy as np
import h5py
from .core import Dataset, MODELS, parse_text, parse_dat
from .hdf5 import save_hdf5, load_hdf5
from .spm import load_spm
from .scanfile import bundle_channels
from .metadata import validate_metadata
from .plotting import validate_view, validate_appearance
from .presets import validate_presets
from .views import validate_saved_views


def convert_folder(folder, destination):
    """Recursively convert supported files into one grouped HDF5 project.

    Validate all inputs before saving, so a bad input cannot produce a partial
    project or replace an existing destination. Plain tables require headers.
    Directory symlinks are not traversed. Root-level datasets remain ungrouped.
    """
    folder, destination = Path(folder), Path(destination)
    if destination.suffix.lower() not in ('.h5', '.hdf5'):
        raise ValueError('Choose a .h5 or .hdf5 filename.')
    if not folder.is_dir():
        raise ValueError(f'Input folder does not exist or is not a directory: {folder}')
    def scan_error(error):
        raise error
    supported = {'.csv', '.tsv', '.txt', '.dat', '.spm', '.sxm'}
    paths = sorted(Path(directory) / name
                   for directory, _, names in os.walk(folder, onerror=scan_error, followlinks=False)
                   for name in names if Path(name).suffix.lower() in supported)
    if not paths:
        raise ValueError('No CSV, TSV, TXT, DAT, SPM, or SXM files found in the selected folder or its subfolders.')
    datasets = []
    for path in paths:
        relative = path.relative_to(folder)
        group = '' if relative.parent == Path('.') else relative.parent.as_posix()
        try:
            if path.suffix.lower() in ('.spm', '.sxm'):
                imported = [bundle_channels(load_spm(path), name=path.stem)]
            else:
                text = path.read_bytes().decode('utf-8')
                if path.suffix.lower() == '.dat':
                    dataset = parse_dat(text, name=path.stem, source=str(path.resolve()))
                else:
                    try:
                        delimiter = csv.Sniffer().sniff(text[:65536], delimiters=',\t;').delimiter
                    except csv.Error:
                        delimiter = ',' if path.suffix.lower() == '.csv' else '\t'
                    dataset = parse_text(text, delimiter=delimiter, name=path.stem, source=str(path.resolve()))
                dataset.source_text = text
                imported = [dataset]
            for dataset in imported:
                dataset.group = group
                dataset.visible = not datasets
                datasets.append(dataset)
        except (ValueError, OSError, UnicodeError, csv.Error) as error:
            raise ValueError(f'{relative.as_posix()}: {error}') from error
    save_project(destination, datasets, dict(title=folder.name, xlabel='', ylabel=''))
    return len(datasets)


def save_project(path, datasets, settings):
    validate_view(settings)
    validate_saved_views(settings.get('saved_views', {}))
    validate_presets(settings.get('pipeline_presets', {}))
    for dataset in datasets:
        validate_appearance(dataset.color, dataset.marker)
        validate_metadata(dataset)
        from .analysis import validate_analysis
        validate_analysis(dataset.analysis)
    if Path(path).suffix.lower() in ('.h5', '.hdf5'):
        return save_hdf5(Path(path), datasets, settings)
    payload = []
    for dataset in datasets:
        item = asdict(dataset)
        item['values'] = [[None if np.isnan(v) else float(v) for v in row] for row in dataset.values]
        payload.append(item)
    content = json.dumps(dict(format="rogi", version=1, datasets=payload, settings=settings), allow_nan=False, indent=2)
    path = Path(path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as stream:
            temporary = stream.name
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def load_project(path):
    try:
        data = load_hdf5(path) if h5py.is_hdf5(path) else json.loads(Path(path).read_text(encoding="utf-8"))
        if data['format'] != 'rogi' or data['version'] != 1:
            raise ValueError("Unsupported project format/version.")
        datasets = [Dataset(**item) for item in data['datasets']]
        if len({d.id for d in datasets}) != len(datasets):
            raise ValueError("Duplicate dataset IDs.")
        for d in datasets:
            validate_appearance(d.color, d.marker)
            if not all(isinstance(c, str) for c in d.columns) or len(set(d.columns)) != len(d.columns):
                raise ValueError("Invalid column names.")
            if not (0 <= d.xcol < len(d.columns) and 0 <= d.ycol < len(d.columns)) or d.style not in ('Line', 'Scatter'):
                raise ValueError("Invalid plot settings.")
            if d.fit:
                f = d.fit
                if f['model'] not in MODELS or f['revision'] != d.revision:
                    raise ValueError("Invalid or stale fit.")
                names = MODELS[f['model']][1]
                if set(f['parameters']) != set(names) or set(f['errors']) != set(names):
                    raise ValueError("Invalid fit parameters.")
                lengths = [len(f[k]) for k in ('rows', 'x', 'observed', 'predicted', 'residuals')]
                if len(set(lengths)) != 1 or not lengths[0] or any(r < 0 or r >= len(d.values) for r in f['rows']):
                    raise ValueError("Invalid fit result rows.")
                if not (0 <= f['xcol'] < len(d.columns) and 0 <= f['ycol'] < len(d.columns)):
                    raise ValueError("Invalid fit columns.")
                numeric = list(f['parameters'].values()) + [f['lower'], f['upper'], f['rmse']]
                numeric += [v for key in ('x', 'observed', 'predicted', 'residuals') for v in f[key]]
                if not np.isfinite(numeric).all() or f['lower'] >= f['upper']:
                    raise ValueError("Invalid numeric fit results.")
                if any(e is not None and (not np.isfinite(e) or e < 0) for e in f['errors'].values()):
                    raise ValueError("Invalid parameter uncertainties.")
                if not isinstance(f['warning'], str) or f['dof'] <= 0 or f['excluded_missing'] < 0:
                    raise ValueError("Invalid fit diagnostics.")
        settings = data['settings']
        if not isinstance(settings, dict):
            raise ValueError("Invalid project settings.")
        for key in ('title', 'xlabel', 'ylabel'):
            if key in settings and not isinstance(settings[key], str):
                raise ValueError("Invalid plot label.")
        for key in ('xlim', 'ylim'):
            if key in settings:
                limits = settings[key]
                if limits is not None and (not isinstance(limits, list) or len(limits) != 2 or not np.isfinite(limits).all() or limits[0] == limits[1]):
                    raise ValueError("Invalid plot axis limits.")
        validate_view(settings)
        validate_saved_views(settings.get('saved_views', {}))
        validate_presets(settings.get('pipeline_presets', {}))
        return datasets, settings
    except (KeyError, TypeError, AttributeError, OverflowError) as error:
        raise ValueError(f"Malformed project: {error}") from error
