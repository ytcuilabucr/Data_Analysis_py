"""Fitting controls, result presentation and background fit worker."""
import numpy as np
from PySide6 import QtCore as C, QtWidgets as W
from .core import fit_dataset


class FitWorker(C.QThread):
    result = C.Signal(object, object)
    failed = C.Signal(str)

    def __init__(self, dataset, model, lower, upper, exclude, parent=None):
        super().__init__(parent)
        self.dataset, self.args = dataset, (model, lower, upper, exclude)

    def run(self):
        try:
            self.result.emit(self.dataset, fit_dataset(self.dataset, *self.args))
        except Exception as error:
            self.failed.emit(str(error))



class FittingPanel(W.QWidget):
    drag_changed = C.Signal(bool)
    fit_requested = C.Signal()

    def __init__(self):
        super().__init__()
        fit_layout = W.QVBoxLayout(self)
        fit_layout.setContentsMargins(0, 0, 0, 0)
        self.hide()
        self.model = W.QComboBox()
        self.model.addItems(['Linear', 'Gaussian'])
        self.lower, self.upper = W.QLineEdit(), W.QLineEdit()
        fitform = W.QFormLayout()
        fitform.addRow("Model", self.model)
        fitform.addRow("Range minimum", self.lower)
        fitform.addRow("Range maximum", self.upper)
        fit_layout.addLayout(fitform)
        self.drag = W.QCheckBox("Drag to select range (disable pan/zoom)")
        self.drag.toggled.connect(self.drag_changed.emit)
        fit_layout.addWidget(self.drag)
        self.exclude = W.QCheckBox("Exclude rows with missing X/Y")
        fit_layout.addWidget(self.exclude)
        self.fitbutton = W.QPushButton("Fit selected dataset")
        self.fitbutton.clicked.connect(self.fit_requested.emit)
        fit_layout.addWidget(self.fitbutton)
        self.result = W.QPlainTextEdit()
        self.result.setReadOnly(True)
        fit_layout.addWidget(self.result)


    def show_result(self, d):
        if not d or not d.fit:
            self.result.setPlainText("No fit. Linear: y = slope*x + intercept\n\nGaussian: y = baseline + amplitude*exp(-0.5*((x-center)/sigma)^2)\n\nUnweighted least squares; uncertainties assume independent, equal-variance Y errors and exact X. See README.")
            return
        f = d.fit
        lines = [f"{f['model']} — revision {f['revision']}", f"X: {d.columns[f['xcol']]} / Y: {d.columns[f['ycol']]}", f"Range: [{f['lower']:g}, {f['upper']:g}]", f"Points: {len(f['x'])}; missing excluded: {f['excluded_missing']}"]
        for name, value in f['parameters'].items():
            error = f['errors'][name]
            lines.append(f"{name} = {value:.8g} ± {error:.4g}" if error is not None else f"{name} = {value:.8g} (uncertainty unavailable)")
        lines += [f"RMSE: {f['rmse']:.6g}; dof: {f['dof']}", "± denotes approximate 1σ standard errors.", f['warning']]
        if (f['xcol'], f['ycol']) != (d.xcol, d.ycol):
            lines.append("Fit uses other columns; its curve is hidden.")
        self.result.setPlainText('\n'.join(lines))


    def reset_fit_range(self, dataset, restore_fit=False):
        finite_x = dataset.values[:, dataset.xcol]
        finite_x = finite_x[np.isfinite(finite_x)]
        if restore_fit and dataset.fit and dataset.fit['xcol'] == dataset.xcol:
            lower, upper = dataset.fit['lower'], dataset.fit['upper']
        elif finite_x.size:
            lower, upper = np.min(finite_x), np.max(finite_x)
        else:
            self.lower.clear()
            self.upper.clear()
            return
        self.lower.setText(str(lower))
        self.upper.setText(str(upper))


    def range_selected(self, lower, upper):
        if lower < upper:
            self.lower.setText(f"{lower:.12g}")
            self.upper.setText(f"{upper:.12g}")

