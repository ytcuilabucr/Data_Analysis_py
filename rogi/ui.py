"""Qt desktop presentation. Numerical routines live in core.py."""
import csv
import io
import sys
from copy import deepcopy, copy
from pathlib import Path

# PyCharm's file run configuration executes this without a package context.
if __name__ == "__main__" and not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    __package__ = "rogi"

import numpy as np
from PySide6 import QtCore as C, QtWidgets as W, QtGui as G
from matplotlib.figure import Figure
from .navigation import PlotNavigationToolbar
from matplotlib.transforms import Bbox
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.widgets import SpanSelector, Cursor, RectangleSelector
from .history import ChangeCommand, CellCommand, CellsCommand
from .grouping import group_path, path_key, path_label, node_label, partitions, varying_fields, field_labels, import_destinations
from .spm import load_spm
from .scanfile import bundle_channels, consolidate_legacy
from .images import ImageViewer
from .metadata import attach_spectrum_metadata, metadata_fields, metadata_search_text, acquisition_timestamp, channel_count
from .clipboard import MIME, selection_rectangle, copy_table, parse_paste
from .plotting import MARKERS, LEGENDS, validate_view, display_values
from .core import Dataset, parse_text, spectrum_table, fit_dataset, export_data, export_fit, remove_datasets
from .core import region_statistics
from .project import save_project, load_project, convert_folder


def project_preferences():
    return C.QSettings('Rogi', 'Rogi')


class BrowserItem(W.QTreeWidgetItem):
    """Column-zero conveniences shared by organization and visibility operations."""
    def data(self, *args):
        return super().data(*( (0,) + args if len(args) == 1 else args))

    def setData(self, *args):
        return super().setData(*( (0,) + args if len(args) == 2 else args))

    def text(self, column=0):
        return super().text(column)

    def setText(self, *args):
        return super().setText(*( (0,) + args if len(args) == 1 else args))

    def setToolTip(self, *args):
        return super().setToolTip(*( (0,) + args if len(args) == 1 else args))

    def checkState(self, column=0):
        return super().checkState(column)

    def setCheckState(self, *args):
        return super().setCheckState(*( (0,) + args if len(args) == 1 else args))

    def __lt__(self, other):
        column = self.treeWidget().sortColumn()
        if column == 3:
            return int(self.text(3)) < int(other.text(3))
        return self.text(column).casefold() < other.text(column).casefold()


class DatasetBrowser(W.QTreeWidget):
    """Handle checkbox clicks without Qt's unrelated row-selection transition."""
    currentRowChanged = C.Signal(int)

    def __init__(self):
        super().__init__()
        self.setRootIsDecorated(False)
        self.setSelectionBehavior(W.QAbstractItemView.SelectionBehavior.SelectRows)
        self.setHeaderLabels(['Dataset / plot', 'Favorite', 'Acquisition date', 'Channels', 'Tags', 'Comments'])
        for column, width in enumerate((155, 65, 165, 75, 140, 220)):
            self.setColumnWidth(column, width)
        self.header().setSectionsClickable(True)
        self.header().sectionClicked.connect(self.sort_column)
        self.currentItemChanged.connect(lambda *_: self.currentRowChanged.emit(self.currentRow()))
        self.checkbox_id = None
        self.sort_order = C.Qt.SortOrder.AscendingOrder
        self.sorted_column = None

    def sort_column(self, column):
        self.sort_order = (C.Qt.SortOrder.DescendingOrder
                           if self.sorted_column == column and self.sort_order == C.Qt.SortOrder.AscendingOrder
                           else C.Qt.SortOrder.AscendingOrder)
        self.sorted_column = column
        self.sortItems(column, self.sort_order)
        self.header().setSortIndicatorShown(True)
        self.header().setSortIndicator(column, self.sort_order)

    def count(self):
        return self.topLevelItemCount()

    def item(self, row):
        return self.topLevelItem(row)

    def currentRow(self):
        return self.indexOfTopLevelItem(self.currentItem())

    def setCurrentRow(self, row, flags=C.QItemSelectionModel.SelectionFlag.ClearAndSelect):
        self.setCurrentItem(self.item(row), flags)

    def setCurrentItem(self, item, flags=C.QItemSelectionModel.SelectionFlag.ClearAndSelect):
        super().setCurrentItem(item, 0, flags | C.QItemSelectionModel.SelectionFlag.Rows)

    def checkbox_at(self, position):
        item = self.itemAt(position)
        if item is None or self.columnAt(position.x()) != 0:
            return None
        option = W.QStyleOptionViewItem()
        option.initFrom(self)
        option.rect = self.visualItemRect(item)
        option.features |= W.QStyleOptionViewItem.ViewItemFeature.HasCheckIndicator
        option.checkState = item.checkState()
        rect = self.style().subElementRect(W.QStyle.SubElement.SE_ItemViewItemCheckIndicator, option, self)
        return item if rect.contains(position) else None

    def mousePressEvent(self, event):
        item = self.checkbox_at(event.position().toPoint())
        if event.button() == C.Qt.MouseButton.LeftButton and item is not None:
            self.checkbox_id = item.data(C.Qt.ItemDataRole.UserRole)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if self.checkbox_id is not None:
            target, self.checkbox_id = self.checkbox_id, None
            item = self.checkbox_at(event.position().toPoint())
            if item is not None and item.data(C.Qt.ItemDataRole.UserRole) == target:
                item.setCheckState(C.Qt.CheckState.Unchecked if item.checkState() == C.Qt.CheckState.Checked
                                   else C.Qt.CheckState.Checked)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event):
        if self.checkbox_id is None:
            super().mouseMoveEvent(event)


class DataTable(C.QAbstractTableModel):
    edited = C.Signal()
    failed = C.Signal(str)

    def __init__(self, dataset, edit_callback=None):
        super().__init__()
        self.dataset = dataset
        self.edit_callback = edit_callback

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
            if self.edit_callback:
                self.edit_callback(self.dataset, index.row(), index.column(), value)
            else:
                self.dataset.edit(index.row(), index.column(), value)
        except ValueError as error:
            self.failed.emit(str(error))
            return False
        self.dataChanged.emit(index, index)
        if not self.edit_callback:
            self.edited.emit()
        return True


class ImportDialog(W.QDialog):
    def __init__(self, path, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Import preview — choose numeric columns")
        self.resize(800, 550)
        self.path = Path(path)
        self.text = self.path.read_bytes().decode("utf-8")
        instrument_table = spectrum_table(self.text) if self.path.suffix.lower() == '.dat' else None
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
            self.dataset = parse_text(self.table_text, self.delimiter.currentData(), self.header.isChecked(), selected,
                                      self.path.stem, str(self.path))
            self.dataset.source_text = self.text
            if self.path.suffix.lower() == '.dat':
                attach_spectrum_metadata(self.dataset, self.text)
            self.accept()
        except (ValueError, csv.Error) as error:
            self.message.setText(str(error))


class SpmImportDialog(W.QDialog):
    """Preview binary raster channels without treating the payload as text."""
    def __init__(self, path, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Import SPM — choose channels')
        self.resize(800, 550)
        self.channels = load_spm(path)
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
        self.datasets = [bundle_channels(self.datasets)]
        self.accept()


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
        self.setWindowTitle('Group by metadata')
        self.resize(880, 620)
        self.selected_files = list(datasets)
        self.all_files = list(all_datasets) if all_datasets is not None else self.selected_files
        self.level_rows = []
        layout = W.QVBoxLayout(self)
        note = W.QLabel('Add levels to subdivide each parent group. Only fields that vary within a parent '
                        'are offered. Missing values form a “Missing value” subgroup.')
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
            elif not any(metadata_fields(d) for d in self.datasets):
                text = 'These files have no structured metadata. Reimport the original instrument files.'
            else:
                text = 'No varying metadata fields within these parent groups. Try another scope or Replace grouping.'
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


def populate_group_tree(tree, paths, labels=None):
    if labels is None:
        labels = field_labels(n['field'] for path in paths for n in path if n['field'] is not None)
    nodes = {}
    for path in paths:
        parent = tree.invisibleRootItem()
        for depth, node in enumerate(path, 1):
            key = path_key(path[:depth])
            if key not in nodes:
                item = W.QTreeWidgetItem(parent, [node_label(node, labels), '0'])
                item.setToolTip(0, node_label(node))
                item.setData(0, C.Qt.ItemDataRole.UserRole, list(path[:depth]))
                nodes[key] = item
            parent = nodes[key]
            parent.setText(1, str(int(parent.text(1)) + 1))


class MetadataDialog(W.QDialog):
    def __init__(self, dataset, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Metadata — {dataset.name}")
        self.resize(900, 620)
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
        self.preferences = project_preferences()
        self.saved_views = {}
        self.pipeline_presets = {}
        self.dirty = False
        self.external_dirty = False
        self.replaying = False
        self.opening = False
        self.worker = None
        self.loading = False
        self.drawing = False
        self.view = {axis: dict(scale='linear', auto=True, limits=None) for axis in ('x', 'y', 'resy')}
        self.panels = [dict(channels=None, view=self.view)]
        self.active_panel = 0
        self.sync_x = False
        self.panel_axes = []
        self.limit_callbacks = []
        self.stats_region = None
        self.stats_context = None
        self.setWindowTitle("Rogi — Scientific Analysis")
        self.resize(1280, 850)
        self.history = G.QUndoStack(self)
        self.file_menu = self.menuBar().addMenu("File")
        self.edit_menu = self.menuBar().addMenu("Edit")
        self.undo_action = self.history.createUndoAction(self, "Undo")
        self.redo_action = self.history.createRedoAction(self, "Redo")
        self.undo_action.setShortcuts(G.QKeySequence.keyBindings(G.QKeySequence.StandardKey.Undo))
        self.redo_action.setShortcuts(G.QKeySequence.keyBindings(G.QKeySequence.StandardKey.Redo))
        self.edit_menu.addAction(self.undo_action)
        self.edit_menu.addAction(self.redo_action)
        self.history.indexChanged.connect(self.update_dirty)
        self.show_fitting = self.menuBar().addMenu("View").addAction("Show fitting")
        self.saved_views_menu = self.show_fitting.parent().addMenu("Saved views")
        self.refresh_saved_views_menu()
        self.show_fitting.setCheckable(True)
        self.show_plot_controls = self.show_fitting.parent().addAction("Show plot controls")
        self.show_plot_controls.setCheckable(True)
        self.show_statistics = self.show_fitting.parent().addAction("Show statistics")
        self.show_statistics.setCheckable(True)
        toolbar = self.addToolBar("Project")
        self.project_actions = {}
        standard_keys = {"Open project…": G.QKeySequence.StandardKey.Open,
                         "Save": G.QKeySequence.StandardKey.Save,
                         "Save as…": G.QKeySequence.StandardKey.SaveAs}
        for label, function in [("Import…", self.import_file), ("Convert folder…", self.convert_folder),
                                ("Open project…", self.open_project),
                                ("Save", self.save), ("Save as…", lambda: self.save(True)),
                                ("Editable copy", self.make_copy), ("Analysis pipeline…", self.analysis_pipeline),
                                ("Apply pipeline preset…", self.apply_pipeline_preset),
                                ("Reopen analysis recipe…", self.reopen_analysis_recipe),
                                ("2D spectrum map…", self.spectrum_map),
                                ("Export data…", self.export_data),
                                ("Export fit…", self.export_fit), ("Export plot…", self.export_plot)]:
            action = toolbar.addAction(label)
            self.project_actions[label] = action
            if label in standard_keys:
                action.setShortcuts(G.QKeySequence.keyBindings(standard_keys[label]))
            elif label == "Import…":
                action.setShortcut(G.QKeySequence("Ctrl+I"))
            if label in standard_keys or label == "Import…":
                self.file_menu.addAction(action)
            action.triggered.connect(lambda checked=False, fn=function: self.guard(fn))
            if label == "Export fit…":
                self.export_fit_action = action
                action.setVisible(False)
        self.recent_menu = self.file_menu.addMenu("Recent projects")
        self.refresh_recent_projects()
        splitter = W.QSplitter()
        self.setCentralWidget(splitter)
        self.browser = DatasetBrowser()
        self.browser.setMinimumWidth(480)
        self.browser.setSelectionMode(W.QAbstractItemView.SelectionMode.ExtendedSelection)
        self.browser.setToolTip("Highlight rows to select them; check boxes to show them on the plot.")
        browser_panel = W.QWidget()
        browser_layout = W.QVBoxLayout(browser_panel)
        self.search = W.QLineEdit()
        self.search.setPlaceholderText("Search datasets / metadata…")
        self.search.setAccessibleName("Search datasets")
        self.group_filter = W.QComboBox()
        self.group_filter.setAccessibleName("Filter dataset group")
        self.group_filter.addItem("All groups", None)
        self.group_filter.addItem("Ungrouped", "")
        self.favorites_filter = W.QCheckBox('Favorites only')
        self.tag_filter = W.QLineEdit()
        self.tag_filter.setPlaceholderText('Filter tag…')
        self.metadata_filter = W.QLineEdit()
        self.metadata_filter.setPlaceholderText('Filter instrument metadata…')
        self.date_from, self.date_to = W.QLineEdit(), W.QLineEdit()
        self.date_from.setPlaceholderText('Acquisition from YYYY-MM-DD')
        self.date_to.setPlaceholderText('Acquisition through YYYY-MM-DD')
        for widget in (self.tag_filter, self.metadata_filter, self.date_from, self.date_to):
            widget.setAccessibleName(widget.placeholderText())
            widget.textChanged.connect(self.filter_browser)
        self.favorites_filter.toggled.connect(self.filter_browser)
        self.group_tree = W.QTreeWidget()
        self.group_tree.setHeaderLabels(['Groups', 'Files'])
        self.group_tree.setMaximumHeight(240)
        self.group_tree.setVisible(False)
        self.group_tree.itemClicked.connect(self.select_group_node)
        organize = W.QToolButton()
        organize.setText("Organize")
        organize.setPopupMode(W.QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = W.QMenu(organize)
        self.organization_actions = {}
        for label, function in [
                ("Rename…", self.rename_dataset), ("Assign group…", self.assign_group),
                ("Group by metadata…", self.group_by_metadata),
                ("View metadata…", self.view_metadata),
                ("Favorite selected", lambda: self.annotate_selected('favorite', True)),
                ("Unfavorite selected", lambda: self.annotate_selected('favorite', False)),
                ("Edit tags…", self.edit_tags),
                ("Edit comments…", self.edit_comments),
                ("Ungroup selected", lambda: self.set_selected_group("")),
                ("Show selected", lambda: self.set_selected_visibility(True)),
                ("Hide selected", lambda: self.set_selected_visibility(False)),
                ("Select all shown", self.select_all_shown),
                ("Clear selection", self.browser.clearSelection),
                ("Remove selected…", self.remove_selected)]:
            action = menu.addAction(label)
            action.triggered.connect(lambda checked=False, fn=function: self.guard(fn))
            self.organization_actions[label] = action
        organize.setMenu(menu)
        for widget in (self.search, self.group_filter, self.favorites_filter, self.tag_filter,
                       self.metadata_filter, self.date_from, self.date_to, self.group_tree, organize, self.browser):
            browser_layout.addWidget(widget)
        self.selection_info = W.QLabel("0 selected")
        browser_layout.addWidget(self.selection_info)
        date_hint = W.QLabel("Dates: instrument acquisition, not filesystem times.")
        date_hint.setWordWrap(True)
        browser_layout.addWidget(date_hint)
        splitter.addWidget(browser_panel)
        self.search.textChanged.connect(self.filter_browser)
        self.group_filter.currentIndexChanged.connect(self.filter_browser)
        self.browser.itemSelectionChanged.connect(self.selection_changed)
        center = W.QSplitter(C.Qt.Orientation.Vertical)
        splitter.addWidget(center)
        plot_widget = W.QWidget()
        plot_layout = W.QVBoxLayout(plot_widget)
        self.figure = Figure(figsize=(8, 6), layout='constrained')
        self.ax, self.resax = self.figure.subplots(2, 1, sharex=True, gridspec_kw={'height_ratios': [3, 1]})
        self.fit_plot_spec = self.ax.get_subplotspec()
        self.full_plot_spec = self.figure.add_gridspec(1, 1)[0]
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.navigation = PlotNavigationToolbar(self.canvas, self)
        plot_layout.addWidget(self.navigation)
        plot_layout.addWidget(self.canvas)
        self.plot_tabs = W.QTabWidget()
        self.plot_tabs.addTab(plot_widget, 'Line plot')
        self.image_viewer = ImageViewer(self)
        self.image_viewer.profile_created.connect(self.add_dataset)
        self.image_viewer.preview_requested.connect(lambda name: self.guard(lambda: self.preview_image_preset(name)))
        self.plot_tabs.addTab(self.image_viewer, '2D Map')
        self.plot_tabs.currentChanged.connect(self.plot_tab_changed)
        center.addWidget(self.plot_tabs)
        self.table = W.QTableView()
        self.table.setSelectionMode(W.QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setSelectionBehavior(W.QAbstractItemView.SelectionBehavior.SelectItems)
        self.copy_action = G.QAction("Copy table selection with headers", self.table)
        self.paste_action = G.QAction("Paste numeric block", self.table)
        for action, key, function in (
                (self.copy_action, G.QKeySequence.StandardKey.Copy, self.copy_selection),
                (self.paste_action, G.QKeySequence.StandardKey.Paste, self.paste_selection)):
            action.setShortcuts(G.QKeySequence.keyBindings(key))
            action.setShortcutContext(C.Qt.ShortcutContext.WidgetWithChildrenShortcut)
            action.triggered.connect(lambda checked=False, fn=function: self.guard(fn))
            self.table.addAction(action)
            self.edit_menu.addAction(action)
            action.setEnabled(False)
        center.addWidget(self.table)
        self.image_viewer.show_table.toggled.connect(self.update_table_visibility)
        center.setSizes([580, 220])
        panel = W.QWidget()
        layout = W.QVBoxLayout(panel)
        panel_scroll = W.QScrollArea()
        self.analysis_panel = panel_scroll
        panel_scroll.setWidgetResizable(True)
        panel_scroll.setWidget(panel)
        panel_scroll.setMinimumWidth(380)
        panel_scroll.setMaximumWidth(400)
        splitter.addWidget(panel_scroll)
        splitter.setSizes([420, 680, 380])
        self.info = W.QLabel("Import a CSV, TSV, TXT, or DAT file to begin.")
        self.info.setWordWrap(True)
        channels = W.QGroupBox("Axis channels — active dataset")
        channel_form = W.QFormLayout(channels)
        channel_form.setRowWrapPolicy(W.QFormLayout.RowWrapPolicy.WrapLongRows)
        self.x = W.QComboBox()
        self.y = W.QComboBox()
        for axis, combo in [('X', self.x), ('Y', self.y)]:
            combo.setAccessibleName(f'{axis} axis channel')
            combo.setToolTip(f'Choose the numeric channel for the {axis} axis of the selected dataset.')
            combo.setMinimumContentsLength(20)
            combo.setSizeAdjustPolicy(W.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            channel_form.addRow(f'{axis} axis channel', combo)
        self.panel_choice = W.QComboBox()
        self.panel_choice.addItem('Panel 1')
        self.panel_choice.currentIndexChanged.connect(self.activate_panel)
        channel_form.addRow('Active panel', self.panel_choice)
        add_panel = W.QPushButton('Add panel with selected channels')
        add_panel.clicked.connect(lambda: self.add_panel())
        channel_form.addRow(add_panel)
        assign = W.QPushButton('Assign selected channels to active panel')
        assign.clicked.connect(self.assign_panel_channel)
        channel_form.addRow(assign)
        unassign = W.QPushButton('Remove selected dataset from active panel')
        unassign.clicked.connect(self.unassign_panel_channel)
        channel_form.addRow(unassign)
        remove = W.QPushButton('Remove active panel')
        remove.clicked.connect(self.remove_panel)
        channel_form.addRow(remove)
        self.sync_x_control = W.QCheckBox('Synchronize X limits')
        self.sync_x_control.toggled.connect(self.set_sync_x)
        channel_form.addRow(self.sync_x_control)
        layout.addWidget(channels)
        layout.addWidget(self.info)
        form = W.QFormLayout()
        self.style = W.QComboBox()
        self.style.addItems(['Line', 'Scatter'])
        self.title = W.QLineEdit()
        self.xlabel = W.QLineEdit()
        self.ylabel = W.QLineEdit()
        for entry in (self.xlabel, self.ylabel):
            entry.setToolTip('Optional custom label. Clear to follow the visible channel names.')
        for label, widget in [("Style", self.style),
                              ("Plot title", self.title), ("X label", self.xlabel), ("Y label", self.ylabel)]:
            form.addRow(label, widget)
        layout.addLayout(form)
        self.plot_panel = W.QWidget()
        controls = W.QFormLayout(self.plot_panel)
        controls.setContentsMargins(0, 0, 0, 0)
        self.axis_controls = {}
        for axis in ('x', 'y'):
            scale = W.QComboBox()
            scale.addItems(['linear', 'log'])
            auto = W.QCheckBox("Automatic limits")
            auto.setChecked(True)
            low, high = W.QLineEdit(), W.QLineEdit()
            low.setPlaceholderText("Minimum")
            high.setPlaceholderText("Maximum")
            for field, label in ((scale, "scale"), (auto, "automatic limits"),
                                 (low, "minimum"), (high, "maximum")):
                field.setAccessibleName(f"{axis.upper()} axis {label}")
            row = W.QWidget()
            row_layout = W.QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.addWidget(low)
            row_layout.addWidget(high)
            controls.addRow(f"{axis.upper()} scale", scale)
            controls.addRow(auto)
            controls.addRow(row)
            self.axis_controls[axis] = (scale, auto, low, high)
            auto.toggled.connect(lambda checked, lo=low, hi=high: (lo.setEnabled(not checked), hi.setEnabled(not checked)))
        apply = W.QPushButton("Apply axes")
        apply.clicked.connect(lambda: self.guard(self.apply_axes))
        controls.addRow(apply)
        self.color = W.QPushButton("Automatic color")
        self.color.clicked.connect(self.choose_color)
        reset_color = W.QPushButton("Reset color")
        reset_color.clicked.connect(lambda: self.set_color(""))
        controls.addRow("Dataset color", self.color)
        controls.addRow(reset_color)
        self.marker = W.QComboBox()
        for label, value in MARKERS.items():
            self.marker.addItem(label, value)
        self.marker.currentIndexChanged.connect(self.appearance_changed)
        controls.addRow("Dataset marker", self.marker)
        self.legend_position = W.QComboBox()
        self.legend_position.addItems(LEGENDS)
        self.legend_position.currentTextChanged.connect(self.presentation_changed)
        controls.addRow("Legend", self.legend_position)
        self.cursor_enabled = W.QCheckBox("Coordinate cursor")
        self.cursor_enabled.toggled.connect(self.presentation_changed)
        controls.addRow(self.cursor_enabled)
        layout.addWidget(self.plot_panel)
        self.plot_panel.hide()
        self.show_plot_controls.toggled.connect(self.plot_panel.setVisible)
        self.log_notice = W.QLabel()
        self.log_notice.setWordWrap(True)
        layout.addWidget(self.log_notice)
        self.coordinates = W.QLabel("")
        self.statusBar().addPermanentWidget(self.coordinates)
        self.canvas.mpl_connect('motion_notify_event', self.cursor_motion)
        self.sync_axis_controls()
        hint = W.QLabel("Changing channels for a hidden dataset shows it alone. Check datasets to compare curves.")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.stats_panel = W.QGroupBox("Statistics — active dataset Y")
        stats_layout = W.QFormLayout(self.stats_panel)
        self.stats_mode = W.QComboBox()
        self.stats_mode.addItems(["X range", "Rectangle"])
        stats_layout.addRow("Region", self.stats_mode)
        self.stats_bounds = [W.QLineEdit() for _ in range(4)]
        for label, field in zip(("X minimum", "X maximum", "Y minimum", "Y maximum"), self.stats_bounds):
            field.setAccessibleName("Statistics " + label)
            stats_layout.addRow(label, field)
        self.stats_sample = W.QComboBox()
        self.stats_sample.addItems(["Sample (N − 1)", "Population (N)"])
        stats_layout.addRow("Std / variance", self.stats_sample)
        self.stats_drag = W.QCheckBox("Drag on plot to select")
        stats_layout.addRow(self.stats_drag)
        self.stats_calculate = W.QPushButton("Calculate statistics")
        self.stats_calculate.clicked.connect(lambda: self.guard(self.calculate_statistics))
        stats_layout.addRow(self.stats_calculate)
        self.stats_result = W.QPlainTextEdit()
        self.stats_result.setReadOnly(True)
        self.stats_result.setMinimumHeight(220)
        stats_layout.addRow(self.stats_result)
        layout.addWidget(self.stats_panel)
        self.stats_panel.hide()
        self.show_statistics.toggled.connect(self.toggle_statistics)
        self.stats_mode.currentIndexChanged.connect(self.statistics_mode_changed)
        self.stats_sample.currentIndexChanged.connect(self.refresh_statistics)
        self.stats_drag.toggled.connect(self.toggle_statistics_drag)
        for field in self.stats_bounds[2:]:
            field.setEnabled(False)
        self.fit_panel = W.QWidget()
        fit_layout = W.QVBoxLayout(self.fit_panel)
        fit_layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.fit_panel)
        layout.addStretch()
        self.fit_panel.hide()
        self.model = W.QComboBox()
        self.model.addItems(['Linear', 'Gaussian'])
        self.lower, self.upper = W.QLineEdit(), W.QLineEdit()
        fitform = W.QFormLayout()
        fitform.addRow("Model", self.model)
        fitform.addRow("Range minimum", self.lower)
        fitform.addRow("Range maximum", self.upper)
        fit_layout.addLayout(fitform)
        self.drag = W.QCheckBox("Drag to select range (disable pan/zoom)")
        self.drag.toggled.connect(self.toggle_span)
        fit_layout.addWidget(self.drag)
        self.exclude = W.QCheckBox("Exclude rows with missing X/Y")
        fit_layout.addWidget(self.exclude)
        self.fitbutton = W.QPushButton("Fit selected dataset")
        self.fitbutton.clicked.connect(lambda: self.guard(self.start_fit))
        fit_layout.addWidget(self.fitbutton)
        self.result = W.QPlainTextEdit()
        self.result.setReadOnly(True)
        fit_layout.addWidget(self.result)
        self.show_fitting.toggled.connect(self.toggle_fitting)
        self.browser.currentRowChanged.connect(self.select)
        self.browser.itemChanged.connect(lambda item, column: self.visibility(item) if column == 0 else None)
        for combo in (self.x, self.y, self.style):
            combo.currentIndexChanged.connect(self.plot_options)
        for entry in (self.title, self.xlabel, self.ylabel):
            entry.editingFinished.connect(self.labels_changed)
        self.selection_changed()
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
        item = self.browser.currentItem()
        if item is None or item.isHidden() or not item.isSelected():
            return None
        return self.dataset_for_item(item)

    def dataset_for_item(self, item):
        return next((d for d in self.datasets if d.id == item.data(C.Qt.ItemDataRole.UserRole)), None)

    def selected_datasets(self):
        return [self.dataset_for_item(item) for item in self.browser.selectedItems()
                if not item.isHidden()]

    def selection_changed(self):
        count = len(self.selected_datasets())
        self.selection_info.setText(f"{count} selected · checkboxes control plot")
        for label, action in self.organization_actions.items():
            if label == "Rename…":
                action.setEnabled(count == 1)
            elif label not in ("Select all shown", "Clear selection"):
                action.setEnabled(count > 0)
        self.select(self.browser.currentRow())

    def select_all_shown(self):
        with C.QSignalBlocker(self.browser):
            self.browser.clearSelection()
            for row in range(self.browser.count()):
                item = self.browser.item(row)
                item.setSelected(not item.isHidden())
            selected = self.browser.selectedItems()
            if self.current() is None and selected:
                self.browser.setCurrentItem(selected[0], C.QItemSelectionModel.SelectionFlag.NoUpdate)
        self.selection_changed()

    def update_groups(self):
        previous = self.group_filter.currentData()
        with C.QSignalBlocker(self.group_filter):
            self.group_filter.clear()
            self.group_filter.addItem("All groups", None)
            self.group_filter.addItem("Ungrouped", "")
            for group in sorted({d.group for d in self.datasets if d.group and not d.group_path}, key=str.casefold):
                self.group_filter.addItem(group, group)
            paths = {}
            for d in self.datasets:
                path = d.group_path
                for depth in range(1, len(path) + 1):
                    paths.setdefault(path_key(path[:depth]), path[:depth])
            for path in paths.values():
                self.group_filter.addItem('↳ ' + self.display_group_path(path), path)
                self.group_filter.setItemData(self.group_filter.count() - 1, path_label(path),
                                              C.Qt.ItemDataRole.ToolTipRole)
            index = self.group_filter.findData(previous)
            self.group_filter.setCurrentIndex(max(0, index))
        expanded = set()
        iterator = W.QTreeWidgetItemIterator(self.group_tree)
        while iterator.value():
            item = iterator.value()
            if item.isExpanded():
                expanded.add(path_key(item.data(0, C.Qt.ItemDataRole.UserRole) or []))
            iterator += 1
        self.group_tree.clear()
        populate_group_tree(self.group_tree, [group_path(d) for d in self.datasets])
        self.group_tree.setVisible(any(d.group_path for d in self.datasets))
        iterator = W.QTreeWidgetItemIterator(self.group_tree)
        while iterator.value():
            item = iterator.value()
            item.setExpanded(path_key(item.data(0, C.Qt.ItemDataRole.UserRole)) in expanded)
            iterator += 1
        # Adding/removing a field can introduce or remove a short-name collision.
        with C.QSignalBlocker(self.browser):
            for row in range(self.browser.count()):
                item = self.browser.item(row)
                self.update_browser_item(item, self.dataset_for_item(item))

    def select_group_node(self, item, column):
        self.group_filter.setCurrentIndex(self.group_filter.findData(item.data(0, C.Qt.ItemDataRole.UserRole)))

    def filter_browser(self, *args):
        query = self.search.text().strip().casefold()
        group = self.group_filter.currentData()
        bounds = []
        for field in (self.date_from, self.date_to):
            value = field.text().strip()
            valid = not value or C.QDate.fromString(value, 'yyyy-MM-dd').isValid()
            field.setStyleSheet('' if valid else 'border: 1px solid red')
            field.setToolTip('Inclusive acquisition date; unknown dates are excluded. Use YYYY-MM-DD.'
                             if valid else 'Invalid date: use YYYY-MM-DD')
            bounds.append(value if valid else None)
        lower, upper = bounds
        with C.QSignalBlocker(self.browser):
            for row in range(self.browser.count()):
                item = self.browser.item(row)
                d = self.dataset_for_item(item)
                matches = (group_path(d)[:len(group)] == group if isinstance(group, list)
                           else group is None or d.group == group)
                timestamp = acquisition_timestamp(d)
                date = timestamp[:10] if timestamp else None
                hidden = (not matches
                          or query not in f"{d.name} {d.group} {d.source} {d.tags} {d.comments} {metadata_search_text(d)}".casefold()
                          or (self.favorites_filter.isChecked() and not d.favorite)
                          or self.tag_filter.text().strip().casefold() not in ' '.join(d.tags).casefold()
                          or self.metadata_filter.text().strip().casefold() not in metadata_search_text(d).casefold()
                          or lower is None or upper is None
                          or (bool(lower or upper) and (date is None
                              or (bool(lower) and date < lower) or (bool(upper) and date > upper))))
                item.setHidden(hidden)
                if hidden:
                    item.setSelected(False)
            # Reset Qt's pending selection range too, so a later click cannot
            # revive rows that were deselected by a filter.
            selected = self.browser.selectedItems()
            self.browser.clearSelection()
            for item in selected:
                item.setSelected(True)
            current = self.browser.currentItem()
            if current is not None and current.isHidden():
                self.browser.setCurrentItem(selected[0] if selected else None,
                                            C.QItemSelectionModel.SelectionFlag.NoUpdate)
        self.selection_changed()

    def update_browser_item(self, item, dataset):
        label = self.display_group_path(group_path(dataset))
        item.setText(dataset.name + (" [raw]" if dataset.raw else " [derived]")
                     + (f" — {label}" if label else ""))
        timestamp = acquisition_timestamp(dataset)
        item.setText(1, '★' if dataset.favorite else '')
        item.setText(2, timestamp.replace('T', ' ') if timestamp else 'Unknown')
        item.setText(3, str(channel_count(dataset)))
        item.setText(4, ', '.join(dataset.tags))
        item.setText(5, dataset.comments)
        item.setToolTip(2, 'Earliest parsed acquisition timestamp from the instrument. Timezone unspecified. '
                          'Filesystem creation/modification times are not acquisition dates. '
                          'Numeric timestamps without a declared epoch are not interpreted.')
        item.setToolTip(3, 'Scan signal channels; for tables, the number of stored columns.')
        item.setToolTip(5, dataset.comments)
        item.setToolTip(f"{dataset.name}\nGroup: {dataset.group or 'Ungrouped'}"
                        f"\nSource: {dataset.source}\nID: {dataset.id}\nParent: {dataset.parent or 'None'}")

    def display_group_path(self, path):
        labels = field_labels(node['field'] for d in self.datasets for node in d.group_path
                              if node['field'] is not None)
        return path_label(path, labels)

    def annotate_selected(self, attribute, value):
        self.change_attributes(self.selected_datasets(), attribute, value, f'Edit {attribute}')

    def edit_tags(self):
        selected = self.selected_datasets()
        if not selected:
            return
        value, ok = W.QInputDialog.getText(self, 'Edit tags', 'Tags, comma separated (replaces selected tags):',
                                         text=', '.join(selected[0].tags) if len(selected) == 1 else '')
        if ok:
            self.annotate_selected('tags', list(dict.fromkeys(tag.strip() for tag in value.split(',') if tag.strip())))

    def edit_comments(self):
        selected = self.selected_datasets()
        if not selected:
            return
        value, ok = W.QInputDialog.getMultiLineText(self, 'Edit comments', 'Comments (replaces selected comments):',
                                                  selected[0].comments if len(selected) == 1 else '')
        if ok:
            self.annotate_selected('comments', value)

    def rename_dataset(self):
        selected = self.selected_datasets()
        if len(selected) != 1:
            return
        d = selected[0]
        name, ok = W.QInputDialog.getText(self, "Rename dataset", "Display name:", text=d.name)
        if not ok:
            return
        name = name.strip()
        if not name:
            raise ValueError("Dataset name cannot be blank.")
        if name != d.name:
            self.change_attributes([d], 'name', name, f'Rename {d.name} to {name}')

    def assign_group(self):
        if not self.selected_datasets():
            return
        groups = sorted({d.group for d in self.datasets if d.group}, key=str.casefold)
        group, ok = W.QInputDialog.getItem(self, "Assign group", "Group (blank = ungrouped):",
                                          groups, 0, True)
        if ok:
            self.set_selected_group(group.strip())

    def group_by_metadata(self):
        selected = self.selected_datasets()
        dialog = MetadataGroupingDialog(selected, self, all_datasets=self.datasets)
        if dialog.exec() == W.QDialog.DialogCode.Accepted:
            self.group_by_levels(dialog.datasets, dialog.levels, dialog.mode.currentIndex() == 1)

    def group_by_levels(self, datasets, levels, append=False):
        if not levels or not datasets:
            return
        pairs = partitions(datasets, levels, append)
        before = list(self.datasets)
        old = [(d, d.group, deepcopy(d.group_path)) for d, _ in pairs]
        ids = {d.id for d, _ in pairs}
        ordered = iter(d for d, _ in pairs)
        after = [next(ordered) if d.id in ids else d for d in before]
        def apply():
            for d, path in pairs:
                d.group_path = deepcopy(path)
                d.group = path_label(path)
            self.datasets[:] = after
        def revert():
            for d, label, path in old:
                d.group, d.group_path = label, deepcopy(path)
            self.datasets[:] = before
        self.history.push(ChangeCommand(self, 'Group by metadata levels', apply, revert))
        self.statusBar().showMessage(f'Grouped {len(pairs)} files into '
                                    f'{len({path_key(p) for _, p in pairs})} groups.', 6000)

    def group_selected_by_metadata(self, key, descending=False, datasets=None):
        self.group_by_levels(self.selected_datasets() if datasets is None else datasets,
                             [(key, descending)])

    def view_metadata(self):
        d = self.current()
        if d is None:
            raise ValueError("Select a dataset to inspect its metadata.")
        dialog = MetadataDialog(d, self)
        dialog.exec()

    def set_selected_group(self, group):
        selected = self.selected_datasets()
        label = f"Group {len(selected)} dataset(s) as {group}" if group else f"Ungroup {len(selected)} dataset(s)"
        self.change_attributes(selected, 'group', group, label)

    def change_attributes(self, datasets, attribute, value, label):
        changes = [(d, getattr(d, attribute)) for d in datasets
                   if getattr(d, attribute) != value or (attribute == 'group' and d.group_path)]
        if not changes:
            return
        old_paths = {d.id: deepcopy(d.group_path) for d, _ in changes} if attribute == 'group' else {}
        def apply():
            for d, old in changes:
                setattr(d, attribute, deepcopy(value))
                if attribute == 'group':
                    d.group_path = []
        def revert():
            for d, old in changes:
                setattr(d, attribute, deepcopy(old))
                if attribute == 'group':
                    d.group_path = deepcopy(old_paths[d.id])
        self.history.push(ChangeCommand(self, label, apply, revert))

    def set_selected_visibility(self, visible):
        selected = self.selected_datasets()
        self.change_attributes(selected, 'visible', visible,
                               f"{'Show' if visible else 'Hide'} {len(selected)} dataset(s)")

    def remove_selected(self):
        selected = self.selected_datasets()
        if not selected:
            return
        ids = {d.id for d in selected}
        remove_datasets(self.datasets, ids)  # Validate before confirmation.
        answer = W.QMessageBox.question(
            self, "Remove datasets",
            f"Remove {len(selected)} selected dataset(s) from this project?\n"
            + "\n".join(d.name for d in selected)
            + "\n\nTheir data, edits, and fits will be removed. Source files are untouched. Use Edit → Undo to restore them during this session.",
            W.QMessageBox.StandardButton.Yes | W.QMessageBox.StandardButton.Cancel,
            W.QMessageBox.StandardButton.Cancel)
        if answer != W.QMessageBox.StandardButton.Yes:
            return
        removed = [(i, d) for i, d in enumerate(self.datasets) if d.id in ids]
        def apply():
            self.datasets = remove_datasets(self.datasets, ids)
        def revert():
            for index, d in removed:
                self.datasets.insert(index, d)
            self.history_selection = ids
        self.history.push(ChangeCommand(self, f"Remove {len(removed)} dataset(s)", apply, revert))

    def update_dirty(self, *args):
        self.dirty = self.external_dirty or not self.history.isClean()
        self.setWindowTitle(f"Rogi — {self.path.name if self.path else 'Untitled'}" + (" *" if self.dirty else ""))

    def changed(self):
        if not self.replaying and not self.opening:
            self.external_dirty = True
            self.update_dirty()

    def refresh_history_view(self):
        table_model = self.table.model()
        table_dataset_id = table_model.dataset.id if table_model else None
        table_ranges = [(r.top(), r.left(), r.bottom(), r.right())
                        for r in self.table.selectionModel().selection()] if table_model else []
        table_current = self.table.currentIndex()
        current_cell = (table_current.row(), table_current.column()) if table_current.isValid() else None
        selected = getattr(self, 'history_selection', {d.id for d in self.selected_datasets() if d})
        if hasattr(self, 'history_selection'):
            del self.history_selection
        item = self.browser.currentItem()
        current_id = item.data(C.Qt.ItemDataRole.UserRole) if item else None
        # Keep existing items alive while Qt handles a checkbox mouse event.
        # Replacing them mid-event loses the active row and clears channel controls.
        existing = {self.browser.item(row).data(C.Qt.ItemDataRole.UserRole): self.browser.item(row)
                    for row in range(self.browser.count())}
        rebuild = set(existing) != {d.id for d in self.datasets}
        with C.QSignalBlocker(self.browser):
            if rebuild:
                self.browser.clear()
            for row, d in enumerate(self.datasets):
                item = BrowserItem(self.browser) if rebuild else existing[d.id]
                item.setData(C.Qt.ItemDataRole.UserRole, d.id)
                self.update_browser_item(item, d)
                item.setFlags(item.flags() | C.Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(C.Qt.CheckState.Checked if d.visible else C.Qt.CheckState.Unchecked)
                item.setSelected(d.id in selected)
                if d.id == current_id:
                    self.browser.setCurrentItem(item, C.QItemSelectionModel.SelectionFlag.NoUpdate)
            if self.browser.currentItem() is None:
                items = self.browser.selectedItems()
                if items:
                    self.browser.setCurrentItem(items[0], C.QItemSelectionModel.SelectionFlag.NoUpdate)
        if self.browser.sorted_column is not None:
            self.browser.sortItems(self.browser.sorted_column, self.browser.sort_order)
        self.update_groups()
        self.filter_browser()
        model = self.table.model()
        if model and model.dataset.id == table_dataset_id:
            selection = C.QItemSelection()
            for top, left, bottom, right in table_ranges:
                selection.select(model.index(top, left), model.index(bottom, right))
            self.table.selectionModel().select(selection, C.QItemSelectionModel.SelectionFlag.ClearAndSelect)
            if current_cell:
                self.table.selectionModel().setCurrentIndex(model.index(*current_cell), C.QItemSelectionModel.SelectionFlag.NoUpdate)
        self.redraw()

    def update_clipboard_actions(self, *args):
        model = self.table.model()
        selected = bool(self.table.selectionModel() and self.table.selectionModel().hasSelection())
        busy = bool(self.worker and self.worker.isRunning())
        self.copy_action.setEnabled(bool(model and selected and not busy))
        self.paste_action.setEnabled(bool(model and selected and not model.dataset.raw and not busy))

    def copy_selection(self):
        model = self.table.model()
        if model is None:
            raise ValueError("Select a dataset first.")
        rectangle = selection_rectangle(self.table.selectionModel().selectedIndexes())
        text = copy_table(model.dataset, rectangle)
        mime = C.QMimeData()
        mime.setText(text)
        mime.setData(MIME, text.encode('utf-8'))
        W.QApplication.clipboard().setMimeData(mime)
        self.statusBar().showMessage("Copied table selection with column headers.", 3000)

    def select_table_block(self, top, left, height, width):
        model = self.table.model()
        selection = C.QItemSelection(model.index(top, left), model.index(top + height - 1, left + width - 1))
        self.table.selectionModel().select(selection, C.QItemSelectionModel.SelectionFlag.ClearAndSelect)
        self.table.selectionModel().setCurrentIndex(model.index(top, left), C.QItemSelectionModel.SelectionFlag.NoUpdate)

    def paste_selection(self):
        if self.worker and self.worker.isRunning():
            raise ValueError("Wait for the current fit to finish before pasting.")
        model = self.table.model()
        if model is None:
            raise ValueError("Select a dataset first.")
        top, left, _, _ = selection_rectangle(self.table.selectionModel().selectedIndexes())
        mime = W.QApplication.clipboard().mimeData()
        text = mime.text()
        copied_headers = mime.hasFormat(MIME) and bytes(mime.data(MIME)) == text.encode('utf-8')
        values = parse_paste(model.dataset, text, top, left, copied_headers)
        d = model.dataset
        changes = []
        for r, row in enumerate(values):
            for c, value in enumerate(row):
                old = d.values[top + r, left + c]
                if old != value and not (np.isnan(old) and np.isnan(value)):
                    changes.append((top + r, left + c, value))
        if changes:
            self.history.push(CellsCommand(
                self, d, changes, f"Paste {values.shape[0]} × {values.shape[1]} cells into {d.name}"))
        self.select_table_block(top, left, *values.shape)
        self.statusBar().showMessage(f"Pasted {values.shape[0]} × {values.shape[1]} cells; {len(changes)} changed.", 4000)

    def edit_cell(self, dataset, row, column, text):
        if dataset.raw:
            raise ValueError("Raw data is read-only. Create an editable copy first.")
        value = float(text) if str(text).strip() else np.nan
        if np.isinf(value):
            raise ValueError("Use a finite number or a blank for missing data.")
        old = dataset.values[row, column]
        if old == value or (np.isnan(old) and np.isnan(value)):
            return
        self.history.push(CellCommand(self, dataset, row, column, value))

    def add_dataset(self, dataset):
        def apply():
            self.datasets.append(dataset)
            self.history_selection = {dataset.id}
            # Keep the newly added dataset as the inspection target.
            with C.QSignalBlocker(self.browser):
                self.browser.setCurrentItem(None)
        def revert():
            self.datasets = remove_datasets(self.datasets, {dataset.id})
        if self.opening:
            apply()
            self.refresh_history_view()
        else:
            label = "Create analysis dataset" if dataset.analysis else ("Import" if dataset.raw else "Create editable copy")
            self.history.push(ChangeCommand(self, f"{label} {dataset.name}", apply, revert))

    def import_file(self):
        path, _ = W.QFileDialog.getOpenFileName(self, "Import numeric data", "", "Supported data (*.csv *.tsv *.txt *.dat *.spm *.sxm);;SPM scans and curves (*.spm *.sxm);;Text data (*.csv *.tsv *.txt *.dat);;All files (*)")
        if path:
            if Path(path).suffix.lower() in ('.spm', '.sxm'):
                dialog = SpmImportDialog(path, self)
                if not dialog.exec():
                    return
                imported = dialog.datasets
            else:
                dialog = ImportDialog(path, self)
                if not dialog.exec():
                    return
                imported = [dialog.dataset]
            if self.datasets or self.path:
                destination = ImportGroupDialog(imported[0], self.datasets, self.path, self)
                if not destination.exec():
                    return
                for dataset in imported:
                    dataset.group_path = destination.selected_path()
                    dataset.group = path_label(dataset.group_path)
            # Reveal the newly imported file even if the browser was filtered.
            self.search.clear()
            for field in (self.tag_filter, self.metadata_filter, self.date_from, self.date_to):
                field.clear()
            self.favorites_filter.setChecked(False)
            self.group_filter.setCurrentIndex(0)
            for index, dataset in enumerate(imported):
                dataset.visible = index == 0
                self.add_dataset(dataset)
            self.statusBar().showMessage('File added. Use Save to store it in the project.', 6000)

    def convert_folder(self):
        folder = W.QFileDialog.getExistingDirectory(self, 'Select folder of CSV, TSV, TXT, DAT, SPM, or SXM files')
        if not folder:
            return
        folder = Path(folder)
        destination, _ = W.QFileDialog.getSaveFileName(
            self, 'Convert folder to HDF5 project', str(folder.parent / (folder.name + '.rogi.h5')),
            'Rogi HDF5 project (*.h5 *.hdf5)')
        if not destination:
            return
        if not Path(destination).suffix:
            destination += '.h5'
        if not self.confirm_discard():
            return
        count = convert_folder(folder, destination)
        self.open_project(destination, confirm=False)
        self.statusBar().showMessage(f"Created and opened {count} dataset(s) in {destination}", 8000)

    def select(self, row):
        dataset = self.current()
        self.refresh_statistics()
        if dataset is None:
            self.image_viewer.set_context(self.datasets, None)
            self.table.setModel(None)
            self.update_clipboard_actions()
            self.result.clear()
            self.info.setText("Select a dataset to inspect it.")
            self.loading = True
            self.x.clear()
            self.y.clear()
            self.loading = False
            return
        pair = self.panels[self.active_panel]['channels']
        if not self.opening and pair and dataset.id in pair and max(pair[dataset.id]) < len(dataset.columns):
            dataset.xcol, dataset.ycol = pair[dataset.id]
        self.loading = True
        for combo, index in [(self.x, dataset.xcol), (self.y, dataset.ycol)]:
            combo.clear()
            combo.addItems(dataset.columns)
            combo.setCurrentIndex(index)
        self.style.setCurrentText(dataset.style)
        self.color.setText(dataset.color or "Automatic color")
        self.marker.setCurrentIndex(self.marker.findData(dataset.marker))
        table_model = DataTable(dataset, self.edit_cell)
        table_model.edited.connect(self.edited)
        table_model.failed.connect(self.error)
        self.table_model = table_model
        self.table.setModel(table_model)
        self.table.selectionModel().selectionChanged.connect(self.update_clipboard_actions)
        self.update_clipboard_actions()
        missing = int(np.isnan(dataset.values).sum())
        self.info.setText(f"{dataset.name}\n{len(dataset.values)} rows × {len(dataset.columns)} channels; {missing} missing cells\n"
                          + ("Raw data: read-only" if dataset.raw else f"Editable data: revision {dataset.revision}"))
        self.info.setToolTip(f'{dataset.name}\nParent: {dataset.parent or "None"}')
        self.reset_fit_range(dataset, restore_fit=True)
        if dataset.fit:
            self.model.setCurrentText(dataset.fit['model'])
        self.loading = False
        self.show_result()
        self.redraw()

    def edited(self):
        self.changed()
        self.select(self.browser.currentRow())

    def spectrum_map(self, recipe=None):
        from .maps_ui import MapDialog
        sources = self.selected_datasets()
        if recipe is not None:
            ids = recipe['ids']
            lookup = {d.id: d for d in self.datasets}
            if any(i not in lookup for i in ids):
                raise ValueError('A saved map source is missing. Reselect spectra to create a new map.')
            sources = [lookup[i] for i in ids]
        if not sources:
            raise ValueError('Select spectra in the dataset browser first.')
        dialog = MapDialog(sources, self, recipe)
        dialog.exec()

    def analysis_pipeline(self):
        if self.current():
            from .analysis_ui import AnalysisDialog, MultiAnalysisDialog
            selected = self.selected_datasets()
            dialog = MultiAnalysisDialog(selected, self) if len(selected) > 1 else AnalysisDialog(self.current(), self, self.pipeline_presets, self.pipeline_presets_changed)
            if dialog.exec() == W.QDialog.DialogCode.Accepted:
                for result in dialog.datasets if len(selected) > 1 else [dialog.dataset]:
                    self.add_dataset(result)

    def add_analysis_batch(self, results):
        if not results:
            return
        def apply():
            self.datasets.extend(results)
            self.history_selection = {d.id for d in results}
        def revert():
            self.datasets = remove_datasets(self.datasets, {d.id for d in results})
        self.history.push(ChangeCommand(self, f'Apply pipeline to {len(results)} datasets', apply, revert))

    def pipeline_presets_changed(self):
        self.image_viewer.set_presets(self.pipeline_presets)
        self.changed()

    def preview_image_preset(self, name):
        from .image_analysis import ImagePreviewDialog
        from .presets import validate_presets
        source = self.image_viewer.current
        if source is None:
            raise ValueError('Select an image file and channel in 2D Map first.')
        if name not in self.pipeline_presets:
            raise ValueError('The selected preset is no longer available.')
        validate_presets({name: self.pipeline_presets[name]})
        dialog = ImagePreviewDialog(source, self.pipeline_presets[name], name, self,
                                    palette=self.image_viewer.palette.currentText(),
                                    transpose=self.image_viewer.transpose.isChecked())
        try:
            dialog.exec()
        finally:
            dialog.deleteLater()

    def apply_pipeline_preset(self):
        from .analysis_ui import BatchPipelineDialog
        selected = self.selected_datasets()
        if not selected:
            raise ValueError('Select datasets in the browser first.')
        dialog = BatchPipelineDialog(selected, self.pipeline_presets, self)
        if dialog.exec() == W.QDialog.DialogCode.Accepted:
            self.add_analysis_batch(dialog.datasets)

    def reopen_analysis_recipe(self):
        from .analysis_ui import AnalysisDialog
        result = self.current()
        if result is None or not result.analysis or result.analysis.get('version') != 1:
            raise ValueError('Select a result from a single-signal analysis pipeline.')
        record = result.analysis
        source = next((d for d in self.datasets if d.id == record['source']['dataset_id']), None)
        if source is None:
            raise ValueError('The source dataset is unavailable. Its recipe cannot be reopened against the source.')
        dialog = AnalysisDialog(source, self, self.pipeline_presets, self.pipeline_presets_changed)
        dialog.load_operations(record['operations'])
        for axis in ('x', 'y'):
            channel = record['input_channels'][axis]
            if channel['index'] >= len(source.columns) or source.columns[channel['index']] != channel['name']:
                raise ValueError('The original input channels are unavailable.')
            getattr(dialog, axis + 'channel').setCurrentIndex(channel['index'])
            getattr(dialog, axis + 'unit').setText(channel['unit'])
        dialog.name.setText(result.name + ' (rerun)')
        if source.revision != record['source']['revision']:
            dialog.status.setText(f"Source changed: recorded revision {record['source']['revision']}, current revision {source.revision}. Preview will use current data.")
        else:
            dialog.status.setText('Saved recipe loaded against its source. Edit or save a preset, then preview to create a new result.')
        if dialog.exec() == W.QDialog.DialogCode.Accepted:
            self.add_dataset(dialog.dataset)

    def make_copy(self):
        if self.current():
            self.add_dataset(self.current().derived())

    def activate_dataset(self, dataset_id):
        for row in range(self.browser.count()):
            item = self.browser.item(row)
            if item.data(C.Qt.ItemDataRole.UserRole) == dataset_id and not item.isHidden():
                self.browser.setCurrentRow(row, C.QItemSelectionModel.SelectionFlag.ClearAndSelect)
                self.select(row)
                return

    def visibility(self, item):
        if not self.loading:
            d = self.dataset_for_item(item)
            visible = item.checkState() == C.Qt.CheckState.Checked
            active = self.current()
            target_id = d.id if visible else (active.id if active else None)
            self.change_attributes([d], 'visible', visible, f"{'Show' if visible else 'Hide'} {d.name}")
            if target_id is not None:
                self.activate_dataset(target_id)

    def panel_datasets(self, panel):
        if panel['channels'] is None:
            return self.datasets
        result = []
        for d in self.datasets:
            pair = panel['channels'].get(d.id)
            if pair and max(pair) < len(d.columns):
                plotted = copy(d)
                plotted.xcol, plotted.ycol = pair
                result.append(plotted)
        return result

    def freeze_default_panel(self):
        for panel in self.panels:
            if panel['channels'] is None:
                panel['channels'] = {d.id: [d.xcol, d.ycol] for d in self.datasets}

    def refresh_panels(self):
        with C.QSignalBlocker(self.panel_choice):
            self.panel_choice.clear()
            self.panel_choice.addItems([f'Panel {i + 1}' for i in range(len(self.panels))])
            self.panel_choice.setCurrentIndex(self.active_panel)
        self.view = self.panels[self.active_panel]['view']
        with C.QSignalBlocker(self.ylabel):
            self.ylabel.setText(self.panels[self.active_panel].get('ylabel', ''))

    def add_panel(self):
        d = self.current()
        self.freeze_default_panel()
        channels = {d.id: [d.xcol, d.ycol]} if d else {}
        self.panels.append(dict(channels=channels, view={
            axis: dict(scale='linear', auto=True, limits=None) for axis in ('x', 'y', 'resy')}))
        self.activate_panel(len(self.panels) - 1)

    def assign_panel_channel(self):
        d = self.current()
        if d:
            self.freeze_default_panel()
            self.panels[self.active_panel]['channels'][d.id] = [d.xcol, d.ycol]
            self.changed()
            self.redraw()

    def unassign_panel_channel(self):
        d = self.current()
        if d:
            self.freeze_default_panel()
            self.panels[self.active_panel]['channels'].pop(d.id, None)
            self.changed()
            self.redraw()

    def remove_panel(self):
        if len(self.panels) > 1:
            self.panels.pop(self.active_panel)
            self.activate_panel(min(self.active_panel, len(self.panels) - 1))

    def activate_panel(self, index):
        if index < 0 or self.loading:
            return
        self.active_panel = index
        self.refresh_panels()
        channels = self.panels[index]['channels']
        d = self.current()
        if channels:
            if d is None or d.id not in channels:
                d = next((d for d in self.datasets if d.id in channels), None)
            if d and max(channels[d.id]) < len(d.columns):
                d.xcol, d.ycol = channels[d.id]
                self.activate_dataset(d.id)
                self.select(self.browser.currentRow())
        self.sync_axis_controls()
        self.navigation.update()
        self.changed()
        self.redraw()

    def set_sync_x(self, enabled):
        self.sync_x = enabled
        self.changed()
        self.redraw()

    def restore_panels(self, settings):
        self.panels = deepcopy(settings.get('panels', [dict(channels=None, view=self.view, ylabel=settings.get('ylabel', ''))]))
        self.active_panel = settings.get('active_panel', 0)
        self.sync_x = settings.get('sync_x', False)
        with C.QSignalBlocker(self.sync_x_control):
            self.sync_x_control.setChecked(self.sync_x)
        self.refresh_panels()
        d = self.current()
        channels = self.panels[self.active_panel]['channels']
        if d and channels and d.id in channels and max(channels[d.id]) < len(d.columns):
            d.xcol, d.ycol = channels[d.id]
        if d:
            self.select(self.browser.currentRow())

    def plot_options(self):
        if self.loading or not self.current():
            return
        d = self.current()
        x_changed = d.xcol != self.x.currentIndex()
        channels_changed = x_changed or d.ycol != self.y.currentIndex()
        d.xcol, d.ycol, d.style = self.x.currentIndex(), self.y.currentIndex(), self.style.currentText()
        if self.panels[self.active_panel]['channels'] is not None:
            self.panels[self.active_panel]['channels'][d.id] = [d.xcol, d.ycol]
        if channels_changed and not d.visible:
            previous = [(dataset, dataset.visible) for dataset in self.datasets]
            def show_only():
                for dataset, visible in previous:
                    dataset.visible = dataset is d
            def restore_visibility():
                for dataset, visible in previous:
                    dataset.visible = visible
            self.history.push(ChangeCommand(self, f"Show only {d.name} after channel change",
                                            show_only, restore_visibility))
            self.statusBar().showMessage(f'Showing only {d.name}. Check other datasets to compare.', 5000)
        if x_changed:
            self.reset_fit_range(d)
        self.changed()
        self.show_result()
        self.redraw()

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

    def labels_changed(self):
        self.panels[self.active_panel]['ylabel'] = self.ylabel.text()
        self.changed()
        self.redraw()

    def toggle_fitting(self, visible):
        self.fit_panel.setVisible(visible)
        self.export_fit_action.setVisible(visible)
        if not visible:
            self.drag.setChecked(False)
        self.changed()
        self.redraw()

    def toggle_span(self, active):
        if active:
            self.stats_drag.setChecked(False)
            self.disable_navigation()
        if hasattr(self, 'span'):
            self.span.set_active(active)

    def range_selected(self, lower, upper):
        if lower < upper:
            self.lower.setText(f"{lower:.12g}")
            self.upper.setText(f"{upper:.12g}")

    def disable_navigation(self):
        if self.navigation.mode == 'pan/zoom':
            self.navigation.pan()
        elif self.navigation.mode == 'zoom rect':
            self.navigation.zoom()

    def toggle_statistics(self, visible):
        self.stats_panel.setVisible(visible)
        if not visible:
            self.stats_drag.setChecked(False)
        self.refresh_statistics()
        self.redraw()

    def statistics_mode_changed(self, *args):
        for field in self.stats_bounds[2:]:
            field.setEnabled(self.stats_mode.currentIndex() == 1)
        self.stats_region = None
        self.stats_result.setPlainText("Select a region or enter bounds, then calculate.")
        self.redraw()

    def toggle_statistics_drag(self, active):
        if active:
            self.drag.setChecked(False)
            self.disable_navigation()
            d = self.current()
            if d and not d.visible:
                self.statusBar().showMessage("Check the active dataset to see its curve while selecting.", 5000)
        self.redraw()

    def statistics_selected(self, lower, upper, ylower=None, yupper=None):
        bounds = (lower, upper, ylower, yupper)
        for field, value in zip(self.stats_bounds, bounds):
            if value is not None:
                field.setText(f"{value:.17g}")
        self.guard(self.calculate_statistics)

    def statistics_rectangle_selected(self, press, release):
        if None not in (press.xdata, press.ydata, release.xdata, release.ydata):
            self.statistics_selected(*sorted((press.xdata, release.xdata)),
                                     *sorted((press.ydata, release.ydata)))

    def calculate_statistics(self):
        d = self.current()
        if d is None:
            raise ValueError("Select an active dataset first.")
        bounds = [float(field.text()) for field in self.stats_bounds[:2]]
        bounds += ([float(field.text()) for field in self.stats_bounds[2:]]
                   if self.stats_mode.currentIndex() else [None, None])
        # Validate before replacing a previous valid selection.
        region_statistics(d, *bounds, sample=self.stats_sample.currentIndex() == 0)
        self.stats_context = (d.id, d.xcol, d.ycol)
        self.stats_region = tuple(bounds)
        self.refresh_statistics()
        self.redraw()

    def refresh_statistics(self, *args):
        d = self.current()
        context = (d.id, d.xcol, d.ycol) if d else None
        if context != self.stats_context:
            self.stats_context = context
            self.stats_region = None
            for field in self.stats_bounds:
                field.clear()
        if not d or self.stats_region is None:
            self.stats_result.setPlainText("Select a dataset and drag a region, or enter bounds and calculate.")
            return
        result = region_statistics(d, *self.stats_region, sample=self.stats_sample.currentIndex() == 0)
        lo, hi, ylo, yhi = self.stats_region
        lines = [d.name, f"Y: {d.columns[d.ycol]} · X: {d.columns[d.xcol]}",
                 f"X range: [{lo:.8g}, {hi:.8g}] (inclusive)"]
        if ylo is not None:
            lines.append(f"Y range: [{ylo:.8g}, {yhi:.8g}] (inclusive)")
        lines += [f"Count: {result['count']}",
                  f"Missing X (whole dataset): {result['missing_x']}",
                  f"Missing Y within X range: {result['missing_y']}",
                  "Std / variance: " + ("sample (N − 1)" if result['sample'] else "population (N)")]
        for key, label in (('minimum', 'Minimum'), ('maximum', 'Maximum'), ('mean', 'Mean'),
                           ('median', 'Median'), ('std', 'Standard deviation'), ('variance', 'Variance'),
                           ('sem', 'Standard error of mean'), ('sum', 'Sum'), ('rms', 'RMS'),
                           ('q1', '25th percentile'), ('q3', '75th percentile')):
            value = result[key]
            lines.append(f"{label}: " + (f"{value:.10g}" if value is not None else "N/A"))
        lines += ["N/A: insufficient observations or result outside numeric range.",
                  "Stored values, not fitted/interpolated points. Log-hidden values are included if within bounds."]
        self.stats_result.setPlainText("\n".join(lines))

    def sync_axis_controls(self):
        for axis, (scale, auto, low, high) in self.axis_controls.items():
            state = self.view[axis]
            scale.setCurrentText(state['scale'])
            auto.setChecked(state['auto'])
            limits = state['limits'] or (0, 1)
            low.setText(f"{limits[0]:.12g}")
            high.setText(f"{limits[1]:.12g}")
            low.setEnabled(not state['auto'])
            high.setEnabled(not state['auto'])

    def apply_axes(self):
        proposed = {}
        settings = {}
        for axis, (scale, auto, low, high) in self.axis_controls.items():
            limits = None if auto.isChecked() else [float(low.text()), float(high.text())]
            if limits is not None and limits[0] >= limits[1]:
                raise ValueError("Axis minimum must be less than maximum.")
            proposed[axis] = dict(scale=scale.currentText(), auto=auto.isChecked(), limits=limits)
            settings.update({axis + 'scale': scale.currentText(), axis + 'auto': auto.isChecked()})
            if limits is not None:
                settings[axis + 'lim'] = limits
        validate_view(settings)
        self.view.update(proposed)
        # Applying automatic axes also resets any residual-panel zoom.
        self.view['resy'] = dict(scale='linear', auto=True, limits=None)
        self.changed()
        self.redraw()
        self.navigation.update()

    def choose_color(self):
        if self.current():
            color = W.QColorDialog.getColor(parent=self, title="Dataset color")
            if color.isValid():
                self.set_color(color.name())

    def set_color(self, color):
        if self.current() and self.current().color != color:
            self.current().color = color
            self.color.setText(color or "Automatic color")
            self.changed()
            self.redraw()

    def appearance_changed(self):
        if not self.loading and self.current():
            self.current().marker = self.marker.currentData()
            self.changed()
            self.redraw()

    def presentation_changed(self, *args):
        if not self.loading:
            self.changed()
            self.redraw()

    def cursor_motion(self, event):
        if (self.cursor_enabled.isChecked() and event.inaxes in [a for pair in self.panel_axes for a in pair]
                and event.xdata is not None and event.ydata is not None):
            for line in getattr(self, 'shared_cursor_lines', []):
                line.set_xdata([event.xdata, event.xdata])
                line.set_visible(True)
            self.canvas.draw_idle()
            label = "Residual" if event.inaxes is self.resax else "Y"
            self.coordinates.setText(f"X: {event.xdata:.7g}   {label}: {event.ydata:.7g}")
        else:
            self.coordinates.clear()
            for line in getattr(self, 'shared_cursor_lines', []):
                line.set_visible(False)
            self.canvas.draw_idle()

    def limits_changed(self, axis, axes):
        if self.drawing:
            return
        limits = list(axes.get_xlim() if axis == 'x' else axes.get_ylim())
        panel_index = next((i for i, pair in enumerate(self.panel_axes) if axes in pair), self.active_panel)
        state = self.panels[panel_index]['view'][axis]
        if axis == 'x' and self.sync_x:
            self.drawing = True
            try:
                for panel, pair in zip(self.panels, self.panel_axes):
                    panel['view']['x'].update(auto=False, limits=limits)
                    for target in pair:
                        if target is not axes:
                            target.set_xlim(limits)
            finally:
                self.drawing = False
            self.sync_axis_controls()
            self.changed()
        if state['limits'] != limits:
            state.update(auto=False, limits=limits)
            self.sync_axis_controls()
            self.changed()

    def update_table_visibility(self, *args):
        self.table.setVisible(self.plot_tabs.currentIndex() == 0 or self.image_viewer.show_table.isChecked())

    def plot_tab_changed(self, index):
        self.update_table_visibility()
        self.analysis_panel.setVisible(index == 0)
        self.image_viewer.set_context(self.datasets, self.current())

    def redraw(self):
        self.image_viewer.set_context(self.datasets, self.current())
        self.drawing = True
        try:
            self.draw_plot()
        finally:
            self.drawing = False

    def draw_plot(self):
        for axes, callback in self.limit_callbacks:
            axes.callbacks.disconnect(callback)
        self.limit_callbacks.clear()
        if hasattr(self, 'span'):
            self.span.disconnect_events()
        if hasattr(self, 'stats_selector'):
            self.stats_selector.disconnect_events()
        for cursor in getattr(self, 'cursors', []):
            cursor.disconnect_events()
        self.cursors = []
        if len(self.panel_axes) != len(self.panels):
            self.figure.clear()
            self.panel_grid = self.figure.add_gridspec(len(self.panels), 1)
            self.panel_axes = []
            self.panel_fit_specs = []
            for i in range(len(self.panels)):
                sub = self.panel_grid[i].subgridspec(2, 1, height_ratios=[3, 1])
                ax = self.figure.add_subplot(sub[0])
                resax = self.figure.add_subplot(sub[1], sharex=ax)
                self.panel_axes.append((ax, resax))
                self.panel_fit_specs.append(sub[0])
            self.navigation.update()
        self.panel_log_notices = []
        active_view = self.panels[self.active_panel]['view']
        if self.sync_x:
            for panel in self.panels:
                panel['view']['x'] = deepcopy(active_view['x'])
        for i in [j for j in range(len(self.panels)) if j != self.active_panel] + [self.active_panel]:
            self.ax, self.resax = self.panel_axes[i]
            self.view = self.panels[i]['view']
            self.fit_plot_spec = self.panel_fit_specs[i]
            self.full_plot_spec = self.panel_grid[i]
            self.draw_panel(i)
        if self.sync_x:
            limits = self.ax.get_xlim()
            for panel, pair in zip(self.panels, self.panel_axes):
                panel['view']['x']['limits'] = list(limits)
                pair[0].set_xlim(limits)
        self.log_notice.setText(("Log axes require positive values. Not drawn: "
                                 + "; ".join(self.panel_log_notices)
                                 + ". Stored data and fits are unchanged.") if self.panel_log_notices else "")
        self.log_notice.setVisible(bool(self.panel_log_notices))
        self.shared_cursor_lines = [ax.axvline(0, visible=False, color='gray', linewidth=.7)
                                    for pair in self.panel_axes for ax in pair if ax.get_visible()]
        self.sync_axis_controls()
        self.canvas.draw_idle()

    def draw_panel(self, panel_index):
        active = panel_index == self.active_panel
        plotted_datasets = self.panel_datasets(self.panels[panel_index])
        self.coordinates.clear()
        self.ax.clear()
        self.resax.clear()
        # Empty axes otherwise retain limits contributed by old cursor artists.
        self.ax.dataLim = Bbox.null()
        self.resax.dataLim = Bbox.null()
        fitting = self.show_fitting.isChecked() and active
        self.resax.set_visible(fitting)
        self.ax.set_subplotspec(self.fit_plot_spec if fitting else self.full_plot_spec)
        self.ax.tick_params(labelbottom=not fitting)
        notices = []
        palette = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd',
                   '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf']
        color_indices = {d.id: i for i, d in enumerate(self.datasets)}
        for d in plotted_datasets:
            if not d.visible:
                continue
            color = d.color or palette[color_indices[d.id] % len(palette)]
            x, y, excluded = display_values(d.values[:, d.xcol], d.values[:, d.ycol],
                                            self.view['x']['scale'], self.view['y']['scale'])
            if excluded:
                notices.append(f"{d.name}: {excluded} data row(s)")
            if d.style == 'Scatter':
                self.ax.scatter(x, y, s=14, label=d.name, color=color, marker=d.marker or 'o')
            else:
                self.ax.plot(x, y, label=d.name, color=color, marker=d.marker or 'None')
            if (d.analysis and d.analysis.get('version') == 2 and d.analysis.get('operation') == 'mean'
                    and (d.xcol, d.ycol) == (0, 1)):
                sd = d.values[:, 2]
                lower, upper = y - sd, y + sd
                if self.view['y']['scale'] == 'log':
                    lower = np.where(lower > 0, lower, np.nan)
                    upper = np.where(upper > 0, upper, np.nan)
                self.ax.fill_between(x, lower, upper, color=color, alpha=.2, label=d.name + ' ±1 sample SD (not SEM)')
            if fitting and d.fit and (d.fit['xcol'], d.fit['ycol']) == (d.xcol, d.ycol):
                fit = d.fit
                order = np.argsort(fit['x'])
                fx, fy, count = display_values(np.array(fit['x'])[order], np.array(fit['predicted'])[order],
                                               self.view['x']['scale'], self.view['y']['scale'])
                if count:
                    notices.append(f"{d.name}: {count} fit point(s)")
                self.ax.plot(fx, fy, '--', label=d.name + ' fit', color=color)
                rx, ry, _ = display_values(fit['x'], fit['residuals'], self.view['x']['scale'], 'linear')
                self.resax.scatter(rx, ry, s=10, label=d.name, color=color)
        self.panel_log_notices.extend(
            (f'Panel {panel_index + 1}: ' if len(self.panels) > 1 else '') + notice
            for notice in notices)
        panel_title = self.title.text()
        if len(self.panels) > 1:
            panel_title = f"Panel {panel_index + 1}" + (' (active)' if active else '') + (f' — {panel_title}' if panel_title else '')
        self.ax.set_title(panel_title)
        visible = [d for d in plotted_datasets if d.visible]
        x_label = ', '.join(dict.fromkeys(d.columns[d.xcol] for d in visible)) or 'X'
        y_label = ', '.join(dict.fromkeys(d.columns[d.ycol] for d in visible)) or 'Y'
        self.xlabel.setPlaceholderText(x_label)
        self.ylabel.setPlaceholderText(y_label)
        self.ax.set_ylabel(self.panels[panel_index].get('ylabel', self.ylabel.text() if len(self.panels) == 1 else '') or y_label)
        self.resax.set_xlabel(self.xlabel.text() or x_label)
        self.ax.set_xlabel("" if fitting else self.resax.get_xlabel())
        self.resax.set_ylabel("Residual")
        self.resax.axhline(0, color='gray', linewidth=0.8)
        # No positive data has a deterministic log view, without clipping values.
        for axis in ('x', 'y'):
            state = self.view[axis]
            if state['scale'] == 'log':
                interval = self.ax.dataLim.intervalx if axis == 'x' else self.ax.dataLim.intervaly
                if not np.isfinite(interval).all() or max(interval) <= 0:
                    getattr(self.ax, 'set_' + axis + 'lim')(1, 10)
            getattr(self.ax, 'set_' + axis + 'scale')(state['scale'], **({'nonpositive': 'mask'} if state['scale'] == 'log' else {}))
        for axis, axes in (('x', self.ax), ('y', self.ax), ('resy', self.resax)):
            state = self.view[axis]
            coordinate = 'x' if axis == 'x' else 'y'
            if state['auto']:
                interval = axes.dataLim.intervalx if coordinate == 'x' else axes.dataLim.intervaly
                empty_log = state['scale'] == 'log' and (not np.isfinite(interval).all() or max(interval) <= 0)
                if empty_log:
                    getattr(axes, 'set_' + coordinate + 'lim')(1, 10)
                else:
                    getattr(axes, 'set_autoscale' + coordinate + '_on')(True)
                    axes.autoscale_view(scalex=coordinate == 'x', scaley=coordinate == 'y')
            elif state['limits'] is not None:
                getattr(axes, 'set_' + coordinate + 'lim')(state['limits'])
            state['limits'] = list(getattr(axes, 'get_' + coordinate + 'lim')())
        for axes in (self.ax, self.resax):
            axes.grid(True, alpha=0.2)
            if axes.get_legend_handles_labels()[0] and self.legend_position.currentText() != 'hidden':
                axes.legend(fontsize=8, loc=self.legend_position.currentText())
        # Interactive artists must not participate in automatic data limits.
        # Automatic ranges are recomputed explicitly on the next redraw.
        for axes in (self.ax, self.resax):
            axes.set_autoscalex_on(False)
            axes.set_autoscaley_on(False)
        if active:
            self.refresh_statistics()
            self.span = SpanSelector(self.ax, self.range_selected, 'horizontal', useblit=True,
                                     interactive=True, props=dict(alpha=0.2, facecolor='tab:blue'))
            self.span.set_active(self.drag.isChecked())
            if self.stats_mode.currentIndex() == 0:
                self.stats_selector = SpanSelector(self.ax, self.statistics_selected, 'horizontal',
                                                   useblit=True, interactive=True,
                                                   props=dict(alpha=.18, facecolor='tab:green'))
            else:
                self.stats_selector = RectangleSelector(self.ax, self.statistics_rectangle_selected,
                                                        useblit=True, interactive=True,
                                                        props=dict(alpha=.18, facecolor='tab:green'))
            if self.stats_region is not None and self.show_statistics.isChecked():
                self.stats_selector.extents = (self.stats_region[:2] if self.stats_mode.currentIndex() == 0
                                               else self.stats_region)
                self.stats_selector.set_visible(True)
            self.stats_selector.set_active(self.stats_drag.isChecked() and self.show_statistics.isChecked())
        self.cursors += [Cursor(axes, useblit=False, color='gray', linewidth=.7) for axes in (self.ax, self.resax)]
        for cursor in self.cursors:
            cursor.set_active(self.cursor_enabled.isChecked())
        self.sync_axis_controls()
        for axis, axes, event in [('x', self.ax, 'xlim_changed'), ('x', self.resax, 'xlim_changed'),
                                  ('y', self.ax, 'ylim_changed'), ('resy', self.resax, 'ylim_changed')]:
            callback = axes.callbacks.connect(event, lambda ax, key=axis: self.limits_changed(key, ax))
            self.limit_callbacks.append((axes, callback))
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
        channels = self.panels[self.active_panel]['channels']
        if self.current() and channels is not None and self.current().id not in channels:
            raise ValueError('Assign the active dataset to this panel before fitting.')
        if not self.current():
            raise ValueError("Import or select a dataset first.")
        lower, upper = float(self.lower.text()), float(self.upper.text())
        self.worker = FitWorker(self.current(), self.model.currentText(), lower, upper, self.exclude.isChecked(), self)
        self.worker.result.connect(self.fit_ready)
        self.worker.failed.connect(self.error)
        self.worker.finished.connect(self.fit_finished)
        self.centralWidget().setEnabled(False)
        self.edit_menu.setEnabled(False)
        self.file_menu.setEnabled(False)
        for action in self.project_actions.values():
            action.setEnabled(False)
        self.copy_action.setEnabled(False)
        self.paste_action.setEnabled(False)
        self.undo_action.setEnabled(False)
        self.redo_action.setEnabled(False)
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
        self.edit_menu.setEnabled(True)
        self.file_menu.setEnabled(True)
        for action in self.project_actions.values():
            action.setEnabled(True)
        self.update_clipboard_actions()
        self.undo_action.setEnabled(self.history.canUndo())
        self.redo_action.setEnabled(self.history.canRedo())
        self.findChild(W.QToolBar).setEnabled(True)
        self.statusBar().showMessage("Fit operation finished", 4000)

    def refresh_saved_views_menu(self):
        menu = self.saved_views_menu
        menu.clear()
        menu.addAction("Save current view…", lambda: self.guard(self.prompt_save_view))
        for name in self.saved_views:
            entry = menu.addMenu(name)
            entry.addAction("Restore", lambda checked=False, n=name: self.guard(lambda: self.restore_view(n)))
            entry.addAction("Rename…", lambda checked=False, n=name: self.guard(lambda: self.prompt_rename_view(n)))
            entry.addAction("Delete", lambda checked=False, n=name: self.delete_view(n))

    def prompt_save_view(self):
        name, ok = W.QInputDialog.getText(self, "Save view", "View name:")
        if ok:
            self.create_view(name)

    def prompt_rename_view(self, name):
        new_name, ok = W.QInputDialog.getText(self, "Rename view", "View name:", text=name)
        if ok:
            self.rename_view(name, new_name)

    def view_name(self, name, previous=None):
        name = name.strip()
        if not name:
            raise ValueError("Enter a view name.")
        if name in self.saved_views and name != previous:
            raise ValueError("A view with that name already exists.")
        return name

    def create_view(self, name):
        from .views import validate_saved_views
        name = self.view_name(name)
        plot = self.settings()
        plot.pop('saved_views', None)
        plot.pop('pipeline_presets', None)
        snapshot = dict(plot=plot, active=self.current().id if self.current() else None,
                        mode=self.plot_tabs.currentIndex(), image=self.image_viewer.snapshot(),
                        datasets={d.id: dict(visible=d.visible, xcol=d.xcol, ycol=d.ycol)
                                  for d in self.datasets})
        validate_saved_views({name: snapshot})
        self.saved_views[name] = deepcopy(snapshot)
        self.refresh_saved_views_menu()
        self.changed()

    def rename_view(self, name, new_name):
        new_name = self.view_name(new_name, name)
        self.saved_views = {new_name if key == name else key: value
                            for key, value in self.saved_views.items()}
        self.refresh_saved_views_menu()
        self.changed()

    def delete_view(self, name):
        del self.saved_views[name]
        self.refresh_saved_views_menu()
        self.changed()

    def restore_view(self, name):
        snapshot = deepcopy(self.saved_views[name])
        if snapshot.get('kind') == 'spectrum_map':
            self.spectrum_map(snapshot['recipe'])
            return
        settings = snapshot['plot']
        for dataset in self.datasets:
            state = snapshot['datasets'].get(dataset.id)
            if state:
                dataset.visible = state['visible']
                for field in ('xcol', 'ycol'):
                    if state[field] < len(dataset.columns):
                        setattr(dataset, field, state[field])
        self.search.clear()
        self.group_filter.setCurrentIndex(0)
        self.refresh_history_view()
        active = next((d for d in self.datasets if d.id == snapshot['active']), None)
        if active is None:
            active = next((d for d in self.datasets if d.visible),
                          self.datasets[0] if self.datasets else None)
        if active:
            self.activate_dataset(active.id)
            self.select(self.browser.currentRow())
        self.loading = True
        for field in ('title', 'xlabel', 'ylabel'):
            getattr(self, field).setText(settings.get(field, ''))
        self.legend_position.setCurrentText(settings.get('legend', 'best'))
        self.cursor_enabled.setChecked(settings.get('cursor', False))
        self.show_fitting.setChecked(settings.get('show_fitting', False))
        self.loading = False
        for axis in self.view:
            self.view[axis] = dict(scale=settings.get(axis + 'scale', 'linear'),
                                  auto=settings.get(axis + 'auto', True),
                                  limits=settings.get(axis + 'lim'))
        self.restore_panels(settings)
        self.redraw()
        self.plot_tabs.setCurrentIndex(snapshot['mode'])
        self.image_viewer.restore_snapshot(snapshot['image'], self.datasets, active)
        self.navigation.update()
        self.changed()
        missing = set(snapshot['datasets']) - {d.id for d in self.datasets}
        if missing:
            self.statusBar().showMessage(f"Restored view; skipped {len(missing)} missing dataset(s).", 6000)

    def settings(self):
        settings = dict(title=self.title.text(), xlabel=self.xlabel.text(), ylabel=self.ylabel.text(),
                        selected_dataset_id=self.current().id if self.current() else None,
                        legend=self.legend_position.currentText(), cursor=self.cursor_enabled.isChecked(),
                        show_fitting=self.show_fitting.isChecked())
        for axis, state in self.view.items():
            settings.update({axis + 'scale': state['scale'], axis + 'auto': state['auto'],
                             axis + 'lim': state['limits']})
        settings.update(panels=deepcopy(self.panels), active_panel=self.active_panel, sync_x=self.sync_x)
        settings['saved_views'] = deepcopy(self.saved_views)
        settings['pipeline_presets'] = deepcopy(self.pipeline_presets)
        return settings

    def recent_projects(self):
        paths = self.preferences.value('recent_projects', [], type=list)
        return list(dict.fromkeys(str(Path(path).resolve()) for path in paths
                                  if isinstance(path, str) and Path(path).is_file()))[:10]

    def refresh_recent_projects(self):
        self.recent_menu.clear()
        paths = self.recent_projects()
        self.recent_menu.setEnabled(bool(paths))
        for path in paths:
            action = self.recent_menu.addAction(path.replace('&', '&&'))
            action.triggered.connect(lambda checked=False, p=path: self.guard(lambda: self.open_project(p)))

    def remember_project(self, path):
        path = str(Path(path).resolve())
        paths = [path] + [p for p in self.recent_projects() if p != path]
        self.preferences.setValue('recent_projects', paths[:10])
        self.preferences.sync()
        self.refresh_recent_projects()

    def suggest_recent_project(self):
        paths = self.recent_projects()
        if not paths or self.path is not None or self.datasets:
            return
        path, ok = W.QInputDialog.getItem(self, "Recent projects",
            "Open a recent project (Cancel starts an empty workspace):", paths, 0, False)
        if ok and path:
            self.guard(lambda: self.open_project(path))

    def save(self, save_as=False):
        path = self.path
        if path is None or save_as:
            default = Path(path).with_suffix('.h5') if path else Path('analysis.rogi.h5')
            name, chosen = W.QFileDialog.getSaveFileName(self, "Save project", str(default),
                "Rogi HDF5 project (*.h5 *.hdf5);;Rogi JSON project (*.json)")
            if not name:
                return False
            path = Path(name)
            if path.suffix.lower() not in ('.h5', '.hdf5', '.json'):
                path = Path(str(path) + ('.json' if 'JSON' in chosen else '.h5'))
        save_project(path, self.datasets, self.settings())
        self.path = Path(path)
        self.remember_project(path)
        self.external_dirty = False
        self.history.setClean()
        self.update_dirty()
        return True

    def confirm_discard(self):
        if not self.dirty:
            return True
        answer = W.QMessageBox.question(self, "Unsaved project", "Save changes before continuing?",
                                       W.QMessageBox.StandardButton.Save | W.QMessageBox.StandardButton.Discard | W.QMessageBox.StandardButton.Cancel)
        if answer == W.QMessageBox.StandardButton.Save:
            return bool(self.guard(self.save))
        return answer == W.QMessageBox.StandardButton.Discard

    def open_project(self, path=None, *, confirm=True):
        if confirm and not self.confirm_discard():
            return
        if path is None:
            path, _ = W.QFileDialog.getOpenFileName(self, "Open project", "", "Rogi projects (*.h5 *.hdf5 *.json)")
        if path:
            datasets, settings = load_project(path)
            datasets, selected_id = consolidate_legacy(datasets, settings.get('selected_dataset_id'))
            settings['selected_dataset_id'] = selected_id
            self.saved_views = deepcopy(settings.get('saved_views', {}))
            self.pipeline_presets = deepcopy(settings.get('pipeline_presets', {}))
            self.image_viewer.set_presets(self.pipeline_presets)
            self.refresh_saved_views_menu()
            self.opening = True
            self.history.clear()
            self.stats_region = None
            self.stats_context = None
            self.stats_drag.setChecked(False)
            self.search.clear()
            for field in (self.tag_filter, self.metadata_filter, self.date_from, self.date_to):
                field.clear()
            self.favorites_filter.setChecked(False)
            self.group_filter.setCurrentIndex(0)
            with C.QSignalBlocker(self.browser):
                self.browser.clear()
                self.datasets = []
            self.update_groups()
            self.selection_changed()
            self.table.setModel(None)
            self.result.clear()
            for field in ('title', 'xlabel', 'ylabel'):
                getattr(self, field).setText(settings.get(field, ''))
            for d in datasets:
                self.add_dataset(d)
            if datasets:
                fallback = next((i for i, d in enumerate(datasets) if d.visible), 0)
                row = next((i for i, d in enumerate(datasets)
                            if d.id == settings.get('selected_dataset_id')), fallback)
                self.activate_dataset(datasets[row].id)
            self.loading = True
            self.legend_position.setCurrentText(settings.get('legend', 'best'))
            self.cursor_enabled.setChecked(settings.get('cursor', False))
            with C.QSignalBlocker(self.show_fitting):
                self.show_fitting.setChecked(settings.get('show_fitting', False))
            self.fit_panel.setVisible(self.show_fitting.isChecked())
            self.export_fit_action.setVisible(self.show_fitting.isChecked())
            self.drag.setChecked(False)
            self.loading = False
            for axis in self.view:
                self.view[axis] = dict(scale=settings.get(axis + 'scale', 'linear'),
                                      auto=settings.get(axis + 'auto', axis + 'lim' not in settings),
                                      limits=settings.get(axis + 'lim'))
            self.restore_panels(settings)
            self.redraw()
            self.navigation.update()
            self.path = Path(path)
            self.remember_project(path)
            self.opening = False
            self.external_dirty = False
            self.history.setClean()
            self.update_dirty()
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
        path, chosen = W.QFileDialog.getSaveFileName(self, "Export plot", "plot.png", "PNG (*.png);;SVG (*.svg)")
        if path:
            if not Path(path).suffix:
                path += '.svg' if chosen.startswith('SVG') else '.png'
            if Path(path).suffix.lower() not in ('.png', '.svg'):
                raise ValueError("Choose a .png or .svg filename.")
            figure = self.image_viewer.figure if self.plot_tabs.currentIndex() == 1 else self.figure
            figure.savefig(path, dpi=180)

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
    C.QTimer.singleShot(0, window.suggest_recent_project)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
