"""Versioned, non-destructive one-dimensional analysis recipes (no Qt)."""
from copy import deepcopy
import numpy as np
from .units import column_unit, normalize_unit, unit_hint

POLICIES = dict(
    missing='Rows with missing X or Y stay missing; local operations never cross gaps.',
    boundary='Smoothing clips centered windows at segment ends; differentiation uses one-sided endpoint slopes; singletons are missing.',
    spacing='Smoothing weights samples equally. Differentiation uses actual X spacing, requires strictly monotonic finite X, and never sorts or resamples.')
OPERATIONS = ('mean_subtract', 'normalize', 'moving_average', 'differentiate', 'photodiode_power')
PHOTODIODE_DEFAULTS = dict(detector='newport_2107', gain_setting=1.0, dark_v=0.0)


def validate_operations(operations):
    if not isinstance(operations, list) or not operations:
        raise ValueError('Add at least one operation.')
    for step in operations:
        if not isinstance(step, dict) or set(step) != {'operation', 'parameters'}:
            raise ValueError('Invalid analysis operation.')
        op, params = step['operation'], step['parameters']
        if op not in OPERATIONS or not isinstance(params, dict):
            raise ValueError('Unknown analysis operation.')
        if op == 'normalize':
            if set(params) != {'method'} or params['method'] not in ('max_abs', 'min_max'):
                raise ValueError('Normalization method must be max_abs or min_max.')
        elif op == 'moving_average':
            window = params.get('window')
            if set(params) != {'window'} or type(window) is not int or window < 1 or window % 2 != 1:
                raise ValueError('Moving-average window must be a positive odd integer.')
        elif op == 'photodiode_power':
            from .calibration import DETECTORS
            gain, dark = params.get('gain_setting'), params.get('dark_v')
            legacy = params.get('gain_v_per_a')  # older records stored the transimpedance itself
            if legacy is not None:
                gain_ok = set(params) == {'detector', 'gain_v_per_a', 'dark_v'} and type(legacy) in (int, float) \
                    and np.isfinite(legacy) and legacy > 0
            else:
                gain_ok = set(params) == set(PHOTODIODE_DEFAULTS) and type(gain) in (int, float) \
                    and gain in DETECTORS.get(params.get('detector'), {}).get('gain_settings', ())
            if (not gain_ok or params['detector'] not in DETECTORS
                    or type(dark) not in (int, float) or not np.isfinite(dark)):
                raise ValueError('Photodiode power needs a known detector, one of its front-panel gain '
                                 'settings and a finite dark voltage (V).')
        elif params:
            raise ValueError(f'{op} takes no parameters.')


def validate_analysis(record):
    if record is None:
        return
    if isinstance(record, dict) and record.get('version') == 2:
        _validate_multi(record)
        return
    if not isinstance(record, dict) or record.get('version') != 1:
        raise ValueError('Unsupported analysis provenance.')
    try:
        validate_operations(record['operations'])
        source = record['source']
        if (not isinstance(source['dataset_id'], str) or not source['dataset_id']
                or type(source['revision']) is not int or source['revision'] < 0):
            raise ValueError('Invalid analysis source.')
        for channel in record['input_channels'].values():
            if (type(channel['index']) is not int or channel['index'] < 0
                    or not isinstance(channel['name'], str) or not isinstance(channel['unit'], str)):
                raise ValueError('Invalid analysis channel.')
        if set(record['input_channels']) != {'x', 'y'}:
            raise ValueError('Analysis needs X and Y input channels.')
        if (not isinstance(record['output_units'], list) or len(record['output_units']) != 2
                or not all(isinstance(u, str) for u in record['output_units'])
                or record['policies'] != POLICIES):
            raise ValueError('Invalid analysis units or numerical policies.')
        if 'calibrations' in record and not isinstance(record['calibrations'], dict):
            raise ValueError('Invalid analysis calibrations.')
    except (KeyError, TypeError, AttributeError) as error:
        raise ValueError('Malformed analysis provenance.') from error


def channel_unit(dataset, index):
    return column_unit(dataset, index)


def _segments(valid):
    edges = np.diff(np.r_[False, valid, False].astype(int))
    return zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1))


def analyze(dataset, operations, *, xcol=None, ycol=None, xunit=None, yunit=None, name=None):
    """Return an independent editable snapshot; never mutate source or recipe.

    Unknown units are ''. Normalization emits '1' (dimensionless). Zero-scale
    normalization raises; all-missing inputs raise. No interpolation is done.
    """
    from .core import Dataset
    validate_operations(operations)
    xcol = dataset.xcol if xcol is None else xcol
    ycol = dataset.ycol if ycol is None else ycol
    if (type(xcol) is not int or type(ycol) is not int or xcol == ycol
            or not 0 <= xcol < len(dataset.columns) or not 0 <= ycol < len(dataset.columns)):
        raise ValueError('Choose distinct valid X and Y channels.')
    xu = channel_unit(dataset, xcol) if xunit is None else normalize_unit(xunit)
    yu = channel_unit(dataset, ycol) if yunit is None else normalize_unit(yunit)
    input_yunit = yu
    x = dataset.values[:, xcol].copy()
    y = dataset.values[:, ycol].copy()
    y[~np.isfinite(x)] = np.nan
    with np.errstate(over='raise', divide='raise', invalid='raise'):
        try:
            for step in operations:
                valid = np.isfinite(y)
                if not valid.any():
                    raise ValueError('Operation has no finite X/Y samples.')
                op, params = step['operation'], step['parameters']
                if op == 'mean_subtract':
                    y[valid] -= np.mean(y[valid])
                elif op == 'normalize':
                    v = y[valid]
                    offset = np.min(v) if params['method'] == 'min_max' else 0.
                    scale = np.max(v) - offset if params['method'] == 'min_max' else np.max(np.abs(v))
                    if scale == 0:
                        raise ValueError('Cannot normalize a zero-scale signal.')
                    y[valid] = (v - offset) / scale
                    yu = '1'
                elif op == 'photodiode_power':
                    from .calibration import DETECTORS, photodiode_power_mw
                    if xu != 'nm':
                        raise ValueError('Photodiode power needs X as wavelength in nm.')
                    if yu != 'V':
                        raise ValueError('Photodiode power needs Y as a voltage in V.')
                    if 'gain_v_per_a' in params:
                        setting = params['gain_v_per_a'] / DETECTORS[params['detector']]['transimpedance_v_per_a_per_setting']
                    else:
                        setting = params['gain_setting']
                    y = photodiode_power_mw(y, x, params['detector'], float(setting), float(params['dark_v']))
                    if not np.isfinite(y).any():
                        raise ValueError('No samples lie inside the detector calibration range.')
                    yu = 'mW'
                else:
                    result = np.full(y.shape, np.nan)
                    if op == 'differentiate':
                        dx = np.diff(x[np.isfinite(x)])
                        if not (np.all(dx > 0) or np.all(dx < 0)):
                            raise ValueError('Differentiation requires strictly monotonic X (no duplicates).')
                        yu = (yu if xu == '1' else f'({yu})/({xu})') if yu and xu else ''
                    for start, end in _segments(valid):
                        if op == 'moving_average':
                            half = params['window'] // 2
                            # Prefix sums keep large windows linear in sample count.
                            segment = y[start:end]
                            total = np.r_[0., np.cumsum(segment)]
                            rows = np.arange(end - start)
                            lo, hi = np.maximum(0, rows-half), np.minimum(end-start, rows+half+1)
                            result[start:end] = (total[hi] - total[lo]) / (hi-lo)
                        elif end-start >= 2:
                            result[start:end] = np.gradient(y[start:end], x[start:end], edge_order=1)
                    y = result
        except FloatingPointError as error:
            raise ValueError('Analysis overflow or invalid arithmetic; rescale the input.') from error
    if np.isinf(y).any():
        raise ValueError('Analysis produced infinite values.')
    record = dict(version=1, source=dict(dataset_id=dataset.id, revision=dataset.revision),
                  input_channels=dict(x=dict(index=xcol, name=dataset.columns[xcol], unit=xu),
                                      y=dict(index=ycol, name=dataset.columns[ycol], unit=input_yunit)),
                  operations=deepcopy(operations), output_units=[xu, yu], policies=deepcopy(POLICIES))
    detectors = {s['parameters']['detector'] for s in operations if s['operation'] == 'photodiode_power'}
    if detectors:
        from .calibration import detector_curve
        # The curve itself is provenance: results stay reproducible if the bundled curve changes.
        record['calibrations'] = {d: detector_curve(d) for d in sorted(detectors)}
    output_name = 'Result' + (f' ({yu})' if yu else '')
    if output_name == dataset.columns[xcol]:
        output_name += ' [analysis]'
    return Dataset(name or dataset.name + ' (analysis)', [dataset.columns[xcol], output_name],
                   np.column_stack((x, y)), raw=False, parent=dataset.id, source=dataset.source,
                   group=dataset.group, group_path=deepcopy(dataset.group_path),
                   column_units=[xu, yu], analysis=record)


MULTI_POLICIES = dict(interpolation='linear within contiguous finite runs; no extrapolation or gap bridging',
                      compatibility='exact channel names and units',
                      statistics='sample standard deviation (ddof=1); SEM=SD/sqrt(n); undefined for n<2')


def _validate_multi(record):
    try:
        sources = record['sources']
        if not isinstance(sources, list):
            raise ValueError('Invalid analysis sources.')
        ids = [s['dataset_id'] for s in sources]
        if any(not isinstance(i, str) or not i for i in ids) or len(ids) < 2 or len(set(ids)) != len(ids):
            raise ValueError('Invalid analysis sources.')
        for s in sources:
            if not isinstance(s['dataset_id'], str) or not s['dataset_id'] or type(s['revision']) is not int or s['revision'] < 0:
                raise ValueError('Invalid analysis source.')
            if set(s['input_channels']) != {'x', 'y'}:
                raise ValueError('Invalid analysis channels.')
            for c in s['input_channels'].values():
                if type(c['index']) is not int or c['index'] < 0 or not all(isinstance(c[k], str) for k in ('name', 'unit')):
                    raise ValueError('Invalid analysis channel.')
        if (record['operation'] not in ('reference_subtract', 'paired_subtract', 'mean')
                or record['alignment'] != dict(mode=record['alignment']['mode'], grid_dataset_id=record['alignment']['grid_dataset_id'])
                or record['alignment']['mode'] not in ('exact', 'interpolate')
                or record['alignment']['grid_dataset_id'] not in ids
                or record['policies'] != MULTI_POLICIES
                or not isinstance(record['output_units'], list)
                or not all(isinstance(u, str) for u in record['output_units'])):
            raise ValueError('Invalid multi-dataset analysis provenance.')
        pairs = record['pairs']
        if record['operation'] == 'mean':
            if pairs or len(record['output_units']) != 5:
                raise ValueError('Invalid mean provenance.')
        elif (len(pairs) != 1 or len(pairs[0]) != 2 or pairs[0][0] == pairs[0][1]
              or any(i not in ids for i in pairs[0]) or len(record['output_units']) != 3):
            raise ValueError('Invalid subtraction provenance.')
    except (KeyError, TypeError, AttributeError) as error:
        raise ValueError('Malformed multi-dataset analysis provenance.') from error


def analyze_many(datasets, operation='mean', *, reference=None, pairs=None,
                 alignment='exact', grid=None):
    """Analyze selected channels; return independent datasets with full provenance.

    Subtraction is explicitly left minus right. Exact alignment compares X values
    without tolerance. Interpolation never bridges missing rows or extrapolates.
    Counts are finite spectra for means, and finite operands for subtraction.
    """
    from .core import Dataset
    datasets = list(datasets)
    lookup = {d.id: d for d in datasets}
    if len(datasets) < 2 or len(lookup) != len(datasets):
        raise ValueError('Select at least two distinct datasets.')
    if operation not in ('mean', 'reference_subtract', 'paired_subtract'):
        raise ValueError('Unknown multi-dataset operation.')
    if alignment not in ('exact', 'interpolate'):
        raise ValueError('Choose exact alignment or explicit interpolation.')
    if alignment == 'interpolate' and grid is None:
        raise ValueError('Choose a reference grid for interpolation.')
    grid = datasets[0].id if grid is None else grid
    if grid not in lookup:
        raise ValueError('Reference grid must be a selected dataset.')
    sources = []
    for d in datasets:
        if d.xcol == d.ycol or not all(0 <= i < len(d.columns) for i in (d.xcol, d.ycol)):
            raise ValueError('Choose distinct valid X and Y channels.')
        sources.append(dict(dataset_id=d.id, revision=d.revision, name=d.name,
                            input_channels={axis: dict(index=i, name=d.columns[i], unit=channel_unit(d, i))
                                            for axis, i in [('x', d.xcol), ('y', d.ycol)]}))
    signature = lambda s: [(s['input_channels'][a]['name'], s['input_channels'][a]['unit']) for a in ('x', 'y')]
    if any(signature(s) != signature(sources[0]) for s in sources[1:]):
        raise ValueError('Compatible X/Y channel names and units are required (no automatic unit conversion). '
                         + unit_hint([[u for _, u in signature(s)] for s in sources]))
    x = lookup[grid].values[:, lookup[grid].xcol].copy()
    if not np.isfinite(x).all():
        raise ValueError('X coordinates must be finite.')
    aligned = {}
    for d in datasets:
        dx, dy = d.values[:, d.xcol], d.values[:, d.ycol]
        if not np.isfinite(dx).all():
            raise ValueError('X coordinates must be finite.')
        if alignment == 'exact':
            if not np.array_equal(dx, x):
                raise ValueError('Matching X coordinates required; explicitly choose interpolation to align grids.')
            aligned[d.id] = dy.copy()
        else:
            if not (np.all(np.diff(dx) > 0) or np.all(np.diff(dx) < 0)):
                raise ValueError('Interpolation requires strictly monotonic X without duplicates.')
            if len(dx) > 1 and dx[0] > dx[-1]:
                dx, dy = dx[::-1], dy[::-1]
            y = np.full(x.shape, np.nan)
            for start, end in _segments(np.isfinite(dy)):
                mask = (x >= dx[start]) & (x <= dx[end-1])
                y[mask] = np.interp(x[mask], dx[start:end], dy[start:end])
            aligned[d.id] = y
    if operation == 'reference_subtract':
        if reference not in lookup:
            raise ValueError('Choose a selected reference dataset.')
        pairs = [(d.id, reference) for d in datasets if d.id != reference]
    elif operation == 'paired_subtract':
        if not pairs or any(len(p) != 2 or p[0] == p[1] or any(i not in lookup for i in p) for p in pairs):
            raise ValueError('Specify explicit pairs of distinct selected datasets (left minus right).')
        if len({tuple(p) for p in pairs}) != len(pairs):
            raise ValueError('Duplicate subtraction pairs are not allowed.')
    else:
        pairs = []
    xu, yu = [sources[0]['input_channels'][a]['unit'] for a in ('x', 'y')]
    outputs = []
    try:
        with np.errstate(over='raise', invalid='raise', divide='raise'):
            for pair in pairs if pairs else [None]:
                if pair is None:
                    values = np.array([aligned[d.id] for d in datasets])
                    count = np.isfinite(values).sum(axis=0)
                    mean = np.divide(np.nansum(values, axis=0), count, out=np.full(x.shape, np.nan), where=count > 0)
                    squares = np.nansum((values - mean)**2, axis=0)
                    sd = np.sqrt(np.divide(squares, count-1, out=np.full(x.shape, np.nan), where=count > 1))
                    sem = sd / np.sqrt(np.maximum(count, 1))
                    data = np.column_stack((x, mean, sd, sem, count))
                    columns = [lookup[grid].columns[lookup[grid].xcol], 'Mean', 'Standard deviation (sample)', 'Standard error of mean', 'Sample count']
                    units, title = [xu, yu, yu, yu, '1'], 'Mean spectra'
                else:
                    left, right = [aligned[i] for i in pair]
                    count = np.isfinite(left).astype(int) + np.isfinite(right).astype(int)
                    data = np.column_stack((x, left-right, count))
                    columns = [lookup[grid].columns[lookup[grid].xcol], 'Difference', 'Contributing operand count']
                    units, title = [xu, yu, '1'], lookup[pair[0]].name + ' − ' + lookup[pair[1]].name
                record = dict(version=2, sources=deepcopy(sources), operation=operation,
                              pairs=[list(pair)] if pair else [], alignment=dict(mode=alignment, grid_dataset_id=grid),
                              output_units=units, policies=deepcopy(MULTI_POLICIES))
                outputs.append(Dataset(title, columns, data, raw=False, column_units=units, analysis=record))
    except FloatingPointError as error:
        raise ValueError('Analysis overflow; rescale the inputs.') from error
    return outputs
