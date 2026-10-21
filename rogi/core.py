"""Numerical operations; deliberately independent of Qt."""
from dataclasses import dataclass, field
from copy import deepcopy
from .metadata import attach_spectrum_metadata, validate_metadata
import csv
import io
import uuid
import warnings
from pathlib import Path

import numpy as np
from scipy.optimize import curve_fit, OptimizeWarning


@dataclass
class Dataset:
    name: str
    columns: list[str]
    values: np.ndarray
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    raw: bool = True
    source: str = ""
    source_text: str = ""
    parent: str | None = None
    revision: int = 0
    edits: list = field(default_factory=list)
    fit: dict | None = None
    xcol: int = 0
    ycol: int = 1
    visible: bool = True
    style: str = "Line"
    group: str = ""
    color: str = ""
    marker: str = ""
    instrument_metadata: dict = field(default_factory=dict)
    timestamps: list = field(default_factory=list)
    group_path: list = field(default_factory=list)

    favorite: bool = False
    tags: list[str] = field(default_factory=list)
    comments: str = ""

    column_units: list = field(default_factory=list)
    analysis: dict | None = None

    def __post_init__(self):
        if (type(self.favorite) is not bool or not isinstance(self.tags, list)
                or not all(isinstance(tag, str) for tag in self.tags)
                or not isinstance(self.comments, str)):
            raise ValueError("Invalid dataset annotations.")
        from .analysis import validate_analysis
        validate_analysis(self.analysis)
        if (not isinstance(self.column_units, list) or (self.column_units and len(self.column_units) != len(self.columns))
                or not all(isinstance(unit, str) for unit in self.column_units)):
            raise ValueError("Invalid column units.")
        if not isinstance(self.group, str):
            raise ValueError("Dataset group must be text.")
        if (not isinstance(self.group_path, list) or any(
                not isinstance(n, dict) or set(n) != {'field', 'value'}
                or (n['field'] is not None and not isinstance(n['field'], str))
                or (n['value'] is not None and not isinstance(n['value'], str)) for n in self.group_path)):
            raise ValueError('Invalid group path.')
        if self.group_path:
            from .grouping import path_label
            self.group = path_label(self.group_path)
        self.values = np.array(self.values, dtype=float, copy=True)
        if self.values.ndim != 2 or self.values.shape[1] != len(self.columns):
            raise ValueError("Dataset shape does not match its columns.")
        if not self.values.shape[0] or len(self.columns) < 2:
            raise ValueError("A dataset needs at least one row and two columns.")
        if np.isinf(self.values).any():
            raise ValueError("Infinite values are not supported; use missing cells instead.")
        self.values.setflags(write=not self.raw)
        validate_metadata(self)

    def derived(self):
        return Dataset(self.name + " (edited copy)", self.columns.copy(), self.values,
                       raw=False, parent=self.id, source=self.source,
                       favorite=self.favorite, tags=self.tags.copy(), comments=self.comments,
                       column_units=self.column_units.copy(), analysis=deepcopy(self.analysis),
                       xcol=self.xcol, ycol=self.ycol, style=self.style, group=self.group,
                       color=self.color, marker=self.marker,
                       group_path=deepcopy(self.group_path),
                       instrument_metadata=deepcopy(self.instrument_metadata), timestamps=deepcopy(self.timestamps))

    def edit(self, row, column, text):
        if self.raw:
            raise ValueError("Raw data is read-only. Create an editable copy first.")
        value = float(text) if str(text).strip() else np.nan
        if np.isinf(value):
            raise ValueError("Use a finite number or a blank for missing data.")
        old = self.values[row, column]
        self.values[row, column] = value
        self.edits.append(dict(row=row, column=column, old=None if np.isnan(old) else float(old),
                               new=None if np.isnan(value) else value))
        self.revision += 1
        self.fit = None


def remove_datasets(datasets, ids):
    """Return survivors, refusing removal that would orphan a retained copy."""
    ids = set(ids)
    dependents = [d for d in datasets if d.id not in ids and d.parent in ids]
    if dependents:
        raise ValueError("Cannot remove datasets referenced by remaining derived copies: "
                         + ", ".join(d.name for d in dependents)
                         + ". Keep the parent, or also select its derived copies for removal.")
    return [d for d in datasets if d.id not in ids]


def spectrum_table(text):
    """Return a numeric-channel TSV for sectioned instrument data, or None.

    The caller retains the original text, including metadata and timestamps.
    """
    lines = text.removeprefix('\ufeff').splitlines()
    marker = next((i for i, line in enumerate(lines) if line.strip() == '[Data]'), None)
    if marker is None:
        return None
    rows = [line.split('\t') for line in lines[marker + 1:] if line.strip()]
    if not rows:
        raise ValueError('The [Data] section is empty.')
    columns = rows[0]
    while columns and not columns[-1].strip():
        columns.pop()
    columns = [column.strip() for column in columns]
    for number, row in enumerate(rows[1:], start=1):
        while len(row) > len(columns) and not row[-1].strip():
            row.pop()
        if len(row) != len(columns):
            raise ValueError(f'[Data] row {number}: expected {len(columns)} fields, found {len(row)}.')
    # A text Time channel may appear anywhere. Keep numeric Time channels;
    # only omit the text representation when a numeric timestamp is present.
    selected = list(range(len(columns)))
    if 'Time_Timestamp' in columns:
        for index, column in enumerate(columns):
            if column != 'Time':
                continue
            try:
                for row in rows[1:]:
                    token = row[index].strip()
                    if token.lower() not in ('', 'na', 'nan', 'n/a'):
                        float(token)
            except ValueError:
                selected.remove(index)
    names = []
    for index in selected:
        base = columns[index] or f'Column {index + 1}'
        name, suffix = base, 2
        while name in names:
            name = f'{base} [{suffix}]'
            suffix += 1
        names.append(name)
    output = io.StringIO()
    writer = csv.writer(output, delimiter='\t')
    writer.writerow(names)
    for row in rows[1:]:
        writer.writerow([row[index] for index in selected])
    return output.getvalue()


def parse_dat(text, name='Imported data', source=''):
    """Parse a sectioned instrument DAT or a plain delimited DAT table."""
    table = spectrum_table(text)
    is_spectrum = table is not None
    delimiter = '\t'
    if table is None:
        table = text
        try:
            delimiter = csv.Sniffer().sniff(text[:65536], delimiters=',\t;').delimiter
        except csv.Error:
            pass
    dataset = parse_text(table, delimiter=delimiter, name=name, source=source)
    dataset.source_text = text
    if is_spectrum:
        attach_spectrum_metadata(dataset, text)
    return dataset


def parse_text(text, delimiter=",", header=True, selected=None, name="Imported data", source=""):
    rows = list(csv.reader(io.StringIO(text.removeprefix('\ufeff')), delimiter=delimiter, strict=True))
    if not rows:
        raise ValueError("The file is empty.")
    width = len(rows[0])
    columns = [c.strip() or f"Column {i+1}" for i, c in enumerate(rows[0])] if header else [f"Column {i+1}" for i in range(width)]
    if len(set(columns)) != width:
        raise ValueError("Column names must be unique.")
    selected = list(range(width)) if selected is None else list(selected)
    if len(selected) < 2 or len(set(selected)) != len(selected) or any(i < 0 or i >= width for i in selected):
        raise ValueError("Select at least two distinct columns.")
    values = []
    for line, row in enumerate(rows[1:] if header else rows, start=2 if header else 1):
        if len(row) != width:
            raise ValueError(f"Row {line}: expected {width} fields, found {len(row)}. Check delimiter/blank lines.")
        converted = []
        for col in selected:
            token = row[col].strip()
            try:
                value = np.nan if token.lower() in ("", "na", "nan", "n/a") else float(token)
                if np.isinf(value):
                    raise ValueError()
            except ValueError:
                raise ValueError(f"Row {line}, column {col+1}: {token!r} is not a finite number or missing value.") from None
            converted.append(value)
        values.append(converted)
    if not values:
        raise ValueError("The file contains no data rows.")
    return Dataset(name, [columns[i] for i in selected], np.array(values), source=source, source_text=text)


def linear(x, slope, intercept):
    return slope * x + intercept


def gaussian(x, baseline, amplitude, center, sigma):
    return baseline + amplitude * np.exp(-0.5 * ((x-center)/sigma)**2)


MODELS = {"Linear": (linear, ["slope", "intercept"]),
          "Gaussian": (gaussian, ["baseline", "amplitude", "center", "sigma"])}


def fit_dataset(dataset, model, lower, upper, exclude_missing=False):
    if model not in MODELS:
        raise ValueError("Unknown fit model.")
    if not np.isfinite([lower, upper]).all() or lower >= upper:
        raise ValueError("Fit bounds must be finite, with lower < upper.")
    if dataset.xcol == dataset.ycol:
        raise ValueError("Choose different X and Y columns.")
    x, y = dataset.values[:, dataset.xcol], dataset.values[:, dataset.ycol]
    finite = np.isfinite(x) & np.isfinite(y)
    missing = int((~finite).sum())
    if missing and not exclude_missing:
        raise ValueError(f"{missing} rows have missing X/Y. Explicitly enable exclusion before fitting.")
    mask = finite & (x >= lower) & (x <= upper)
    indices = np.flatnonzero(mask)
    x, y = x[mask], y[mask]
    function, names = MODELS[model]
    if len(x) <= len(names) or np.unique(x).size <= len(names):
        raise ValueError(f"{model} needs more than {len(names)} distinct X values in the range.")
    if model == "Linear":
        design = np.column_stack((x, np.ones(len(x))))
        params, _, rank, _ = np.linalg.lstsq(design, y, rcond=None)
        if rank < 2:
            raise ValueError("X values are too poorly scaled for a reliable linear fit.")
        residual = y - function(x, *params)
        inverse = np.linalg.pinv(design)
        covariance = (inverse @ inverse.T) * (residual @ residual) / (len(x)-2)
    else:
        baseline = float(np.median(y))
        peak = int(np.argmax(np.abs(y-baseline)))
        amplitude = float(y[peak]-baseline)
        if np.ptp(y) == 0:
            raise ValueError("A Gaussian peak cannot be identified in constant Y data.")
        span = float(np.ptp(x))
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", OptimizeWarning)
            try:
                params, covariance = curve_fit(function, x, y,
                    p0=[baseline, amplitude, float(x[peak]), span/6],
                    bounds=([-np.inf, -np.inf, -np.inf, np.finfo(float).eps * span],
                            [np.inf, np.inf, np.inf, np.inf]), maxfev=20000)
            except (RuntimeError, ValueError, FloatingPointError) as error:
                raise ValueError(f"Gaussian fit failed: {error}. Try a range containing the peak and both tails.") from error
        if caught:
            covariance[:] = np.nan
    predicted = function(x, *params)
    if not np.isfinite(params).all() or not np.isfinite(predicted).all():
        raise ValueError("Fit produced nonfinite values; adjust the range or data scale.")
    residual = y-predicted
    reliable = np.isfinite(covariance).all() and np.linalg.cond(covariance) < 1e14
    # Exact synthetic fits may have a zero covariance matrix.
    reliable = reliable or bool(np.all(covariance == 0))
    errors = np.sqrt(np.maximum(0, np.diag(covariance))) if reliable else [None]*len(names)
    return dict(model=model, parameters=dict(zip(names, map(float, params))),
                errors={n: None if e is None else float(e) for n, e in zip(names, errors)},
                covariance=covariance.tolist() if reliable else None,
                warning="" if reliable else "Parameter uncertainties unavailable or ill-conditioned.",
                lower=float(lower), upper=float(upper), xcol=dataset.xcol, ycol=dataset.ycol,
                revision=dataset.revision, excluded_missing=missing, rows=indices.tolist(),
                x=x.tolist(), observed=y.tolist(), predicted=predicted.tolist(), residuals=residual.tolist(),
                rmse=float(np.sqrt(np.mean(residual**2))), dof=len(x)-len(names))


def export_data(dataset, path):
    with Path(path).open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(dataset.columns)
        writer.writerows([["" if np.isnan(v) else v for v in row] for row in dataset.values])


def export_fit(dataset, path):
    if dataset.fit is None:
        raise ValueError("Fit this dataset before exporting results.")
    fit = dataset.fit
    with Path(path).open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["dataset", "model", "revision", "x_column", "y_column", "lower", "upper", "excluded_missing", "dof", "rmse"])
        writer.writerow([dataset.name, fit['model'], fit['revision'], dataset.columns[fit['xcol']], dataset.columns[fit['ycol']], fit['lower'], fit['upper'], fit['excluded_missing'], fit['dof'], fit['rmse']])
        writer.writerow(["parameter", "value", "standard_error"])
        for name, value in fit['parameters'].items():
            writer.writerow([name, value, fit['errors'][name]])
        writer.writerow(["source_row_1based", "x", "observed", "predicted", "residual"])
        writer.writerows(zip([r+1 for r in fit['rows']], fit['x'], fit['observed'], fit['predicted'], fit['residuals']))


def region_statistics(dataset, lower, upper, ylower=None, yupper=None, sample=True):
    """Summarize stored Y observations within inclusive numeric bounds.

    Missing X cannot be assigned to a region. Missing Y within the X interval
    is reported separately before optional Y bounds are applied.
    """
    bounds = [lower, upper]
    if (ylower is None) != (yupper is None):
        raise ValueError("Provide both Y bounds.")
    if ylower is not None:
        bounds += [ylower, yupper]
    if not np.isfinite(bounds).all() or lower > upper or (ylower is not None and ylower > yupper):
        raise ValueError("Region bounds must be finite, with minimum no greater than maximum.")
    x, y = dataset.values[:, dataset.xcol], dataset.values[:, dataset.ycol]
    in_x = np.isfinite(x) & (x >= lower) & (x <= upper)
    included = in_x & np.isfinite(y)
    if ylower is not None:
        included &= (y >= ylower) & (y <= yupper)
    values = y[included]
    n = len(values)
    result = dict(count=n, missing_x=int((~np.isfinite(x)).sum()),
                  missing_y=int((in_x & ~np.isfinite(y)).sum()),
                  rows=np.flatnonzero(included).tolist(), sample=sample)
    names = ('minimum', 'maximum', 'mean', 'median', 'std', 'variance', 'sem',
             'sum', 'rms', 'q1', 'q3')
    result.update(dict.fromkeys(names))
    if n:
        # Extended precision reduces overflow in intermediates for finite data.
        wide = values.astype(np.longdouble)
        with np.errstate(over='ignore', invalid='ignore'):
            variance = np.var(wide, ddof=1 if sample else 0) if n > int(sample) else np.nan
            std = np.sqrt(variance)
            computed = dict(minimum=np.min(wide), maximum=np.max(wide), mean=np.mean(wide),
                            median=np.median(wide), std=std, variance=variance,
                            sem=std / np.sqrt(n), sum=np.sum(wide),
                            rms=np.sqrt(np.mean(wide ** 2)),
                            q1=np.percentile(values, 25), q3=np.percentile(values, 75))
            for key, value in computed.items():
                number = float(value)
                result[key] = number if np.isfinite(number) else None
    return result
