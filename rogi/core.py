"""Numerical operations; deliberately independent of Qt."""
from dataclasses import dataclass, field
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

    def __post_init__(self):
        self.values = np.array(self.values, dtype=float, copy=True)
        if self.values.ndim != 2 or self.values.shape[1] != len(self.columns):
            raise ValueError("Dataset shape does not match its columns.")
        if not self.values.shape[0] or len(self.columns) < 2:
            raise ValueError("A dataset needs at least one row and two columns.")
        if np.isinf(self.values).any():
            raise ValueError("Infinite values are not supported; use missing cells instead.")
        self.values.setflags(write=not self.raw)

    def derived(self):
        return Dataset(self.name + " (edited copy)", self.columns.copy(), self.values,
                       raw=False, parent=self.id, source=self.source,
                       xcol=self.xcol, ycol=self.ycol, style=self.style)

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


def parse_text(text, delimiter=",", header=True, selected=None, name="Imported data", source=""):
    rows = list(csv.reader(io.StringIO(text), delimiter=delimiter, strict=True))
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
