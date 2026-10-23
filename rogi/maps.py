"""Explicit spectrum-to-map assembly, without modifying measured coordinates."""
from dataclasses import dataclass
import csv
import json
import re
import numpy as np
from .analysis import channel_unit
from .units import axis_label, unit_hint
from .metadata import metadata_fields


def coordinate(raw):
    match = re.fullmatch(r'\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*(.*?)\s*', raw or '')
    if not match or not np.isfinite(float(match[1])):
        raise ValueError(f'Missing or nonnumeric sweep coordinate: {raw!r}.')
    return float(match[1]), match[2]


def validate_recipe(recipe):
    if not isinstance(recipe, dict):
        raise ValueError('Invalid map recipe.')
    for key in ('x', 'signal', 'sweep'):
        if not isinstance(recipe.get(key), str) or not recipe[key]:
            raise ValueError(f'Choose a {key} channel or field explicitly.')
    ids = recipe.get('ids')
    if not isinstance(ids, list) or not ids or not all(isinstance(i, str) for i in ids) or len(set(ids)) != len(ids):
        raise ValueError('Select distinct source spectra.')
    if recipe.get('alignment') not in ('exact', 'union', 'reference'):
        raise ValueError('Choose an X-grid alignment explicitly.')
    if recipe.get('missing') not in ('reject', 'gaps'):
        raise ValueError('Choose a missing-measurement policy.')
    if recipe.get('alignment') == 'reference' and recipe.get('reference') not in ids:
        raise ValueError('Choose a reference spectrum.')
    section = recipe.get('section')
    if section is not None and (not isinstance(section, dict)
            or section.get('axis') not in ('x', 'sweep')
            or type(section.get('index')) is not int or section['index'] < 0):
        raise ValueError('Invalid map cross-section.')
    filters = recipe.get('filters', {})
    if not isinstance(filters, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in filters.items()):
        raise ValueError('Invalid sweep dimension selectors.')
    if recipe['sweep'] in filters:
        raise ValueError('The map sweep cannot also be a fixed dimension.')


@dataclass
class SpectrumMap:
    x: np.ndarray
    sweep: np.ndarray
    signal: np.ndarray
    units: tuple
    measured: list
    recipe: dict

    def section(self, axis, index):
        if axis == 'sweep':
            return self.x.copy(), self.signal[index].copy()
        if axis == 'x':
            return self.sweep.copy(), self.signal[:, index].copy()
        raise ValueError('Unknown cross-section axis.')

    def export(self, path):
        """NPZ includes raw observations and recipe; CSV contains plotted coordinates."""
        if str(path).lower().endswith('.npz'):
            arrays = {f'measured_x_{i}': m['x'] for i, m in enumerate(self.measured)}
            arrays.update({f'measured_signal_{i}': m['signal'] for i, m in enumerate(self.measured)})
            provenance = [dict(id=m['id'], sweep=m['sweep']) for m in self.measured]
            np.savez(path, x=self.x, sweep=self.sweep, signal=self.signal,
                     units=np.array(self.units), recipe=json.dumps(self.recipe),
                     sources=json.dumps(provenance), **arrays)
        else:
            with open(path, 'w', newline='') as stream:
                writer = csv.writer(stream)
                writer.writerow([axis_label(self.recipe['x'], self.units[0]),
                                 axis_label(self.recipe['sweep'], self.units[2]),
                                 axis_label(self.recipe['signal'], self.units[1])])
                writer.writerows((x, y, '' if np.isnan(z) else z)
                                 for y, row in zip(self.sweep, self.signal) for x, z in zip(self.x, row))


def assemble_map(datasets, recipe):
    validate_recipe(recipe)
    lookup = {d.id: d for d in datasets}
    if any(i not in lookup for i in recipe['ids']):
        raise ValueError('A source spectrum is missing. Reselect the sources.')
    selected = [lookup[i] for i in recipe['ids']]
    selected = [d for d in selected if all(metadata_fields(d).get(k) == v
                for k, v in recipe.get('filters', {}).items())]
    if not selected:
        raise ValueError('No measurements exist for this combination of sweep dimensions.')
    records, units, grids = [], [], []
    for d in selected:
        if d.instrument_metadata.get('format') in ('nanoscope', 'nanonis_sxm'):
            raise ValueError(f'{d.name}: select spectra, not scan images.')
        try:
            xi, zi = d.columns.index(recipe['x']), d.columns.index(recipe['signal'])
        except ValueError:
            raise ValueError(f'{d.name}: selected channel is missing.') from None
        if xi == zi:
            raise ValueError('Choose distinct X and signal channels.')
        sweep, unit = coordinate(metadata_fields(d).get(recipe['sweep']))
        units.append((channel_unit(d, xi), channel_unit(d, zi), unit))
        x, z = d.values[:, xi].copy(), d.values[:, zi].copy()
        if not np.isfinite(x).all() or len(np.unique(x)) != len(x):
            raise ValueError(f'{d.name}: X coordinates must be finite and unique.')
        if len(x) < 2:
            raise ValueError(f'{d.name}: at least two X coordinates are required.')
        if not np.isfinite(z).any():
            raise ValueError(f'{d.name}: all signal measurements are missing.')
        records.append(dict(id=d.id, sweep=sweep, x=x, signal=z))
        order = np.argsort(x)
        grids.append((x[order], z[order]))
    if any(u != units[0] for u in units):
        raise ValueError('Inconsistent X, signal, or sweep units. Convert units explicitly before assembling. '
                         + unit_hint([u[:2] for u in units]))
    if any(not u for u in units[0]):
        raise ValueError('Unknown units. Supply channel units and a sweep unit (1 for dimensionless).')
    if len({r['sweep'] for r in records}) != len(records):
        raise ValueError('Duplicate sweep values. Select additional sweep dimensions or distinct spectra; repeats are not averaged.')
    mode = recipe['alignment']
    if mode == 'exact':
        x = grids[0][0].copy()
        if any(not np.array_equal(g[0], x) for g in grids):
            raise ValueError('Differing X grids. Explicitly choose measured union or reference interpolation.')
    elif mode == 'union':
        x = np.unique(np.concatenate([g[0] for g in grids]))
    else:
        ref = next((i for i, r in enumerate(records) if r['id'] == recipe['reference']), None)
        if ref is None:
            raise ValueError('Reference spectrum is outside the selected slice.')
        x = grids[ref][0].copy()
    rows = []
    for gx, gz in grids:
        row = np.full(len(x), np.nan)
        if mode == 'reference':
            # Interpolate only between adjacent finite measurements: never bridge a missing sample.
            for j in range(len(gx) - 1):
                if np.isfinite(gz[j:j+2]).all():
                    mask = (x >= gx[j]) & (x <= gx[j+1])
                    row[mask] = np.interp(x[mask], gx[j:j+2], gz[j:j+2])
        indices = np.searchsorted(x, gx)
        for j, index in enumerate(indices):
            if index < len(x) and x[index] == gx[j]:
                row[index] = gz[j]
        rows.append(row)
    order = np.argsort([r['sweep'] for r in records])
    signal = np.array(rows)[order]
    if recipe['missing'] == 'reject' and not np.isfinite(signal).all():
        raise ValueError('Missing signal measurements or uncovered X coordinates. Choose gaps explicitly to retain them.')
    from copy import deepcopy
    return SpectrumMap(x, np.array([records[i]['sweep'] for i in order]), signal,
                       units[0], [records[i] for i in order], deepcopy(recipe))
