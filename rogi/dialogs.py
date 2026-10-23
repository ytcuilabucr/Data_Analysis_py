"""Import previews and dataset metadata dialogs."""
import csv
import io
from copy import deepcopy
from pathlib import Path
from PySide6 import QtCore as C, QtWidgets as W
from .files import read_text_import, parse_text_import, channel_key
from .spm import load_spm
from .scanfile import bundle_channels
from .grouping import path_label, path_key, partitions, varying_fields, field_labels, import_destinations, grouping_fields
from .operations import run_operation, Cancelled
from .browser_panel import populate_group_tree
from .screen import fit_to_screen
from .units import column_unit, conversion_factor, display_unit, normalize_unit


class ImportDialog(W.QDialog):
    def __init__(self, path, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Import preview — choose numeric columns")
        self.resize(800, 550)
        self.path = Path(path)
        self.text, instrument_table = run_operation(self, "Reading import",
            lambda: read_text_import(self.path), cancellable=True)
        self.table_text = instrument_table if instrument_table is not None else self.text.removeprefix('\ufeff')
        self.dataset = None
        layout = W.QVBoxLayout(self)
        form = W.QHBoxLayout()
        self.delimiter = W.QComboBox()
        for label, value in [("Comma", ","), ("Tab", "\t"), ("Semicolon", ";")]:
            self.delimiter.addItem(label, value)
        if self.path.suffix.lower() in ('.tsv', '.txt', '.dat'):
            self.delimiter.setCurrentIndex(1)
        self.header = W.QCheckBox("First row contains headers")
        self.header.setChecked(True)
        if instrument_table is not None:
            self.delimiter.setCurrentIndex(1)
            self.delimiter.setEnabled(False)
            self.header.setEnabled(False)
        form.addWidget(self.delimiter)
        form.addWidget(self.header)
        layout.addLayout(form)
        if instrument_table is not None:
            layout.addWidget(W.QLabel('Instrument [Data] section detected. Metadata and Time are structured and preserved;\n'
                                     'Time_Timestamp is available as a numeric channel. Duplicate names receive suffixes.'))
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
            reader = csv.reader(io.StringIO(self.table_text), delimiter=self.delimiter.currentData(), strict=True)
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
            delimiter, header = self.delimiter.currentData(), self.header.isChecked()
            self.dataset = run_operation(self, "Importing data", lambda: parse_text_import(
                self.path, self.text, self.table_text, delimiter, header, selected), cancellable=True)
            self.accept()
        except Cancelled:
            return
        except (ValueError, csv.Error) as error:
            self.message.setText(str(error))

    def template(self):
        """The accepted choices, reusable for files with the same layout."""
        return dict(delimiter=self.delimiter.currentData(), header=self.header.isChecked(),
                    columns=list(self.dataset.columns))



class SpmImportDialog(W.QDialog):
    """Preview binary raster channels without treating the payload as text."""
    def __init__(self, path, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Import SPM — choose channels')
        self.resize(800, 550)
        self.channels = run_operation(self, "Reading scan", lambda: load_spm(path), cancellable=True)
        self.datasets = []
        layout = W.QVBoxLayout(self)
        notice = W.QLabel('One dataset per file. Selected channels become columns; choose image channels in 2D Map.\n'
                         'Bruker values are raw ADC counts. Nanonis values retain the file’s declared units.\n'
                         'Images use pixel indices; force curves use segment/sample indices. Headers are preserved.')
        notice.setWordWrap(True)
        layout.addWidget(notice)
        self.channel_list = W.QListWidget()
        for dataset in self.channels:
            item = W.QListWidgetItem(dataset.name, self.channel_list)
            item.setFlags(item.flags() | C.Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(C.Qt.CheckState.Checked)
        layout.addWidget(self.channel_list)
        layout.addWidget(W.QLabel('Preview: first 100 samples of the highlighted channel.'))
        self.preview = W.QTableWidget()
        self.preview.setEditTriggers(W.QAbstractItemView.EditTrigger.NoEditTriggers)
        layout.addWidget(self.preview)
        self.message = W.QLabel()
        layout.addWidget(self.message)
        buttons = W.QDialogButtonBox(W.QDialogButtonBox.StandardButton.Ok | W.QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.import_data)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.channel_list.currentRowChanged.connect(self.refresh)
        self.channel_list.setCurrentRow(0)

    def refresh(self, row):
        if row < 0:
            return
        dataset = self.channels[row]
        self.preview.setColumnCount(len(dataset.columns))
        self.preview.setHorizontalHeaderLabels(dataset.columns)
        self.preview.setRowCount(min(100, len(dataset.values)))
        for r, values in enumerate(dataset.values[:100]):
            for c, value in enumerate(values):
                self.preview.setItem(r, c, W.QTableWidgetItem(f'{value:g}'))

    def import_data(self):
        self.datasets = [dataset for i, dataset in enumerate(self.channels)
                         if self.channel_list.item(i).checkState() == C.Qt.CheckState.Checked]
        if not self.datasets:
            self.message.setText('Select at least one channel.')
            return
        try:
            selected = self.datasets
            self.datasets = [run_operation(self, "Importing scan",
                lambda: bundle_channels(selected), cancellable=True)]
        except Cancelled:
            self.datasets = []
            return
        self.accept()

    def template(self):
        """The accepted channels, reusable for scans with the same channels."""
        return dict(channels=[channel_key(d) for i, d in enumerate(self.channels)
                              if self.channel_list.item(i).checkState() == C.Qt.CheckState.Checked])



class ImportGroupDialog(W.QDialog):
    """Choose a destination after parsing the file's complete metadata."""
    def __init__(self, dataset, existing, project_path=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Import — choose subgroup')
        self.resize(660, 300)
        layout = W.QVBoxLayout(self)
        target = str(project_path) if project_path else 'Current unsaved project'
        notice = W.QLabel(f'Add {dataset.name} to:\n{target}\nUse Save to store the added file.')
        notice.setWordWrap(True)
        layout.addWidget(notice)
        destinations = import_destinations(dataset, existing)
        labels = field_labels(n['field'] for p, _ in destinations for n in p if n['field'] is not None)
        form = W.QFormLayout()
        self.destination = W.QComboBox()
        self.destination.addItem('Ungrouped (project root)', [])
        for path, evidence in destinations:
            self.destination.addItem(path_label(path, labels), path)
            self.destination.setItemData(self.destination.count() - 1, path_label(path), C.Qt.ItemDataRole.ToolTipRole)
        form.addRow('Subgroup', self.destination)
        self.child_name = W.QLineEdit()
        self.child_name.setPlaceholderText('Optional new subgroup inside the selected destination')
        form.addRow('New subgroup', self.child_name)
        layout.addLayout(form)
        scores = [(len(evidence), len(path)) if evidence else (0, 0) for path, evidence in destinations]
        best = max(scores, default=(0, 0))
        winners = [i for i, score in enumerate(scores) if score == best and score[0] > 0]
        if len(winners) == 1:
            index = winners[0]
            self.destination.setCurrentIndex(index + 1)
            path, evidence = destinations[index]
            detail = '; '.join(f'{key} = {value}' for key, value in evidence.items())
            message = f'Suggested: {path_label(path, labels)}\nMatching metadata: {detail}\nYou can choose any subgroup.'
        elif winners:
            message = 'Metadata matches multiple subgroups equally. Choose a destination; no subgroup was selected automatically.'
        else:
            message = 'No confident metadata match. Choose a subgroup or leave the file ungrouped.'
        self.suggestion = W.QLabel(message)
        self.suggestion.setWordWrap(True)
        layout.addWidget(self.suggestion)
        buttons = W.QDialogButtonBox(W.QDialogButtonBox.StandardButton.Ok | W.QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected_path(self):
        path = deepcopy(self.destination.currentData())
        if self.child_name.text().strip():
            path.append({'field': None, 'value': self.child_name.text().strip()})
        return path



class MetadataGroupingDialog(W.QDialog):
    def __init__(self, datasets, parent=None, all_datasets=None):
        super().__init__(parent)
        self.setWindowTitle('Group by metadata or title')
        fit_to_screen(self, 880, 620)
        self.selected_files = list(datasets)
        self.all_files = list(all_datasets) if all_datasets is not None else self.selected_files
        self.level_rows = []
        layout = W.QVBoxLayout(self)
        note = W.QLabel('Add levels to subdivide each parent group. Only fields that vary within a parent '
                        'are offered. Missing values form a “Missing value” subgroup. “Title:” fields come from '
                        'file titles: “power = 10” or “power100” give power, “4MHz” gives MHz.')
        note.setWordWrap(True)
        layout.addWidget(note)
        form = W.QFormLayout()
        self.scope = W.QComboBox()
        self.scope.addItems([f'Selected files ({len(self.selected_files)})',
                             f'All project files ({len(self.all_files)})'])
        self.mode = W.QComboBox()
        self.mode.addItems(['Replace grouping', 'Add subgroup within existing groups'])
        self.mode.setCurrentIndex(1)
        self.mode.setToolTip('Existing groups are kept as parents by default. '
                             'Choose Replace grouping only to discard the current hierarchy.')
        form.addRow('Files to group:', self.scope)
        form.addRow('Operation:', self.mode)
        layout.addLayout(form)
        self.level_layout = W.QVBoxLayout()
        layout.addLayout(self.level_layout)
        self.add_level = W.QPushButton('Add subgroup level')
        self.add_level.clicked.connect(lambda: self.add_row())
        layout.addWidget(self.add_level)
        self.summary = W.QLabel()
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.preview = W.QTreeWidget()
        self.preview.setHeaderLabels(['Group / subgroup', 'Files'])
        self.preview.header().setSectionResizeMode(0, W.QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.preview)
        self.buttons = W.QDialogButtonBox(W.QDialogButtonBox.StandardButton.Ok |
                                         W.QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(W.QDialogButtonBox.StandardButton.Ok).setText('Group files')
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.scope.currentIndexChanged.connect(self.update_fields)
        self.mode.currentIndexChanged.connect(self.update_fields)
        self.add_row()

    @property
    def levels(self):
        return [(field.currentText(), order.currentIndex() == 1)
                for _, field, order, _ in self.level_rows if field.currentText()]

    def add_row(self):
        widget = W.QWidget()
        row = W.QHBoxLayout(widget)
        row.setContentsMargins(0, 0, 0, 0)
        field, order = W.QComboBox(), W.QComboBox()
        field.setSizePolicy(W.QSizePolicy.Policy.Expanding, W.QSizePolicy.Policy.Fixed)
        order.addItems(['Ascending', 'Descending'])
        remove = W.QPushButton('Remove')
        row.addWidget(field, 1)
        row.addWidget(order)
        row.addWidget(remove)
        self.level_rows.append((widget, field, order, remove))
        self.level_layout.addWidget(widget)
        self.field, self.order = self.level_rows[0][1:3]
        field.currentIndexChanged.connect(self.update_fields)
        order.currentIndexChanged.connect(self.update_preview)
        remove.clicked.connect(lambda: self.remove_row(widget))
        self.update_fields()

    def remove_row(self, widget):
        self.level_rows = [r for r in self.level_rows if r[0] is not widget]
        self.level_layout.removeWidget(widget)
        widget.deleteLater()
        self.field, self.order = self.level_rows[0][1:3]
        self.update_fields()

    def update_fields(self, *args):
        self.datasets = self.selected_files if self.scope.currentIndex() == 0 else self.all_files
        levels = []
        for index, (_, field, order, remove) in enumerate(self.level_rows):
            keys = varying_fields(self.datasets, levels, self.mode.currentIndex() == 1) if index == len(levels) else []
            previous = field.currentText()
            with C.QSignalBlocker(field):
                field.clear()
                field.addItems(keys)
                if previous in keys:
                    field.setCurrentText(previous)
            field.setEnabled(bool(keys))
            order.setEnabled(bool(keys))
            remove.setEnabled(len(self.level_rows) > 1)
            if field.currentText():
                levels.append((field.currentText(), order.currentIndex() == 1))
        complete = bool(levels) and len(levels) == len(self.level_rows)
        self.buttons.button(W.QDialogButtonBox.StandardButton.Ok).setEnabled(complete)
        self.add_level.setEnabled(complete and bool(varying_fields(
            self.datasets, levels, self.mode.currentIndex() == 1)))
        self.update_preview()

    def update_preview(self, *args):
        self.preview.clear()
        if not self.levels:
            if len(self.datasets) < 2:
                text = f'{len(self.datasets)} file(s) in scope. Choose All project files or select at least two files.'
            elif not any(grouping_fields(d) for d in self.datasets):
                text = ('These files have no structured metadata or title fields such as "power = 10" '
                        'or "power100". Reimport the original instrument files or rename them.')
            else:
                text = 'No varying metadata or title fields within these parent groups. Try another scope or Replace grouping.'
            self.summary.setText(text)
            return
        pairs = partitions(self.datasets, self.levels, self.mode.currentIndex() == 1)
        scoped_ids = {d.id for d in self.datasets}
        display_paths = [path for _, path in pairs] + [d.group_path for d in self.all_files
                                                       if d.id not in scoped_ids]
        labels = field_labels(n['field'] for path in display_paths for n in path if n['field'] is not None)
        populate_group_tree(self.preview, [path for _, path in pairs], labels)
        leaves = len({path_key(path) for _, path in pairs})
        missing = sum(any(n['value'] is None for n in path) for _, path in pairs)
        self.summary.setText(f'{leaves} groups · {len(pairs)} files · {missing} files with missing values')
        if len(self.levels) < len(self.level_rows):
            self.summary.setText(self.summary.text() +
                                 ' · No varying fields for the next level; remove that level to apply.')
        self.preview.expandAll()



class MetadataDialog(W.QDialog):
    def __init__(self, dataset, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Metadata — {dataset.name}")
        fit_to_screen(self, 900, 620)
        layout = W.QVBoxLayout(self)
        origin = dataset.instrument_metadata.get('source_dataset_id', 'Not recorded')
        note = W.QLabel(f"Source: {dataset.source or 'Not recorded'}\n"
                        f"Metadata source dataset: {origin}\n"
                        "Original acquisition metadata/timestamps; editable channels may differ. "
                        "No timezone or numeric epoch is inferred. Blank units mean unspecified.")
        note.setWordWrap(True)
        layout.addWidget(note)
        tabs = W.QTabWidget()
        layout.addWidget(tabs)
        tree = W.QTreeWidget()
        tree.setHeaderLabels(["Section / field", "Original value", "Parsed value", "Explicit unit", "Source line"])
        for section in dataset.instrument_metadata.get('sections', []):
            parent_item = W.QTreeWidgetItem(tree, [f"{section['name']} [{section['occurrence']}]", "", "", "", str(section['source_line'])])
            for entry in section['entries']:
                W.QTreeWidgetItem(parent_item, [entry['key'], entry['raw_value'],
                    "" if entry['value'] is None else str(entry['value']), entry['unit'] or "", str(entry['source_line'])])
        for line in dataset.instrument_metadata.get('unparsed', []):
            W.QTreeWidgetItem(tree, ["Unparsed header", line['text'], "", "", str(line['source_line'])])
        tree.expandAll()
        for column in range(tree.columnCount()):
            tree.resizeColumnToContents(column)
        tabs.addTab(tree, "Instrument fields")
        for stream in dataset.timestamps:
            table = W.QTableWidget(len(stream['raw']), 3)
            table.setEditTriggers(W.QAbstractItemView.EditTrigger.NoEditTriggers)
            table.setHorizontalHeaderLabels(["Source data row", "Original timestamp", "Parsed value"])
            table.verticalHeader().setVisible(False)
            for row, (raw, value) in enumerate(zip(stream['raw'], stream['values'])):
                parsed = str(value) if value is not None else ("Unrecognized" if row + 1 in stream['invalid_rows'] else "Missing")
                for col, text in enumerate((str(row + 1), raw, parsed)):
                    table.setItem(row, col, W.QTableWidgetItem(text))
            table.resizeColumnsToContents()
            tabs.addTab(table, f"{stream['name']} [column {stream['source_column']}]")
        if not dataset.instrument_metadata:
            tree.setHeaderLabel("No structured metadata recorded for this dataset")
        source = W.QPlainTextEdit()
        source.setReadOnly(True)
        source.setPlainText(dataset.source_text or "Source text is retained by the parent dataset.")
        tabs.addTab(source, "Original source text")
        buttons = W.QDialogButtonBox(W.QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class UnitsDialog(W.QDialog):
    """Relabel channel units in place, or convert values into an editable copy."""

    def __init__(self, dataset, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Units — {dataset.name}")
        fit_to_screen(self, 640, 480)
        self.dataset = dataset
        self.old = [column_unit(dataset, i) for i in range(len(dataset.columns))]
        layout = W.QVBoxLayout(self)
        info = W.QLabel("Blank means unknown; enter 1 for dimensionless. Plot labels, analysis "
                        "compatibility and maps all use these units.")
        info.setWordWrap(True)
        layout.addWidget(info)
        self.table = W.QTableWidget(len(dataset.columns), 3)
        self.table.setHorizontalHeaderLabels(["Channel", "Current unit", "New unit"])
        self.table.horizontalHeader().setSectionResizeMode(0, W.QHeaderView.ResizeMode.Stretch)
        for row, (name, unit) in enumerate(zip(dataset.columns, self.old)):
            for column, text in enumerate((name, unit, unit)):
                item = W.QTableWidgetItem(text)
                if column < 2:
                    item.setFlags(item.flags() & ~C.Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(row, column, item)
        layout.addWidget(self.table)
        self.relabel = W.QRadioButton("Relabel only: values unchanged (fixes a missing or wrong unit)")
        self.convert = W.QRadioButton("Convert values: SI prefix changes only, e.g. nA → pA "
                                      "(creates an editable copy)")
        self.relabel.setChecked(True)
        for button in (self.relabel, self.convert):
            button.toggled.connect(self.check)
            layout.addWidget(button)
        self.status = W.QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.buttons = W.QDialogButtonBox(W.QDialogButtonBox.StandardButton.Ok | W.QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.table.itemChanged.connect(self.check)
        self.check()

    def units(self):
        return [normalize_unit(self.table.item(row, 2).text()) for row in range(self.table.rowCount())]

    def check(self, *args):
        units = self.units()
        changed = [i for i, (a, b) in enumerate(zip(self.old, units)) if a != b]
        problem = '' if changed else 'No unit changed.'
        notes = []
        if changed and self.convert.isChecked():
            for i in changed:
                try:
                    notes.append(f"{self.dataset.columns[i]}: × {conversion_factor(self.old[i], units[i]):g}")
                except ValueError as error:
                    problem = str(error)
        elif changed:
            notes = [f"{self.dataset.columns[i]}: {display_unit(self.old[i]) or 'unknown'} → "
                     f"{display_unit(units[i]) or 'unknown'}" for i in changed]
        self.status.setText(problem or '; '.join(notes))
        self.buttons.button(W.QDialogButtonBox.StandardButton.Ok).setEnabled(not problem)
