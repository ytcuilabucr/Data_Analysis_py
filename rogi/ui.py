"""Qt desktop presentation. Numerical routines live in core.py."""
import csv
import io
import sys
from pathlib import Path
import numpy as np
from PySide6 import QtCore as C, QtWidgets as W
from matplotlib.figure import Figure
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.widgets import SpanSelector
from .core import Dataset, parse_text, fit_dataset, export_data, export_fit
from .project import save_project, load_project


class DataTable(C.QAbstractTableModel):
    edited = C.Signal()
    failed = C.Signal(str)

    def __init__(self, dataset):
        super().__init__()
        self.dataset = dataset

    def rowCount(self, parent=C.QModelIndex()):
        return 0 if parent.isValid() else len(self.dataset.values)

    def columnCount(self, parent=C.QModelIndex()):
        return 0 if parent.isValid() else len(self.dataset.columns)

    def data(self, index, role=C.Qt.ItemDataRole.DisplayRole):
        if index.isValid() and role in (C.Qt.ItemDataRole.DisplayRole, C.Qt.ItemDataRole.EditRole):
            value = self.dataset.values[index.row(), index.column()]
            return "" if np.isnan(value) else str(value)

    def headerData(self, section, orientation, role=C.Qt.ItemDataRole.DisplayRole):
        if role == C.Qt.ItemDataRole.DisplayRole:
            return self.dataset.columns[section] if orientation == C.Qt.Orientation.Horizontal else str(section+1)

    def flags(self, index):
        flags = super().flags(index)
        return flags if self.dataset.raw else flags | C.Qt.ItemFlag.ItemIsEditable

    def setData(self, index, value, role=C.Qt.ItemDataRole.EditRole):
        if role != C.Qt.ItemDataRole.EditRole or not index.isValid():
            return False
        try:
            self.dataset.edit(index.row(), index.column(), value)
        except ValueError as error:
            self.failed.emit(str(error))
            return False
        self.dataChanged.emit(index, index)
        self.edited.emit()
        return True


class ImportDialog(W.QDialog):
    def __init__(self, path, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Import preview — choose numeric columns")
        self.resize(800, 550)
        self.path = Path(path)
        self.text = self.path.read_text(encoding="utf-8-sig")
        self.dataset = None
        layout = W.QVBoxLayout(self)
        form = W.QHBoxLayout()
        self.delimiter = W.QComboBox()
        for label, value in [("Comma", ","), ("Tab", "\t"), ("Semicolon", ";")]:
            self.delimiter.addItem(label, value)
        if self.path.suffix.lower() in ('.tsv', '.txt'):
            self.delimiter.setCurrentIndex(1)
        self.header = W.QCheckBox("First row contains headers")
        self.header.setChecked(True)
        form.addWidget(self.delimiter)
        form.addWidget(self.header)
        layout.addLayout(form)
        layout.addWidget(W.QLabel("Preview: first 100 rows. Blank/NA/NaN/N/A cells remain missing.\nSelect at least two columns below; the complete source text is preserved."))
        self.preview = W.QTableWidget()
        self.preview.setEditTriggers(W.QAbstractItemView.EditTrigger.NoEditTriggers)
        layout.addWidget(self.preview)
        self.columns = W.QListWidget()
        self.columns.setMaximumHeight(120)
        layout.addWidget(self.columns)
        self.message = W.QLabel()
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        buttons = W.QDialogButtonBox(W.QDialogButtonBox.StandardButton.Ok | W.QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.import_data)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.delimiter.currentIndexChanged.connect(self.refresh)
        self.header.toggled.connect(self.refresh)
        self.refresh()

    def refresh(self):
        self.columns.clear()
        self.preview.clear()
        try:
            reader = csv.reader(io.StringIO(self.text), delimiter=self.delimiter.currentData(), strict=True)
            rows = []
            for i, row in enumerate(reader):
                if i >= 101:
                    break
                rows.append(row)
            if not rows:
                raise ValueError("The file is empty.")
            names = rows[0] if self.header.isChecked() else [f"Column {i+1}" for i in range(len(rows[0]))]
            body = rows[1:] if self.header.isChecked() else rows[:100]
            self.preview.setColumnCount(len(names))
            self.preview.setHorizontalHeaderLabels(names)
            self.preview.setRowCount(len(body))
            for r, row in enumerate(body):
                for c, value in enumerate(row[:len(names)]):
                    self.preview.setItem(r, c, W.QTableWidgetItem(value))
            for name in names:
                item = W.QListWidgetItem(name, self.columns)
                item.setFlags(item.flags() | C.Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(C.Qt.CheckState.Checked)
            self.message.setText("All rows will be validated when you import.")
        except (ValueError, csv.Error) as error:
            self.message.setText(str(error))

    def import_data(self):
        try:
            selected = [i for i in range(self.columns.count()) if self.columns.item(i).checkState() == C.Qt.CheckState.Checked]
            self.dataset = parse_text(self.text, self.delimiter.currentData(), self.header.isChecked(), selected,
                                      self.path.stem, str(self.path))
            self.accept()
        except (ValueError, csv.Error) as error:
            self.message.setText(str(error))


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


class MainWindow(W.QMainWindow):
    def __init__(self):
        super().__init__()
        self.datasets = []
        self.path = None
        self.dirty = False
        self.worker = None
        self.loading = False
        self.setWindowTitle("Rogi — Scientific Analysis")
        self.resize(1280, 850)
        toolbar = self.addToolBar("Project")
        for label, function in [("Import…", self.import_file), ("Open project…", self.open_project),
                                ("Save", self.save), ("Save as…", lambda: self.save(True)),
                                ("Editable copy", self.make_copy), ("Export data…", self.export_data),
                                ("Export fit…", self.export_fit), ("Export plot…", self.export_plot)]:
            action = toolbar.addAction(label)
            action.triggered.connect(lambda checked=False, fn=function: self.guard(fn))
        splitter = W.QSplitter()
        self.setCentralWidget(splitter)
        self.browser = W.QListWidget()
        self.browser.setMinimumWidth(190)
        splitter.addWidget(self.browser)
        center = W.QSplitter(C.Qt.Orientation.Vertical)
        splitter.addWidget(center)
        plot_widget = W.QWidget()
        plot_layout = W.QVBoxLayout(plot_widget)
        self.figure = Figure(figsize=(8, 6), layout='constrained')
        self.ax, self.resax = self.figure.subplots(2, 1, sharex=True, gridspec_kw={'height_ratios': [3, 1]})
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.navigation = NavigationToolbar2QT(self.canvas, self)
        plot_layout.addWidget(self.navigation)
        plot_layout.addWidget(self.canvas)
        center.addWidget(plot_widget)
        self.table = W.QTableView()
        center.addWidget(self.table)
        center.setSizes([580, 220])
        panel = W.QWidget()
        panel.setMaximumWidth(320)
        layout = W.QVBoxLayout(panel)
        splitter.addWidget(panel)
        splitter.setSizes([200, 780, 300])
        self.info = W.QLabel("Import a CSV or tab-delimited file to begin.")
        self.info.setWordWrap(True)
        layout.addWidget(self.info)
        form = W.QFormLayout()
        self.x = W.QComboBox()
        self.y = W.QComboBox()
        self.style = W.QComboBox()
        self.style.addItems(['Line', 'Scatter'])
        self.title = W.QLineEdit()
        self.xlabel = W.QLineEdit()
        self.ylabel = W.QLineEdit()
        for label, widget in [("X column", self.x), ("Y column", self.y), ("Style", self.style),
                              ("Plot title", self.title), ("X label", self.xlabel), ("Y label", self.ylabel)]:
            form.addRow(label, widget)
        layout.addLayout(form)
        layout.addWidget(W.QLabel("Checked datasets are overlaid.\nSelect a dataset to inspect or fit it."))
        self.model = W.QComboBox()
        self.model.addItems(['Linear', 'Gaussian'])
        self.lower, self.upper = W.QLineEdit(), W.QLineEdit()
        fitform = W.QFormLayout()
        fitform.addRow("Model", self.model)
        fitform.addRow("Range minimum", self.lower)
        fitform.addRow("Range maximum", self.upper)
        layout.addLayout(fitform)
        self.drag = W.QCheckBox("Drag to select range (disable pan/zoom)")
        self.drag.toggled.connect(self.toggle_span)
        layout.addWidget(self.drag)
        self.exclude = W.QCheckBox("Exclude rows with missing X/Y")
        layout.addWidget(self.exclude)
        self.fitbutton = W.QPushButton("Fit selected dataset")
        self.fitbutton.clicked.connect(lambda: self.guard(self.start_fit))
        layout.addWidget(self.fitbutton)
        self.result = W.QPlainTextEdit()
        self.result.setReadOnly(True)
        layout.addWidget(self.result)
        self.browser.currentRowChanged.connect(self.select)
        self.browser.itemChanged.connect(self.visibility)
        for combo in (self.x, self.y, self.style):
            combo.currentIndexChanged.connect(self.plot_options)
        for entry in (self.title, self.xlabel, self.ylabel):
            entry.editingFinished.connect(self.labels_changed)
        self.redraw()

    def guard(self, function):
        try:
            return function()
        except (ValueError, OSError, csv.Error, UnicodeError) as error:
            self.error(str(error))
            return False

    def error(self, text):
        W.QMessageBox.warning(self, "Rogi", text)

    def current(self):
        row = self.browser.currentRow()
        return self.datasets[row] if 0 <= row < len(self.datasets) else None

    def changed(self):
        self.dirty = True
        self.setWindowTitle(f"Rogi — {self.path.name if self.path else 'Untitled'} *")

    def add_dataset(self, dataset):
        self.datasets.append(dataset)
        self.loading = True
        item = W.QListWidgetItem(dataset.name + (" [raw]" if dataset.raw else " [derived]"), self.browser)
        item.setFlags(item.flags() | C.Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(C.Qt.CheckState.Checked if dataset.visible else C.Qt.CheckState.Unchecked)
        self.loading = False
        self.browser.setCurrentRow(len(self.datasets)-1)
        self.changed()
        self.redraw()

    def import_file(self):
        path, _ = W.QFileDialog.getOpenFileName(self, "Import numeric data", "", "Text data (*.csv *.tsv *.txt);;All files (*)")
        if path:
            dialog = ImportDialog(path, self)
            if dialog.exec():
                self.add_dataset(dialog.dataset)

    def select(self, row):
        dataset = self.current()
        if dataset is None:
            return
        self.loading = True
        for combo, index in [(self.x, dataset.xcol), (self.y, dataset.ycol)]:
            combo.clear()
            combo.addItems(dataset.columns)
            combo.setCurrentIndex(index)
        self.style.setCurrentText(dataset.style)
        table_model = DataTable(dataset)
        table_model.edited.connect(self.edited)
        table_model.failed.connect(self.error)
        self.table_model = table_model
        self.table.setModel(table_model)
        missing = int(np.isnan(dataset.values).sum())
        self.info.setText(f"{dataset.name}\n{len(dataset.values)} rows × {len(dataset.columns)} columns; {missing} missing cells\n"
                          + ("Raw data: read-only" if dataset.raw else f"Derived data: revision {dataset.revision}; parent {dataset.parent}"))
        finite_x = dataset.values[:, dataset.xcol]
        finite_x = finite_x[np.isfinite(finite_x)]
        self.lower.setText(str(dataset.fit['lower'] if dataset.fit else np.min(finite_x)) if finite_x.size else "")
        self.upper.setText(str(dataset.fit['upper'] if dataset.fit else np.max(finite_x)) if finite_x.size else "")
        if dataset.fit:
            self.model.setCurrentText(dataset.fit['model'])
        self.loading = False
        self.show_result()
        self.redraw()

    def edited(self):
        self.changed()
        self.select(self.browser.currentRow())

    def make_copy(self):
        if self.current():
            self.add_dataset(self.current().derived())

    def visibility(self, item):
        if not self.loading:
            self.datasets[self.browser.row(item)].visible = item.checkState() == C.Qt.CheckState.Checked
            self.changed()
            self.redraw()

    def plot_options(self):
        if self.loading or not self.current():
            return
        d = self.current()
        d.xcol, d.ycol, d.style = self.x.currentIndex(), self.y.currentIndex(), self.style.currentText()
        self.changed()
        self.select(self.browser.currentRow())

    def labels_changed(self):
        self.changed()
        self.redraw()

    def toggle_span(self, active):
        if hasattr(self, 'span'):
            self.span.set_active(active)

    def range_selected(self, lower, upper):
        if lower < upper:
            self.lower.setText(f"{lower:.12g}")
            self.upper.setText(f"{upper:.12g}")

    def redraw(self):
        if hasattr(self, 'span'):
            self.span.disconnect_events()
        self.ax.clear()
        self.resax.clear()
        for d in self.datasets:
            if not d.visible:
                continue
            x, y = d.values[:, d.xcol], d.values[:, d.ycol]
            if d.style == 'Scatter':
                self.ax.scatter(x, y, s=14, label=d.name)
            else:
                self.ax.plot(x, y, label=d.name)
            if d.fit and (d.fit['xcol'], d.fit['ycol']) == (d.xcol, d.ycol):
                fit = d.fit
                order = np.argsort(fit['x'])
                self.ax.plot(np.array(fit['x'])[order], np.array(fit['predicted'])[order], '--', label=d.name + ' fit')
                self.resax.scatter(fit['x'], fit['residuals'], s=10, label=d.name)
        self.ax.set_title(self.title.text())
        self.ax.set_ylabel(self.ylabel.text() or "Y")
        self.resax.set_xlabel(self.xlabel.text() or "X")
        self.resax.set_ylabel("Residual")
        self.resax.axhline(0, color='gray', linewidth=0.8)
        for ax in (self.ax, self.resax):
            ax.grid(True, alpha=0.2)
            if ax.get_legend_handles_labels()[0]:
                ax.legend(fontsize=8)
        self.span = SpanSelector(self.ax, self.range_selected, 'horizontal', useblit=True,
                                 interactive=True, props=dict(alpha=0.2, facecolor='tab:blue'))
        self.span.set_active(self.drag.isChecked())
        self.canvas.draw_idle()

    def show_result(self):
        d = self.current()
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

    def start_fit(self):
        if not self.current():
            raise ValueError("Import or select a dataset first.")
        lower, upper = float(self.lower.text()), float(self.upper.text())
        self.worker = FitWorker(self.current(), self.model.currentText(), lower, upper, self.exclude.isChecked(), self)
        self.worker.result.connect(self.fit_ready)
        self.worker.failed.connect(self.error)
        self.worker.finished.connect(self.fit_finished)
        self.centralWidget().setEnabled(False)
        self.findChild(W.QToolBar).setEnabled(False)
        self.statusBar().showMessage("Fitting…")
        self.worker.start()

    def fit_ready(self, dataset, fit):
        dataset.fit = fit
        self.changed()
        self.show_result()
        self.redraw()

    def fit_finished(self):
        self.centralWidget().setEnabled(True)
        self.findChild(W.QToolBar).setEnabled(True)
        self.statusBar().showMessage("Fit operation finished", 4000)

    def settings(self):
        return dict(title=self.title.text(), xlabel=self.xlabel.text(), ylabel=self.ylabel.text(),
                    xlim=list(self.ax.get_xlim()), ylim=list(self.ax.get_ylim()))

    def save(self, save_as=False):
        path = self.path
        if path is None or save_as:
            name, _ = W.QFileDialog.getSaveFileName(self, "Save project", str(path or 'analysis.rogi.json'), "Rogi project (*.rogi.json)")
            if not name:
                return False
            path = Path(name)
        save_project(path, self.datasets, self.settings())
        self.path, self.dirty = Path(path), False
        self.setWindowTitle(f"Rogi — {self.path.name}")
        return True

    def confirm_discard(self):
        if not self.dirty:
            return True
        answer = W.QMessageBox.question(self, "Unsaved project", "Save changes before continuing?",
                                       W.QMessageBox.StandardButton.Save | W.QMessageBox.StandardButton.Discard | W.QMessageBox.StandardButton.Cancel)
        if answer == W.QMessageBox.StandardButton.Save:
            return bool(self.guard(self.save))
        return answer == W.QMessageBox.StandardButton.Discard

    def open_project(self):
        if not self.confirm_discard():
            return
        path, _ = W.QFileDialog.getOpenFileName(self, "Open project", "", "Rogi project (*.json)")
        if path:
            datasets, settings = load_project(path)
            self.datasets = []
            self.browser.clear()
            self.table.setModel(None)
            self.result.clear()
            for field in ('title', 'xlabel', 'ylabel'):
                getattr(self, field).setText(settings.get(field, ''))
            for d in datasets:
                self.add_dataset(d)
            self.redraw()
            for key in ('xlim', 'ylim'):
                if key in settings:
                    getattr(self.ax, 'set_'+key)(settings[key])
            self.path, self.dirty = Path(path), False
            self.setWindowTitle(f"Rogi — {self.path.name}")
            self.canvas.draw_idle()

    def export_data(self):
        if not self.current():
            raise ValueError("Select a dataset first.")
        path, _ = W.QFileDialog.getSaveFileName(self, "Export selected dataset", "data.csv", "CSV (*.csv)")
        if path:
            export_data(self.current(), path)

    def export_fit(self):
        if not self.current() or not self.current().fit:
            raise ValueError("Fit a dataset first.")
        path, _ = W.QFileDialog.getSaveFileName(self, "Export parameters and residuals", "fit.csv", "CSV (*.csv)")
        if path:
            export_fit(self.current(), path)

    def export_plot(self):
        path, chosen = W.QFileDialog.getSaveFileName(self, "Export plot and residuals", "plot.png", "PNG (*.png);;SVG (*.svg)")
        if path:
            if not Path(path).suffix:
                path += '.svg' if chosen.startswith('SVG') else '.png'
            if Path(path).suffix.lower() not in ('.png', '.svg'):
                raise ValueError("Choose a .png or .svg filename.")
            self.figure.savefig(path, dpi=180)

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            self.statusBar().showMessage("Wait for the current fit to finish before closing.")
            event.ignore()
        elif self.confirm_discard():
            event.accept()
        else:
            event.ignore()


def main():
    app = W.QApplication.instance() or W.QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
