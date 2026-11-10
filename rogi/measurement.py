"""Reading stepped-measurement HDF5 files written by the acquisition software (no Qt).

A measurement file holds a `plan` group whose `plan_json` attribute lists the
swept axes from outermost to innermost, a `setpoints` group with one 1-D array
per axis, and a `data` group whose arrays all have the plan's shape (readings,
`timestamp` and `seq`). Rogi project files are also HDF5 but carry
`format = 'rogi'`, so the two are told apart by content, not by suffix.

The innermost axis becomes X. Each combination of outer setpoints becomes one
dataset named '<file>, <axis> = <value>', so a power x wavelength scan at three
powers gives three spectra and a wavelength-only scan gives one.
"""
import itertools
import json
from pathlib import Path
import h5py
import numpy as np
from .core import Dataset

H5_SUFFIXES = ('.h5', '.hdf5')
BOOKKEEPING = ('timestamp', 'seq')
BOOKKEEPING_UNITS = {'timestamp': 's', 'seq': ''}
# Setpoint arrays carry no units; these axis-name endings name a conventional one.
AXIS_UNITS = {'wavelength': 'nm'}


def is_measurement(path):
    """True for an HDF5 measurement file, False for Rogi projects and anything unreadable."""
    path = Path(path)
    if path.suffix.lower() not in H5_SUFFIXES:
        return False
    try:
        if not h5py.is_hdf5(path):
            return False
        with h5py.File(path, 'r') as file:
            plan = file.get('plan')
            return (file.attrs.get('format') != 'rogi' and isinstance(plan, h5py.Group)
                    and 'plan_json' in plan.attrs and isinstance(file.get('data'), h5py.Group))
    except (OSError, ValueError):
        return False


def _text(value):
    return value.decode('utf-8') if isinstance(value, bytes) else str(value)


def _plain(value):
    """An HDF5 attribute as a JSON value."""
    if isinstance(value, np.ndarray):
        return [_plain(v) for v in value.tolist()]
    if isinstance(value, (bytes, np.bytes_)):
        return value.decode('utf-8', errors='replace')
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, list):
        return [_plain(v) for v in value]
    return value


def _attributes(group):
    return {key: _plain(value) for key, value in group.attrs.items()} if group is not None else {}


def axis_unit(name, attrs):
    unit = _text(attrs.get('units', '')) if 'units' in attrs else ''
    return unit or AXIS_UNITS.get(name.rsplit('.', 1)[-1].strip().lower(), '')


def _value_text(value):
    return f'{value:g}' if np.isfinite(value) else str(value)


def _plan(file):
    """The plan JSON and its swept axis names, outermost first."""
    try:
        plan = json.loads(_text(file['plan'].attrs['plan_json']))
        return plan, [str(axis['device']) for axis in plan.get('axes', [])]
    except (ValueError, KeyError, TypeError, AttributeError) as error:
        raise ValueError(f'Unreadable measurement plan: {error}') from error


def describe_measurement(path):
    """('Measurement HDF5 · 3 × 236 points (…)', channel names) without building datasets."""
    with h5py.File(path, 'r') as file:
        plan, axes = _plan(file)
        shape = list(plan.get('shape') or [len(axis.get('points', [])) for axis in plan.get('axes', [])])
        channels = [name for name in file['data'] if name not in BOOKKEEPING]
        status = _text(file.attrs.get('status', ''))
    sweep = ' × '.join(f'{n} {axis.rsplit(".", 1)[-1]}' for n, axis in zip(shape, axes)) or 'no swept axes'
    kind = f'Measurement HDF5 · {sweep}'
    if status and status != 'success':
        kind += f' · status {status}'
    return kind, axes[-1:] + channels


def load_measurement(path):
    """Datasets from one measurement file: one per combination of outer setpoints."""
    path = Path(path)
    if not is_measurement(path):
        raise ValueError('Not a measurement HDF5 file (no plan and data groups).')
    with h5py.File(path, 'r') as file:
        plan, axes = _plan(file)
        data = file['data']
        readings = [name for name in data if name not in BOOKKEEPING and isinstance(data[name], h5py.Dataset)]
        if not readings:
            raise ValueError('The measurement has no recorded channels.')
        extra = [name for name in BOOKKEEPING if name in data]
        shape = data[readings[0]].shape
        for name in readings + extra:
            if data[name].shape != shape:
                raise ValueError(f'Channel {name!r} has shape {data[name].shape}, expected {shape}.')
        setpoints = file.get('setpoints')
        if axes:
            missing = [axis for axis in axes if setpoints is None or axis not in setpoints]
            if missing:
                raise ValueError(f'Missing setpoints for {", ".join(missing)}.')
            if tuple(len(setpoints[axis]) for axis in axes) != shape:
                raise ValueError(f'Setpoints {[len(setpoints[a]) for a in axes]} do not match data shape {list(shape)}.')
            x_name, x_values = axes[-1], np.asarray(setpoints[axes[-1]][:], dtype=float)
            x_unit = axis_unit(x_name, setpoints[x_name].attrs)
            outer = [(axis, np.asarray(setpoints[axis][:], dtype=float)) for axis in axes[:-1]]
        else:
            # An unswept (logged) measurement: time is the only X there is.
            if 'timestamp' not in extra or len(shape) != 1:
                raise ValueError('A measurement without swept axes needs a 1-D timestamp.')
            x_name, x_values, x_unit, outer = 'timestamp', None, 's', []
            extra = [name for name in extra if name != 'timestamp']
        arrays = {name: np.asarray(data[name][:], dtype=float) for name in readings + extra}
        units = [x_unit] + [_text(data[name].attrs.get('units', '')) for name in readings] + \
            [BOOKKEEPING_UNITS[name] for name in extra]
        if x_values is None:
            x_values = np.asarray(data['timestamp'][:], dtype=float)
        attributes = _attributes(file)
        source = dict(file=path.name, attributes=attributes, plan=plan,
                      provenance=_attributes(file.get('provenance')),
                      snapshot=_attributes(file.get('snapshot')))
    status = attributes.get('status', '')
    note = f'Measurement status: {status}' + (f' ({attributes["reason"]})' if attributes.get('reason') else '') \
        if status and status != 'success' else ''
    source_text = json.dumps(source, indent=2, default=str)
    columns = [x_name] + readings + extra
    datasets = []
    for index in itertools.product(*(range(len(values)) for _, values in outer)):
        signal = np.column_stack([arrays[name][index] for name in readings])
        if not np.isfinite(signal).any():
            continue  # This outer setpoint was never measured (an aborted scan).
        values = np.column_stack([x_values, signal] + [arrays[name][index] for name in extra])
        name = ', '.join([path.stem] + [f'{axis} = {_value_text(points[i])}'
                                        for (axis, points), i in zip(outer, index)])
        datasets.append(Dataset(name, list(columns), values, source=str(path.resolve()),
                                source_text=source_text, comments=note,
                                column_units=list(units)))
    if not datasets:
        raise ValueError('The measurement contains no recorded values.')
    return datasets
