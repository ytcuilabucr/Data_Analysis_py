"""HDF5 project encoding. Validation is shared with JSON in project.py."""
from dataclasses import fields
import json
import os
import tempfile

import h5py
import numpy as np

FIT_ARRAYS = ('rows', 'x', 'observed', 'predicted', 'residuals')


def _write_json(group, name, value):
    # Bytes also preserve embedded NULs, unlike HDF5 variable-length strings.
    encoded = json.dumps(value, allow_nan=False, ensure_ascii=False).encode('utf-8')
    group.create_dataset(name, data=np.frombuffer(encoded, dtype='u1'), compression='gzip')


def _read_json(group, name):
    return json.loads(group[name][:].tobytes().decode('utf-8'))


def save_hdf5(path, datasets, settings):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, suffix='.h5', delete=False) as stream:
            temporary = stream.name
        with h5py.File(temporary, 'w') as file:
            file.attrs['format'] = 'rogi'
            file.attrs['version'] = 1
            _write_json(file, 'settings', settings)
            runs = file.create_group('datasets')
            for index, dataset in enumerate(datasets):
                group = runs.create_group(f'{index:08d}')
                metadata = {f.name: getattr(dataset, f.name) for f in fields(dataset)
                            if f.name not in ('values', 'fit', 'source_text', 'edits')}
                _write_json(group, 'metadata', metadata)
                _write_json(group, 'source_text', dataset.source_text)
                _write_json(group, 'edits', dataset.edits)
                group.create_dataset('values', data=dataset.values,
                    chunks=(min(4096, len(dataset.values)), 1),
                    compression='gzip', compression_opts=4, shuffle=True)
                if dataset.fit is not None:
                    fit = group.create_group('fit')
                    _write_json(fit, 'metadata', {k: v for k, v in dataset.fit.items() if k not in FIT_ARRAYS})
                    for key in FIT_ARRAYS:
                        fit.create_dataset(key, data=np.asarray(dataset.fit[key],
                            dtype='i8' if key == 'rows' else 'f8'), compression='gzip', shuffle=True)
        # Close HDF5 first, then sync and replace; a failed save leaves the old file.
        with open(temporary, 'rb') as stream:
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def load_hdf5(path):
    with h5py.File(path, 'r') as file:
        if file.attrs.get('format') != 'rogi' or file.attrs.get('version') != 1:
            raise ValueError('Unsupported HDF5 project format/version. Open a Rogi project file.')
        items = []
        for group in file['datasets'].values():
            item = _read_json(group, 'metadata')
            item.update(values=group['values'][:], source_text=_read_json(group, 'source_text'),
                        edits=_read_json(group, 'edits'), fit=None)
            if 'fit' in group:
                fit = group['fit']
                item['fit'] = _read_json(fit, 'metadata')
                item['fit'].update({k: fit[k][:].tolist() for k in FIT_ARRAYS})
            items.append(item)
        return dict(format='rogi', version=1, datasets=items, settings=_read_json(file, 'settings'))
