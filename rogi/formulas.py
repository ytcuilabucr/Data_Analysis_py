"""New columns computed from a typed formula over existing columns (no Qt).

Formulas are parsed with ast and evaluated by a small interpreter that only
knows arithmetic, numbers, columns and the functions below; nothing reaches
Python's eval. A column is referenced as [Column name], as c1, c2, … by
position, or by its bare name when that name is a plain identifier.
Missing inputs give missing results, and so do results that are not finite
(division by zero, log of a negative): they are counted, never stored as inf.
"""
import ast
import operator
import re
from copy import deepcopy

import numpy as np

from .units import infer_unit, normalize_unit


def _reduce(nan_function):
    def reduce(values):
        values = np.asarray(values, dtype=float)
        if not np.isfinite(values).any():
            return np.nan
        return nan_function(values)
    return reduce


def _extreme(elementwise, nan_function):
    # One argument is the column's extreme; two compare row by row.
    def extreme(*values):
        if len(values) == 1:
            return _reduce(nan_function)(values[0])
        if len(values) == 2:
            return elementwise(*values)
        raise ValueError('min and max take one column, or two values to compare row by row.')
    return extreme


FUNCTIONS = {
    'sqrt': np.sqrt, 'exp': np.exp, 'log': np.log, 'ln': np.log, 'log10': np.log10, 'log2': np.log2,
    'abs': np.abs, 'sign': np.sign, 'floor': np.floor, 'ceil': np.ceil, 'round': np.round,
    'sin': np.sin, 'cos': np.cos, 'tan': np.tan, 'asin': np.arcsin, 'acos': np.arccos, 'atan': np.arctan,
    'atan2': np.arctan2, 'sinh': np.sinh, 'cosh': np.cosh, 'tanh': np.tanh, 'hypot': np.hypot,
    'min': _extreme(np.fmin, np.nanmin), 'max': _extreme(np.fmax, np.nanmax),
    'mean': _reduce(np.nanmean), 'median': _reduce(np.nanmedian), 'std': _reduce(lambda v: np.nanstd(v, ddof=1)),
    'sum': _reduce(np.nansum),
}
CONSTANTS = {'pi': np.float64(np.pi), 'e': np.float64(np.e)}
BINARY = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
          ast.Div: operator.truediv, ast.Pow: operator.pow, ast.Mod: np.fmod}
UNARY = {ast.USub: operator.neg, ast.UAdd: operator.pos}
BRACKETED = re.compile(r'\[([^\[\]]*)\]')
POSITIONAL = re.compile(r'c([1-9][0-9]*)')
HELP = ('Use + - * / and ^ or ** for powers, numbers like 1.5e-3, and columns as [Column name] '
        'or c1, c2, …. Functions: ' + ', '.join(sorted(FUNCTIONS)) + '; constants pi, e; row is the row number.')


def _parse(dataset, formula):
    """Syntax tree plus the column index behind each placeholder name."""
    text = str(formula).strip()
    if not text:
        raise ValueError('Enter a formula.')
    references = {}
    def bracket(match):
        name = match.group(1).strip()
        if name not in dataset.columns:
            raise ValueError(f'No column named [{name}].')
        placeholder = f'_column_{dataset.columns.index(name)}'
        references[placeholder] = dataset.columns.index(name)
        return f' {placeholder} '
    text = BRACKETED.sub(bracket, text)
    if '[' in text or ']' in text:
        raise ValueError('Unmatched [ or ] in the formula.')
    try:
        tree = ast.parse(text.replace('^', '**').strip(), mode='eval')
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        raise ValueError('The formula is not valid. ' + HELP) from None
    return tree, references


def _column(dataset, name, references):
    """Index of the column a name refers to, or None."""
    if name in references:
        return references[name]
    if name in dataset.columns:
        return dataset.columns.index(name)
    match = POSITIONAL.fullmatch(name)
    if match:
        index = int(match.group(1)) - 1
        if index >= len(dataset.columns):
            raise ValueError(f'{name} does not exist: this dataset has {len(dataset.columns)} columns.')
        return index
    return None


def _name(dataset, name, references, used):
    index = _column(dataset, name, references)
    if index is not None:
        used.add(index)
        return dataset.values[:, index]
    if name == 'row':
        return np.arange(1., len(dataset.values) + 1)
    if name in CONSTANTS:
        return CONSTANTS[name]
    if name in FUNCTIONS:
        raise ValueError(f'{name} is a function: write {name}(…).')
    raise ValueError(f'Unknown name {name!r}. Put column names with spaces or symbols in brackets, '
                     'for example [Current (A)].')


def _evaluate(node, dataset, references, used):
    if isinstance(node, ast.Expression):
        return _evaluate(node.body, dataset, references, used)
    if isinstance(node, ast.Constant) and type(node.value) in (int, float):
        # NumPy scalars give inf/nan for 1/0 or overflow, as columns do, instead of raising.
        try:
            return np.float64(node.value)
        except OverflowError:
            raise ValueError('A number in the formula is too large.') from None
    if isinstance(node, ast.Name):
        return _name(dataset, node.id, references, used)
    if isinstance(node, ast.BinOp) and type(node.op) in BINARY:
        return BINARY[type(node.op)](_evaluate(node.left, dataset, references, used),
                                     _evaluate(node.right, dataset, references, used))
    if isinstance(node, ast.UnaryOp) and type(node.op) in UNARY:
        return UNARY[type(node.op)](_evaluate(node.operand, dataset, references, used))
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in FUNCTIONS:
            name = node.func.id if isinstance(node.func, ast.Name) else 'that'
            raise ValueError(f'Unknown function {name}. Available: {", ".join(sorted(FUNCTIONS))}.')
        if node.keywords or not node.args:
            raise ValueError(f'{node.func.id} takes plain values, for example {node.func.id}(c2).')
        arguments = [_evaluate(argument, dataset, references, used) for argument in node.args]
        try:
            return FUNCTIONS[node.func.id](*arguments)
        except TypeError:
            raise ValueError(f'Wrong number of values for {node.func.id}.') from None
    raise ValueError('Only arithmetic, numbers, columns and the listed functions are allowed. ' + HELP)


def evaluate(dataset, formula):
    """Values of the formula on every row, and how many rows came out missing
    although none of the columns it uses is missing there."""
    tree, references = _parse(dataset, formula)
    used = set()
    with np.errstate(all='ignore'):
        try:
            result = _evaluate(tree, dataset, references, used)
        except RecursionError:
            raise ValueError('The formula is nested too deeply.') from None
        values = np.broadcast_to(np.asarray(result, dtype=float), (len(dataset.values),)).copy()
    complete = np.isfinite(dataset.values[:, sorted(used)]).all(axis=1)
    invalid = int((complete & ~np.isfinite(values)).sum())
    values[~np.isfinite(values)] = np.nan
    return values, invalid


def formula_column(dataset, name, formula, unit=None):
    """Checked column for add_column: name, unit, values and a provenance record."""
    values, invalid = evaluate(dataset, formula)
    name = str(name).strip()
    if not name:
        raise ValueError('Enter a name for the new column.')
    if name in dataset.columns:
        raise ValueError(f'A column named {name} already exists.')
    unit = infer_unit(name) if unit is None or not str(unit).strip() else normalize_unit(unit)
    record = dict(column=name, formula=str(formula).strip(), unit=unit, revision=dataset.revision)
    return dict(name=name, unit=unit, values=values, invalid=invalid, record=record)


def add_column(dataset, column):
    """Append a formula column to an editable dataset; existing cells and fits are untouched."""
    if dataset.raw:
        raise ValueError('Raw data is read-only. Create an editable copy first.')
    dataset.values = np.column_stack([dataset.values, column['values']])
    dataset.columns = dataset.columns + [column['name']]
    dataset.column_units = dataset.column_units + [column['unit']]
    dataset.formulas = dataset.formulas + [deepcopy(column['record'])]


def remove_last_column(dataset, column):
    """Undo add_column."""
    if dataset.columns[-1] != column['name']:
        raise ValueError('The formula column is no longer the last column.')
    dataset.values = np.ascontiguousarray(dataset.values[:, :-1])
    dataset.columns = dataset.columns[:-1]
    dataset.column_units = dataset.column_units[:-1]
    dataset.formulas = [r for r in dataset.formulas if r != column['record']]
    dataset.xcol, dataset.ycol = (min(i, len(dataset.columns) - 1) for i in (dataset.xcol, dataset.ycol))


def validate_formulas(dataset):
    if (not isinstance(dataset.formulas, list)
            or any(not isinstance(r, dict) or set(r) != {'column', 'formula', 'unit', 'revision'}
                   or not all(isinstance(r[k], str) for k in ('column', 'formula', 'unit'))
                   or type(r['revision']) is not int for r in dataset.formulas)):
        raise ValueError('Invalid formula column records.')
