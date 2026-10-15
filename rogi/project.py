"""Portable, versioned project files. Writes replace the destination atomically."""
from dataclasses import asdict
import json
import os
from pathlib import Path
import tempfile
import numpy as np
from .core import Dataset, MODELS


def save_project(path, datasets, settings):
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
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if data['format'] != 'rogi' or data['version'] != 1:
            raise ValueError("Unsupported project format/version.")
        datasets = [Dataset(**item) for item in data['datasets']]
        if len({d.id for d in datasets}) != len(datasets):
            raise ValueError("Duplicate dataset IDs.")
        for d in datasets:
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
                if not isinstance(limits, list) or len(limits) != 2 or not np.isfinite(limits).all() or limits[0] == limits[1]:
                    raise ValueError("Invalid plot axis limits.")
        return datasets, settings
    except (KeyError, TypeError, AttributeError, OverflowError) as error:
        raise ValueError(f"Malformed project: {error}") from error
