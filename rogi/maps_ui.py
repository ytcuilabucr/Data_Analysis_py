"""Map setup, coordinate-aware rendering, cross-sections and export."""
import csv
from PySide6 import QtWidgets as W
from matplotlib.figure import Figure
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from .maps import assemble_map
from .screen import fit_to_screen
from .metadata import metadata_fields
from .grouping import field_labels


class MapDialog(W.QDialog):
    def __init__(self, datasets, parent=None, recipe=None):
        super().__init__(parent)
        self.sources = datasets
        self.result = None
        self.setWindowTitle('Assemble spectra into a 2D map')
        fit_to_screen(self, 1050, 850)
        layout = W.QVBoxLayout(self)
        form = W.QFormLayout()
        self.x, self.signal, self.sweep = W.QComboBox(), W.QComboBox(), W.QComboBox()
        channels = list(dict.fromkeys(c for d in datasets for c in d.columns))
        for combo in (self.x, self.signal):
            combo.addItem('Choose channel…', None)
            for channel in channels:
                combo.addItem(channel, channel)
        fields = sorted({k for d in datasets for k in metadata_fields(d)})
        labels = field_labels(fields)
        self.sweep.addItem('Choose metadata sweep coordinate…', None)
        for field in fields:
            self.sweep.addItem(labels[field], field)
            self.sweep.setItemData(self.sweep.count()-1, field, 3)
        self.alignment, self.missing, self.reference = W.QComboBox(), W.QComboBox(), W.QComboBox()
        for label, value in [('Choose alignment…', None), ('Require identical measured X grids', 'exact'),
                             ('Union of measured X coordinates (gaps)', 'union'),
                             ('Linear interpolation onto reference X (no extrapolation)', 'reference')]:
            self.alignment.addItem(label, value)
        self.missing.addItem('Reject missing measurements', 'reject')
        self.missing.addItem('Retain missing measurements as gaps', 'gaps')
        for d in datasets:
            self.reference.addItem(d.name, d.id)
        for label, widget in [('X channel', self.x), ('Signal channel', self.signal),
                              ('Sweep coordinate', self.sweep), ('X alignment', self.alignment),
                              ('Reference spectrum', self.reference), ('Missing data', self.missing)]:
            form.addRow(label, widget)
        layout.addLayout(form)
        self.dimensions = {}
        dimension_box = W.QGroupBox('Additional sweep dimensions — choose fixed values to resolve repeats')
        dimension_form = W.QFormLayout(dimension_box)
        for field in fields:
            values = sorted({metadata_fields(d)[field] for d in datasets if field in metadata_fields(d)})
            if len(values) < 2:
                continue
            combo = W.QComboBox()
            combo.addItem('All values', None)
            for value in values:
                combo.addItem(value, value)
            dimension_form.addRow(labels[field], combo)
            self.dimensions[field] = combo
            combo.currentIndexChanged.connect(self.invalidate)
        scroll = W.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(dimension_box)
        scroll.setMaximumHeight(150)
        layout.addWidget(scroll)
        self.figure = Figure(tight_layout=True)
        self.canvas = FigureCanvasQTAgg(self.figure)
        layout.addWidget(self.canvas, 1)
        sections = W.QHBoxLayout()
        self.section_axis, self.section_value = W.QComboBox(), W.QComboBox()
        self.section_axis.addItem('Signal vs X at sweep coordinate', 'sweep')
        self.section_axis.addItem('Signal vs sweep at X coordinate', 'x')
        sections.addWidget(self.section_axis)
        sections.addWidget(self.section_value)
        layout.addLayout(sections)
        self.status = W.QLabel('Select channels, an explicit metadata coordinate, and alignment. Units must be known and identical.')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        buttons = W.QHBoxLayout()
        self.result_buttons = []
        for label, callback in [('Assemble map', self.build), ('Save named view…', self.save_view),
                                ('Export map…', self.export_map), ('Export cross-section…', self.export_section),
                                ('Export figure…', self.export_figure), ('Close', self.accept)]:
            button = W.QPushButton(label)
            button.clicked.connect(callback)
            buttons.addWidget(button)
            if label not in ('Assemble map', 'Close'):
                self.result_buttons.append(button)
        layout.addLayout(buttons)
        for combo in (self.x, self.signal, self.sweep, self.alignment, self.missing, self.reference):
            combo.currentIndexChanged.connect(self.invalidate)
        self.sweep.currentIndexChanged.connect(self.update_dimensions)
        self.section_axis.currentIndexChanged.connect(self.update_sections)
        self.section_value.currentIndexChanged.connect(self.draw)
        self.invalidate()
        if recipe:
            for key in ('x', 'signal', 'sweep', 'alignment', 'missing', 'reference'):
                combo = getattr(self, key)
                combo.setCurrentIndex(combo.findData(recipe.get(key)))
            for field, value in recipe.get('filters', {}).items():
                if field in self.dimensions:
                    self.dimensions[field].setCurrentIndex(self.dimensions[field].findData(value))
            self.build()
            if self.result and recipe.get('section'):
                section = recipe['section']
                self.section_axis.setCurrentIndex(self.section_axis.findData(section['axis']))
                self.section_value.setCurrentIndex(min(section['index'], self.section_value.count() - 1))

    def update_dimensions(self):
        for field, combo in self.dimensions.items():
            combo.setEnabled(field != self.sweep.currentData())
            if not combo.isEnabled():
                combo.setCurrentIndex(0)

    def recipe(self):
        return dict(ids=[d.id for d in self.sources],
                    **{key: getattr(self, key).currentData() for key in
                       ('x', 'signal', 'sweep', 'alignment', 'missing', 'reference')},
                    filters={k: c.currentData() for k, c in self.dimensions.items() if c.currentData() is not None})

    def invalidate(self, *_):
        self.result = None
        self.figure.clear()
        self.canvas.draw_idle()
        for button in self.result_buttons:
            button.setEnabled(False)
        self.status.setText('Setup changed. Assemble to validate and display the map.')

    def build(self):
        self.invalidate()
        try:
            self.result = assemble_map(self.sources, self.recipe())
        except ValueError as error:
            self.status.setText(str(error))
            return
        for button in self.result_buttons:
            button.setEnabled(True)
        self.status.setText(f'{len(self.result.sweep)} spectra × {len(self.result.x)} X coordinates. '
                            'Measured coordinates are retained. NPZ export includes original samples and the alignment recipe.')
        self.update_sections()

    def update_sections(self):
        self.section_value.blockSignals(True)
        self.section_value.clear()
        if self.result:
            axis = self.section_axis.currentData()
            values = getattr(self.result, axis)
            unit = self.result.units[2 if axis == 'sweep' else 0]
            for value in values:
                self.section_value.addItem(f'{value:.12g} {unit}')
        self.section_value.blockSignals(False)
        self.draw()

    def draw(self, *_):
        if self.result is None:
            return
        r = self.result
        self.figure.clear()
        ax, section = self.figure.subplots(1, 2)
        mesh = ax.pcolormesh(r.x, r.sweep, r.signal, shading='nearest')
        self.figure.colorbar(mesh, ax=ax, label=f"{r.recipe['signal']} [{r.units[1]}]")
        ax.set_xlabel(f"{r.recipe['x']} [{r.units[0]}]")
        ax.set_ylabel(f"{r.recipe['sweep']} [{r.units[2]}]")
        axis, index = self.section_axis.currentData(), max(0, self.section_value.currentIndex())
        x, z = r.section(axis, index)
        section.plot(x, z, '.-')
        section.set_title(self.section_value.currentText())
        section.set_xlabel(ax.get_xlabel() if axis == 'sweep' else ax.get_ylabel())
        section.set_ylabel(f"{r.recipe['signal']} [{r.units[1]}]")
        if axis == 'sweep':
            ax.axhline(r.sweep[index], color='red')
        else:
            ax.axvline(r.x[index], color='red')
        self.canvas.draw_idle()

    def save_view(self):
        name, ok = W.QInputDialog.getText(self, 'Save map view', 'View name:')
        if ok:
            try:
                parent = self.parent()
                name = parent.view_name(name)
                from copy import deepcopy
                recipe = deepcopy(self.result.recipe)
                recipe['section'] = dict(axis=self.section_axis.currentData(),
                                         index=self.section_value.currentIndex())
                parent.saved_views[name] = dict(kind='spectrum_map', recipe=recipe)
                parent.refresh_saved_views_menu()
                parent.changed()
            except ValueError as error:
                self.status.setText(str(error))

    def export_map(self):
        path, _ = W.QFileDialog.getSaveFileName(self, 'Export map', 'map.npz', 'Measured data and recipe (*.npz);;Plotted coordinates (*.csv)')
        if path:
            self.write(lambda: self.result.export(path))

    def export_section(self):
        path, _ = W.QFileDialog.getSaveFileName(self, 'Export cross-section', 'section.csv', 'CSV (*.csv)')
        if path:
            def save():
                axis = self.section_axis.currentData()
                x, z = self.result.section(axis, self.section_value.currentIndex())
                r = self.result
                with open(path, 'w', newline='') as stream:
                    writer = csv.writer(stream)
                    writer.writerow([f'Fixed {axis}: {self.section_value.currentText()}'])
                    writer.writerow([f"{r.recipe['x' if axis == 'sweep' else 'sweep']} [{r.units[0 if axis == 'sweep' else 2]}]",
                                     f"{r.recipe['signal']} [{r.units[1]}]"])
                    writer.writerows(zip(x, z))
            self.write(save)

    def export_figure(self):
        path, _ = W.QFileDialog.getSaveFileName(self, 'Export map figure', 'map.png', 'PNG (*.png);;PDF (*.pdf);;SVG (*.svg)')
        if path:
            self.write(lambda: self.figure.savefig(path))

    def write(self, operation):
        try:
            operation()
            self.status.setText('Export complete.')
        except (OSError, ValueError) as error:
            self.status.setText(str(error))
