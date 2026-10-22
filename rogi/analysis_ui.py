"""Pipeline editor and explicit, disposable result preview."""
from copy import deepcopy
from .presets import (make_preset, validate_presets, save_presets, load_presets, apply_preset,
                      place_results, PALETTES, DEFAULT_DISPLAY)
from PySide6 import QtWidgets as W, QtCore as C
from matplotlib.figure import Figure
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from .screen import fit_to_screen
from .analysis import analyze, channel_unit, POLICIES

LABELS = {'mean_subtract': 'Subtract mean', 'normalize': 'Normalize',
          'moving_average': 'Moving average', 'differentiate': 'Differentiate'}


class AnalysisDialog(W.QDialog):
    def __init__(self, dataset, parent=None, presets=None, on_presets_changed=None, display=None):
        super().__init__(parent)
        self.source = dataset
        self.presets = presets if presets is not None else {}
        self.on_presets_changed = on_presets_changed or (lambda: None)
        self.dataset = None
        self.setWindowTitle('Analysis pipeline — ' + dataset.name)
        fit_to_screen(self, 900, 760)
        layout = W.QVBoxLayout(self)
        preset_controls = W.QHBoxLayout()
        self.preset_choice = W.QComboBox()
        preset_controls.addWidget(self.preset_choice, 1)
        for label, callback in [('Load preset', self.load_selected_preset),
                                ('Save/update preset…', self.save_preset),
                                ('Import…', self.import_presets), ('Export…', self.export_preset)]:
            button = W.QPushButton(label)
            button.clicked.connect(callback)
            preset_controls.addWidget(button)
        layout.addLayout(preset_controls)
        self.refresh_presets()
        form = W.QFormLayout()
        self.name = W.QLineEdit(dataset.name + ' (analysis)')
        form.addRow('Derived dataset name', self.name)
        self.xchannel, self.ychannel = W.QComboBox(), W.QComboBox()
        self.xunit, self.yunit = W.QLineEdit(), W.QLineEdit()
        for label, combo, unit, index in [('X', self.xchannel, self.xunit, dataset.xcol),
                                          ('Y', self.ychannel, self.yunit, dataset.ycol)]:
            combo.addItems(dataset.columns)
            combo.setCurrentIndex(index)
            unit.setText(channel_unit(dataset, index))
            unit.setPlaceholderText('Unknown; enter 1 for dimensionless')
            form.addRow(label + ' input channel', combo)
            form.addRow(label + ' input unit', unit)
            combo.currentIndexChanged.connect(lambda i, field=unit: field.setText(channel_unit(dataset, i)))
            combo.currentIndexChanged.connect(self.invalidate)
            unit.textChanged.connect(self.invalidate)
        layout.addLayout(form)
        self.steps = W.QListWidget()
        layout.addWidget(self.steps)
        controls = W.QHBoxLayout()
        self.operation = W.QComboBox()
        for op, label in LABELS.items():
            self.operation.addItem(label, op)
        controls.addWidget(self.operation)
        for label, callback in [('Add', self.add_step), ('Remove', self.remove_step),
                                ('Move up', lambda: self.move_step(-1)), ('Move down', lambda: self.move_step(1))]:
            button = W.QPushButton(label)
            button.clicked.connect(callback)
            controls.addWidget(button)
        layout.addLayout(controls)
        params = W.QFormLayout()
        self.method = W.QComboBox()
        self.method.addItem('Maximum absolute value → unit magnitude', 'max_abs')
        self.method.addItem('Minimum–maximum → [0, 1]', 'min_max')
        self.window = W.QSpinBox()
        self.window.setRange(1, 1000001)
        self.window.setSingleStep(2)
        self.window.setValue(3)
        params.addRow('Normalization method (selected step)', self.method)
        params.addRow('Centered window, odd sample count (selected step)', self.window)
        layout.addLayout(params)
        # Display settings only affect 2D map previews; they never change computed values.
        self.display_box = W.QGroupBox('Save image display settings with the preset (2D map previews)')
        self.display_box.setCheckable(True)
        self.display_box.setChecked(False)
        display_form = W.QHBoxLayout(self.display_box)
        self.palette = W.QComboBox()
        self.palette.addItems(PALETTES)
        self.invert = W.QCheckBox('Invert')
        self.brightness, self.contrast = W.QSpinBox(), W.QSpinBox()
        for spin in (self.brightness, self.contrast):
            spin.setRange(-100, 100)
        self.brightness.setToolTip('Shifts the color window relative to each image\'s data range (0 = centred).')
        self.contrast.setToolTip('Narrows (positive) or widens (negative) the color window; 0 spans the data range.')
        self.gamma = W.QDoubleSpinBox()
        self.gamma.setRange(.25, 4)
        self.gamma.setDecimals(2)
        self.gamma.setSingleStep(.05)
        for widget in (W.QLabel('Colors'), self.palette, self.invert, W.QLabel('Brightness'), self.brightness,
                       W.QLabel('Contrast'), self.contrast, W.QLabel('Gamma'), self.gamma):
            display_form.addWidget(widget)
        display_form.addStretch()
        layout.addWidget(self.display_box)
        self.set_display(display or DEFAULT_DISPLAY)
        self.steps.currentRowChanged.connect(self.select_step)
        self.method.currentIndexChanged.connect(self.update_step)
        self.window.valueChanged.connect(self.update_step)
        rules = W.QLabel('\n'.join(POLICIES.values()) + '\nMean and normalization use finite X/Y pairs. Zero-scale normalization is rejected. Unknown units remain unknown; normalization is dimensionless.')
        rules.setWordWrap(True)
        layout.addWidget(rules)
        self.figure = Figure(figsize=(7, 2.5), tight_layout=True)
        self.canvas = FigureCanvasQTAgg(self.figure)
        layout.addWidget(self.canvas, 1)
        self.status = W.QLabel('Add operations, then preview.')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        buttons = W.QHBoxLayout()
        self.preview_button = W.QPushButton('Preview')
        self.save_button = W.QPushButton('Save as derived dataset')
        cancel = W.QPushButton('Cancel')
        self.preview_button.clicked.connect(self.preview)
        self.save_button.clicked.connect(self.save_result)
        cancel.clicked.connect(self.reject)
        for button in (self.preview_button, self.save_button, cancel):
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self.name.textChanged.connect(self.invalidate)
        self.invalidate()
        self.select_step()

    def refresh_presets(self, selected=None):
        self.preset_choice.clear()
        self.preset_choice.addItems(list(self.presets))
        if selected:
            self.preset_choice.setCurrentText(selected)

    def load_operations(self, operations):
        make_preset(operations)  # Validate before replacing the editor.
        self.steps.clear()
        for step in deepcopy(operations):
            item = W.QListWidgetItem()
            self.set_step(item, step)
            self.steps.addItem(item)
        self.steps.setCurrentRow(0)
        self.invalidate()

    def set_display(self, display):
        self.palette.setCurrentText(display['palette'])
        self.invert.setChecked(display['invert'])
        self.brightness.setValue(display['brightness'])
        self.contrast.setValue(display['contrast'])
        self.gamma.setValue(display['gamma'])

    def display(self):
        if not self.display_box.isChecked():
            return None
        return dict(palette=self.palette.currentText(), invert=self.invert.isChecked(),
                    brightness=self.brightness.value(), contrast=self.contrast.value(),
                    gamma=round(self.gamma.value(), 2))

    def load_selected_preset(self):
        name = self.preset_choice.currentText()
        if name in self.presets:
            self.load_operations(self.presets[name]['operations'])
            display = self.presets[name].get('display')
            self.display_box.setChecked(display is not None)
            if display is not None:
                self.set_display(display)
            self.status.setText('Preset loaded. Check input channels and units, then preview. Changes do not update the preset until Save/update.')

    def store_preset(self, name):
        name = name.strip()
        preset = make_preset(self.operations(), self.display())
        validate_presets({name: preset})
        self.presets[name] = preset
        self.on_presets_changed()
        self.refresh_presets(name)
        self.status.setText('Preset saved in the workspace. Save the project to persist it, or Export for another project.')

    def save_preset(self):
        name, ok = W.QInputDialog.getText(self, 'Save/update pipeline preset',
            'Name (an existing name replaces that preset):', text=self.preset_choice.currentText())
        if ok:
            try:
                self.store_preset(name)
            except ValueError as error:
                self.status.setText(str(error))

    def import_presets(self):
        path, _ = W.QFileDialog.getOpenFileName(self, 'Import pipeline presets', '', 'Pipeline presets (*.json)')
        if not path:
            return
        try:
            imported = load_presets(path)
            # Keep existing recipes when another file uses the same names.
            for name, preset in imported.items():
                base, suffix = name, 2
                while name in self.presets:
                    name = f'{base} ({suffix})'
                    suffix += 1
                self.presets[name] = deepcopy(preset)
            self.on_presets_changed()
            self.refresh_presets()
            self.status.setText('Presets imported. Choose one and click Load preset.')
        except (ValueError, OSError) as error:
            self.status.setText(str(error))

    def export_preset(self):
        name = self.preset_choice.currentText()
        if name not in self.presets:
            self.status.setText('Save a named preset first.')
            return
        path, _ = W.QFileDialog.getSaveFileName(self, 'Export saved pipeline preset', '', 'Pipeline presets (*.json)')
        if path:
            try:
                save_presets(path, {name: self.presets[name]})
                self.status.setText('Saved preset exported (save/update first to include editor changes).')
            except (ValueError, OSError) as error:
                self.status.setText(str(error))

    def operations(self):
        return [self.steps.item(i).data(C.Qt.ItemDataRole.UserRole) for i in range(self.steps.count())]

    def invalidate(self, *_):
        self.dataset = None
        if hasattr(self, 'save_button'):
            self.save_button.setEnabled(False)
            self.status.setText('Configuration changed. Preview before saving.')
            self.figure.clear()
            self.canvas.draw_idle()

    def set_step(self, item, step):
        item.setData(C.Qt.ItemDataRole.UserRole, step)
        details = ', '.join(f'{key}={value}' for key, value in step['parameters'].items())
        item.setText(LABELS[step['operation']] + (f' ({details})' if details else ''))
        self.invalidate()

    def add_step(self):
        op = self.operation.currentData()
        params = {'method': 'max_abs'} if op == 'normalize' else {'window': 3} if op == 'moving_average' else {}
        item = W.QListWidgetItem()
        self.set_step(item, dict(operation=op, parameters=params))
        self.steps.addItem(item)
        self.steps.setCurrentItem(item)

    def remove_step(self):
        self.steps.takeItem(self.steps.currentRow())
        self.invalidate()

    def move_step(self, direction):
        row = self.steps.currentRow()
        if 0 <= row + direction < self.steps.count() and row >= 0:
            item = self.steps.takeItem(row)
            self.steps.insertItem(row + direction, item)
            self.steps.setCurrentItem(item)
            self.invalidate()

    def select_step(self, *_):
        item = self.steps.currentItem()
        step = item.data(C.Qt.ItemDataRole.UserRole) if item else None
        self.method.setEnabled(bool(step and step['operation'] == 'normalize'))
        self.window.setEnabled(bool(step and step['operation'] == 'moving_average'))
        with C.QSignalBlocker(self.method), C.QSignalBlocker(self.window):
            if self.method.isEnabled():
                self.method.setCurrentIndex(self.method.findData(step['parameters']['method']))
            if self.window.isEnabled():
                self.window.setValue(step['parameters']['window'])

    def update_step(self, *_):
        item = self.steps.currentItem()
        if item:
            step = item.data(C.Qt.ItemDataRole.UserRole)
            if step['operation'] == 'normalize':
                step['parameters'] = {'method': self.method.currentData()}
            elif step['operation'] == 'moving_average':
                step['parameters'] = {'window': self.window.value()}
            self.set_step(item, step)

    def preview(self):
        self.invalidate()
        try:
            if not self.name.text().strip():
                raise ValueError('Enter a derived dataset name.')
            result = analyze(self.source, self.operations(), xcol=self.xchannel.currentIndex(),
                             ycol=self.ychannel.currentIndex(), xunit=self.xunit.text(),
                             yunit=self.yunit.text(), name=self.name.text().strip())
        except ValueError as error:
            self.status.setText(str(error))
            return
        self.dataset = result
        # Separate axes make unit-changing operations honest comparisons.
        for position, label, values, unit in [(1, 'Input', self.source.values[:, self.ychannel.currentIndex()], self.yunit.text()),
                                              (2, 'Result', result.values[:, 1], result.column_units[1])]:
            ax = self.figure.add_subplot(1, 2, position)
            ax.plot(result.values[:, 0], values)
            ax.set_title(label)
            ax.set_xlabel(self.xchannel.currentText() + f' [{self.xunit.text() or "unknown unit"}]')
            ax.set_ylabel(unit or 'unknown unit')
        self.canvas.draw_idle()
        self.status.setText(f'Preview of {len(result.values)} rows. Output unit: {result.column_units[1] or "unknown"}. Save adds a dataset to the project; use project Save to persist it.')
        self.save_button.setEnabled(True)

    def save_result(self):
        if self.dataset is not None:
            if self.source.revision != self.dataset.analysis['source']['revision']:
                self.invalidate()
                self.status.setText('Source changed. Preview again before saving.')
                return
            self.accept()


class MultiAnalysisDialog(W.QDialog):
    """Explicit selected-dataset arithmetic and ensemble statistics."""
    def __init__(self, datasets, parent=None):
        super().__init__(parent)
        self.sources = list(datasets)
        self.datasets = []
        self.setWindowTitle('Analysis pipeline — selected datasets')
        fit_to_screen(self, 950, 800)
        layout = W.QVBoxLayout(self)
        info = W.QLabel('Uses each dataset’s selected X/Y channels. Channel names and units must match. '
                        'Select channels in the main window before opening this dialog.')
        info.setWordWrap(True)
        layout.addWidget(info)
        self.inputs = W.QTableWidget(len(datasets), 3)
        self.inputs.setHorizontalHeaderLabels(['Dataset', 'X channel / unit', 'Y channel / unit'])
        self.inputs.setEditTriggers(W.QAbstractItemView.EditTrigger.NoEditTriggers)
        for row, d in enumerate(datasets):
            for col, value in enumerate([d.name, f'{d.columns[d.xcol]} / {channel_unit(d, d.xcol) or "unknown"}',
                                         f'{d.columns[d.ycol]} / {channel_unit(d, d.ycol) or "unknown"}']):
                self.inputs.setItem(row, col, W.QTableWidgetItem(value))
        self.inputs.horizontalHeader().setSectionResizeMode(W.QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.inputs)
        form = W.QFormLayout()
        self.operation = W.QComboBox()
        for label, value in [('Mean spectrum ± sample standard deviation', 'mean'),
                             ('Subtract a reference from every other selected dataset', 'reference_subtract'),
                             ('Explicit paired subtraction (left − right)', 'paired_subtract')]:
            self.operation.addItem(label, value)
        self.reference, self.grid, self.left, self.right = [W.QComboBox() for _ in range(4)]
        for combo in (self.reference, self.grid, self.left, self.right):
            for i, d in enumerate(datasets):
                combo.addItem(f'{i+1}. {d.name}', d.id)
            combo.currentIndexChanged.connect(self.invalidate)
        self.right.setCurrentIndex(1)
        self.alignment = W.QComboBox()
        self.alignment.addItem('Exact matching X coordinates (default)', 'exact')
        self.alignment.addItem('Linear interpolation; no extrapolation or gap bridging', 'interpolate')
        self.grid.setCurrentIndex(-1)
        form.addRow('Operation', self.operation)
        form.addRow('Subtraction reference', self.reference)
        form.addRow('Alignment', self.alignment)
        form.addRow('Reference grid (required for interpolation)', self.grid)
        layout.addLayout(form)
        pair_controls = W.QHBoxLayout()
        pair_controls.addWidget(self.left)
        pair_controls.addWidget(W.QLabel('minus'))
        pair_controls.addWidget(self.right)
        self.add_pair_button = W.QPushButton('Add explicit pair')
        self.add_pair_button.clicked.connect(self.add_pair)
        pair_controls.addWidget(self.add_pair_button)
        self.remove_pair_button = W.QPushButton('Remove pair')
        self.remove_pair_button.clicked.connect(self.remove_pair)
        pair_controls.addWidget(self.remove_pair_button)
        layout.addLayout(pair_controls)
        self.pairs = W.QListWidget()
        layout.addWidget(self.pairs)
        rules = W.QLabel('Bands show sample SD (ddof=1), not SEM. SEM = SD / √n is a separate output column. '
                        'SD and SEM are undefined for n < 2. Counts include finite aligned samples at each X; '
                        'subtraction requires both operands. Unknown units must match as unknown.')
        rules.setWordWrap(True)
        layout.addWidget(rules)
        self.figure = Figure(figsize=(7, 3), tight_layout=True)
        self.canvas = FigureCanvasQTAgg(self.figure)
        layout.addWidget(self.canvas, 1)
        self.status = W.QLabel('Preview to calculate results.')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        controls = W.QHBoxLayout()
        preview = W.QPushButton('Preview')
        preview.clicked.connect(self.preview)
        self.save_button = W.QPushButton('Save derived datasets')
        self.save_button.clicked.connect(self.save_result)
        cancel = W.QPushButton('Cancel')
        cancel.clicked.connect(self.reject)
        for button in (preview, self.save_button, cancel):
            controls.addWidget(button)
        layout.addLayout(controls)
        self.operation.currentIndexChanged.connect(self.configure)
        self.alignment.currentIndexChanged.connect(self.configure)
        self.configure()

    def invalidate(self, *_):
        self.datasets = []
        if hasattr(self, 'save_button'):
            self.save_button.setEnabled(False)
            self.figure.clear()
            self.canvas.draw_idle()
            self.status.setText('Configuration changed. Preview before saving.')

    def configure(self, *_):
        op = self.operation.currentData()
        self.reference.setEnabled(op == 'reference_subtract')
        for widget in (self.left, self.right, self.pairs, self.add_pair_button, self.remove_pair_button):
            widget.setEnabled(op == 'paired_subtract')
        self.grid.setEnabled(self.alignment.currentData() == 'interpolate')
        self.invalidate()

    def add_pair(self):
        item = W.QListWidgetItem(self.left.currentText() + ' − ' + self.right.currentText())
        item.setData(C.Qt.ItemDataRole.UserRole, [self.left.currentData(), self.right.currentData()])
        self.pairs.addItem(item)
        self.invalidate()

    def remove_pair(self):
        self.pairs.takeItem(self.pairs.currentRow())
        self.invalidate()

    def preview(self):
        from .analysis import analyze_many
        self.invalidate()
        try:
            self.datasets = analyze_many(self.sources, self.operation.currentData(),
                reference=self.reference.currentData(),
                pairs=[self.pairs.item(i).data(C.Qt.ItemDataRole.UserRole) for i in range(self.pairs.count())],
                alignment=self.alignment.currentData(),
                grid=self.grid.currentData() if self.grid.isEnabled() else None)
        except ValueError as error:
            self.status.setText(str(error))
            return
        ax, counts = self.figure.subplots(2, 1, sharex=True, gridspec_kw={'height_ratios': [3, 1]})
        for d in self.datasets:
            x, y = d.values[:, 0], d.values[:, 1]
            line, = ax.plot(x, y, label=d.name)
            if d.analysis['operation'] == 'mean':
                sd = d.values[:, 2]
                ax.fill_between(x, y-sd, y+sd, alpha=.2, color=line.get_color(), label='±1 sample SD (not SEM)')
            counts.plot(x, d.values[:, -1], marker='.', label=d.name)
        ax.legend()
        ax.set_ylabel(self.datasets[0].column_units[1] or 'unknown unit')
        counts.set_ylabel('Count n')
        counts.set_xlabel(self.sources[0].columns[self.sources[0].xcol])
        self.canvas.draw_idle()
        self.status.setText(f'{len(self.datasets)} result(s). Per-X counts are plotted below and saved as the last column. '
                            'All selected inputs, revisions, channel choices and alignment settings are recorded.')
        self.save_button.setEnabled(True)

    def save_result(self):
        if self.datasets:
            recorded = self.datasets[0].analysis['sources']
            if any(d.revision != s['revision'] or d.xcol != s['input_channels']['x']['index']
                   or d.ycol != s['input_channels']['y']['index'] for d, s in zip(self.sources, recorded)):
                self.invalidate()
                self.status.setText('Inputs changed. Preview again before saving.')
                return
            self.accept()


class BatchPipelineDialog(W.QDialog):
    """Apply one single-signal recipe independently to each selected dataset."""
    def __init__(self, sources, presets, parent=None):
        super().__init__(parent)
        self.sources = list(sources)
        self.presets = deepcopy(presets)
        self.datasets = []
        self.setWindowTitle('Apply pipeline preset to selected datasets')
        fit_to_screen(self, 900, 700)
        layout = W.QVBoxLayout(self)
        self.preset = W.QComboBox()
        self.preset.addItems(list(presets))
        layout.addWidget(self.preset)
        info = W.QLabel('Each input produces its own result. Choose channels per dataset; units come from those channels. '
                        'All inputs must succeed before any results are added. Presets never combine datasets.')
        info.setWordWrap(True)
        layout.addWidget(info)
        self.inputs = W.QTableWidget(len(sources), 3)
        self.inputs.setHorizontalHeaderLabels(['Dataset', 'X channel / unit', 'Y channel / unit'])
        self.inputs.setEditTriggers(W.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.channels = []
        for row, source in enumerate(sources):
            self.inputs.setItem(row, 0, W.QTableWidgetItem(source.name))
            pair = []
            for column, index in [(1, source.xcol), (2, source.ycol)]:
                combo = W.QComboBox()
                for i, label in enumerate(source.columns):
                    combo.addItem(f'{label} / {channel_unit(source, i) or "unknown"}', i)
                combo.setCurrentIndex(index)
                combo.currentIndexChanged.connect(self.invalidate)
                self.inputs.setCellWidget(row, column, combo)
                pair.append(combo)
            self.channels.append(pair)
        self.inputs.horizontalHeader().setSectionResizeMode(W.QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.inputs)
        self.result_choice = W.QComboBox()
        self.result_choice.currentIndexChanged.connect(self.draw_result)
        layout.addWidget(self.result_choice)
        self.figure = Figure(figsize=(7, 3), tight_layout=True)
        self.canvas = FigureCanvasQTAgg(self.figure)
        layout.addWidget(self.canvas, 1)
        destination = W.QFormLayout()
        self.destination = W.QComboBox()
        self.destination.setAccessibleName('Group for results')
        for label, key in [("Same group as each input", 'source'),
                           ("Subgroup of each input's group", 'subgroup'),
                           ('One new group for all results', 'group')]:
            self.destination.addItem(label, key)
        self.group_name = W.QLineEdit(self.preset.currentText())
        self.group_name.setAccessibleName('Result group name')
        destination.addRow('Put results in', self.destination)
        destination.addRow('Group name', self.group_name)
        layout.addLayout(destination)
        self.destination.currentIndexChanged.connect(self.update_destination)
        self.preset.currentTextChanged.connect(self.group_name.setText)
        self.update_destination()
        self.status = W.QLabel('Choose a preset and preview all inputs.')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        controls = W.QHBoxLayout()
        preview = W.QPushButton('Preview all')
        preview.clicked.connect(self.preview)
        self.save_button = W.QPushButton('Create all derived datasets')
        self.save_button.clicked.connect(self.save_result)
        cancel = W.QPushButton('Cancel')
        cancel.clicked.connect(self.reject)
        for button in (preview, self.save_button, cancel):
            controls.addWidget(button)
        layout.addLayout(controls)
        self.preset.currentIndexChanged.connect(self.invalidate)
        self.invalidate()

    def update_destination(self, *_):
        self.group_name.setEnabled(self.destination.currentData() != 'source')

    def invalidate(self, *_):
        self.datasets = []
        if hasattr(self, 'save_button'):
            self.save_button.setEnabled(False)
            self.result_choice.clear()
            self.figure.clear()
            self.canvas.draw_idle()
            self.status.setText('Preview all inputs before creating results.')

    def preview(self):
        from copy import copy
        self.invalidate()
        try:
            name = self.preset.currentText()
            if name not in self.presets:
                raise ValueError('Save or import a pipeline preset in the single-dataset editor first.')
            inputs = []
            for source, pair in zip(self.sources, self.channels):
                mapped = copy(source)
                mapped.xcol, mapped.ycol = [combo.currentData() for combo in pair]
                inputs.append(mapped)
            self.datasets = apply_preset(inputs, self.presets[name], name)
        except ValueError as error:
            self.status.setText(str(error))
            return
        self.result_choice.addItems([d.name for d in self.datasets])
        self.draw_result()
        self.status.setText(f'{len(self.datasets)} independent results ready. Choose a result above to inspect it. Creation is one undoable action.')
        self.save_button.setEnabled(True)

    def draw_result(self, *_):
        if not self.datasets:
            return
        self.figure.clear()
        d = self.datasets[max(0, self.result_choice.currentIndex())]
        ax = self.figure.add_subplot(111)
        ax.plot(d.values[:, 0], d.values[:, 1])
        ax.set_xlabel(d.columns[0])
        ax.set_ylabel(d.column_units[1] or 'unknown unit')
        ax.set_title(d.name)
        self.canvas.draw_idle()

    def save_result(self):
        if self.datasets:
            if any(source.revision != result.analysis['source']['revision']
                   for source, result in zip(self.sources, self.datasets)):
                self.invalidate()
                self.status.setText('An input changed. Preview again.')
                return
            try:
                place_results(self.sources, self.datasets, self.destination.currentData(), self.group_name.text())
            except ValueError as error:
                self.status.setText(str(error))
                return
            self.accept()
