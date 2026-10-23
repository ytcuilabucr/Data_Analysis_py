"""Column units: one stored unit per column, one label format, SI-prefix scaling only (no Qt).

A unit is plain text; '' means unknown and '1' means dimensionless. Column names
keep whatever the file said; a trailing "(unit)" in a name is display text only.
"""
import re
import numpy as np

# Trailing parentheses that name a scan direction, not a unit.
NOT_UNITS = {'forward', 'backward', 'trace', 'retrace'}
# One nesting level, so a derivative's "Result ((V)/(s))" names "(V)/(s)".
TRAILING = re.compile(r'\s*\(((?:[^()]|\([^()]*\))+)\)\s*$')
QUOTIENT = re.compile(r'\(([^()/\s]+)\)/\(([^()/\s]+)\)')

# Powers of ten; factors come from exponent differences, so 1 nA is exactly 1000 pA.
PREFIXES = {'Y': 24, 'Z': 21, 'E': 18, 'P': 15, 'T': 12, 'G': 9, 'M': 6, 'k': 3, '': 0, 'c': -2,
            'm': -3, 'µ': -6, 'n': -9, 'p': -12, 'f': -15, 'a': -18, 'z': -21, 'y': -24}
BASES = {'m', 's', 'A', 'V', 'W', 'Ω', 'Hz', 'F', 'H', 'T', 'K', 'N', 'Pa', 'J', 'C', 'S',
         'eV', 'g', 'Wb', 'L', 'mol', 'cd', 'rad'}


def normalize_unit(text):
    """Canonical spelling: trimmed, µ for micro, Ω for ohm. Other text is kept as typed."""
    unit = ' '.join(str(text).split())
    unit = unit.replace('μ', 'µ').replace('~m', 'µm')
    unit = re.sub(r'(?<![A-Za-z])([A-Za-z]?)[Oo]hms?(?![A-Za-z])', r'\1Ω', unit)
    # A leading u is micro only when the rest is a known base unit (um, uA, us).
    return re.sub(r'(?<![A-Za-z])u(?=(' + '|'.join(sorted(BASES, key=len, reverse=True)) + r')(?![A-Za-z]))',
                  'µ', unit)


def infer_unit(name):
    """Unit named by a trailing "(unit)" in a column name, or '' when none."""
    match = TRAILING.search(name)
    if not match or match.group(1).strip().lower() in NOT_UNITS:
        return ''
    return normalize_unit(match.group(1))


def base_name(name):
    """Column name without the trailing unit text that infer_unit recognizes."""
    return TRAILING.sub('', name) if infer_unit(name) else name


def display_unit(unit):
    """Reading form: '1' is dimensionless and simple quotients drop their brackets."""
    if unit == '1':
        return 'dimensionless'
    match = QUOTIENT.fullmatch(unit)
    return f'{match[1]}/{match[2]}' if match else unit


def axis_label(name, unit, unknown=''):
    """"Name (unit)". Unknown units are left out unless unknown text is given."""
    shown = display_unit(unit) or unknown
    base = base_name(name)
    return f'{base} ({shown})' if shown else base


def column_unit(dataset, index):
    return dataset.column_units[index] if dataset.column_units else infer_unit(dataset.columns[index])


def column_label(dataset, index, unknown=''):
    return axis_label(dataset.columns[index], column_unit(dataset, index), unknown)


def custom_label(text, units):
    """A typed axis label keeps the axis unit unless the text already ends in brackets."""
    text = text.strip()
    known = [u for u in dict.fromkeys(units) if u]
    if len(known) != 1 or len(set(units)) != 1 or text.endswith((')', ']')):
        return text
    return f'{text} ({display_unit(known[0])})'


def _split(unit):
    if unit in BASES:
        return '', unit
    if len(unit) > 1 and unit[0] in PREFIXES and unit[1:] in BASES:
        return unit[0], unit[1:]
    return None


def _terms(unit):
    """Numerator and optional denominator, accepting the '(V)/(s)' form derivatives emit."""
    parts = [p.strip().removeprefix('(').removesuffix(')').strip() for p in unit.split('/')]
    if len(parts) > 2 or any(_split(p) is None for p in parts):
        return None
    return [_split(p) for p in parts]


def conversion_factor(source, target):
    """Multiplier taking values in source to target when only SI prefixes differ."""
    source, target = normalize_unit(source), normalize_unit(target)
    if source == target:
        return 1.
    a, b = _terms(source) if source else None, _terms(target) if target else None
    if a is None or b is None or len(a) != len(b) or any(x[1] != y[1] for x, y in zip(a, b)):
        raise ValueError(f'Cannot convert {source or "an unknown unit"} to {target or "an unknown unit"}: '
                         'only SI prefix changes of the same unit are supported (for example nA → pA).')
    exponent = PREFIXES[a[0][0]] - PREFIXES[b[0][0]]
    if len(a) == 2:
        exponent -= PREFIXES[a[1][0]] - PREFIXES[b[1][0]]
    return 10. ** exponent


def unit_hint(unit_rows):
    """Advice for channels whose units disagree; names prefix-only differences."""
    for column in zip(*unit_rows):
        first = column[0]
        for unit in column[1:]:
            if unit != first:
                try:
                    conversion_factor(unit, first)
                except ValueError:
                    continue
                return (f'{display_unit(unit)} and {display_unit(first)} differ only by SI prefix: '
                        'use Organize → Edit units… to convert a copy.')
    return 'Use Organize → Edit units… to relabel or convert channel units.'


def renamed_column(name, unit):
    """Column name for converted values: the old trailing unit replaced, else kept."""
    return f'{base_name(name)} ({unit})' if infer_unit(name) else name


def converted_copy(dataset, units):
    """Editable copy whose changed columns are rescaled to the given units.

    Only SI prefixes may change. Column names that carried the old unit are
    renamed, so the copy can match channels already in the new unit.
    """
    units = [normalize_unit(u) for u in units]
    if len(units) != len(dataset.columns):
        raise ValueError('Give one unit per channel.')
    old = [column_unit(dataset, i) for i in range(len(dataset.columns))]
    changed = [i for i, (a, b) in enumerate(zip(old, units)) if a != b]
    if not changed:
        raise ValueError('Choose a new unit for at least one channel.')
    factors = {i: conversion_factor(old[i], units[i]) for i in changed}
    copy = dataset.derived()
    names = list(copy.columns)
    for i in changed:
        with_unit = renamed_column(names[i], units[i])
        if with_unit not in names:
            names[i] = with_unit
        with np.errstate(over='raise'):
            try:
                copy.values[:, i] *= factors[i]
            except FloatingPointError:
                raise ValueError(f'Converting {dataset.columns[i]} to {units[i]} overflows.') from None
    renames = dict(zip(copy.columns, names))
    for layout in copy.instrument_metadata.get('channels', []):
        layout['label'] = names[layout['signal_column']]
        layout['coordinate_names'] = [renames.get(n, n) for n in layout['coordinate_names']]
    copy.columns, copy.column_units = names, units
    copy.name = (f'{dataset.name} (converted: '
                 + ', '.join(f'{display_unit(old[i]) or "?"} → {display_unit(units[i])}' for i in changed) + ')')
    return copy
