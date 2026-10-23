"""Folder file list for bringing data in: browse, filter, preview and load files.

The panel only lists and selects files. It asks the window to load or open them
through its signals, and the window reports which sources are already loaded.
"""
from pathlib import Path
from PySide6 import QtCore as C, QtWidgets as W, QtGui as G
from .files import KINDS, KIND_LABELS, scan_folder, file_kind, is_project, resolved, file_summary

PATH_ROLE = C.Qt.ItemDataRole.UserRole
GROUPING = (('ask', 'Choose once (suggested from metadata)'),
            ('folders', 'Subfolder names'),
            ('root', 'Project root (ungrouped)'))
# New files are loaded only once their size stops changing between checks.
SETTLE_MS = 1000


class FileList(W.QListWidget):
    """Drags carry file URLs, so files can be dropped on the dataset list."""

    def mimeData(self, items):
        mime = C.QMimeData()
        mime.setUrls([C.QUrl.fromLocalFile(item.data(PATH_ROLE)) for item in items])
        return mime


class FilesPanel(W.QWidget):
    load_requested = C.Signal(list, dict)
    open_project_requested = C.Signal(str)
    convert_requested = C.Signal(str)
    folder_changed = C.Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.folder = None
        self.scanned = False   # the first listing of a folder marks nothing as new
        self.loaded = set()
        self.loaded_sources = set  # the window supplies the project's loaded sources
        self.sizes = {}         # resolved path -> size at the previous scan
        self.new = set()        # appeared since the folder was chosen
        self.pending = set()    # new files waiting to settle before auto-load
        layout = W.QVBoxLayout(self)
        layout.setContentsMargins(6, 0, 0, 0)

        row = W.QHBoxLayout()
        self.folder_edit = W.QLineEdit()
        self.folder_edit.setPlaceholderText('Data folder')
        self.folder_edit.setAccessibleName('Data folder')
        self.folder_edit.editingFinished.connect(lambda: self.set_folder(self.folder_edit.text().strip() or None))
        browse = W.QPushButton('Browse…')
        browse.clicked.connect(self.browse)
        self.refresh_button = W.QPushButton('Refresh')
        self.refresh_button.setToolTip('List files written since the last refresh')
        self.refresh_button.clicked.connect(self.refresh)
        row.addWidget(self.folder_edit, 1)
        row.addWidget(browse)
        row.addWidget(self.refresh_button)
        layout.addLayout(row)

        types = W.QHBoxLayout()
        self.kind_boxes = {}
        for kind in KINDS:
            box = self.kind_boxes[kind] = W.QCheckBox(KIND_LABELS[kind])
            box.setChecked(True)
            box.setToolTip(' '.join(KINDS[kind]))
            box.toggled.connect(self.relist)
            types.addWidget(box)
        types.addStretch()
        layout.addLayout(types)

        options = W.QHBoxLayout()
        self.recursive = W.QCheckBox('Subfolders')
        self.recursive.setToolTip('Include files in subfolders')
        self.recursive.toggled.connect(self.relist)
        self.hide_loaded = W.QCheckBox('Hide loaded')
        self.hide_loaded.toggled.connect(self.filter_list)
        self.search = W.QLineEdit()
        self.search.setPlaceholderText('Filter files')
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.filter_list)
        options.addWidget(self.search, 1)
        options.addWidget(self.recursive)
        options.addWidget(self.hide_loaded)
        layout.addLayout(options)

        self.list = FileList()
        self.list.setSelectionMode(W.QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list.setIconSize(C.QSize(12, 12))
        self.list.setDragEnabled(True)
        self.list.setDragDropMode(W.QAbstractItemView.DragDropMode.DragOnly)
        self.list.itemSelectionChanged.connect(self.selection_changed)
        self.list.itemDoubleClicked.connect(self.activate)
        layout.addWidget(self.list, 3)
        self.summary = W.QLabel()
        layout.addWidget(self.summary)
        self.preview = W.QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setLineWrapMode(W.QPlainTextEdit.LineWrapMode.NoWrap)
        self.preview.setPlaceholderText('Select a file to see its header')
        self.preview.setMaximumHeight(150)
        self.preview.setFont(G.QFontDatabase.systemFont(G.QFontDatabase.SystemFont.FixedFont))
        layout.addWidget(self.preview, 1)

        load_box = W.QGroupBox('Load options')
        form = W.QFormLayout(load_box)
        name_row = W.QHBoxLayout()
        self.name_pattern = W.QLineEdit()
        self.name_pattern.setPlaceholderText('{stem}  (file name)')
        self.name_pattern.setToolTip('Dataset names, e.g. Scan_{n} or BG_{num}.\n'
                                     '{stem}: file name · {n}: running number · {num}: last number in the '
                                     'file name · {folder}: parent folder.\nTitle fields such as power100 '
                                     'come from the name, so keep them when you rename.')
        self.start_number = W.QSpinBox()
        self.start_number.setRange(0, 999999)
        self.start_number.setPrefix('from ')
        self.start_number.setToolTip('First {n}; advances after every load')
        name_row.addWidget(self.name_pattern, 1)
        name_row.addWidget(self.start_number)
        form.addRow('Name', name_row)
        self.grouping = W.QComboBox()
        for key, label in GROUPING:
            self.grouping.addItem(label, key)
        form.addRow('Group', self.grouping)
        self.sort_x = W.QCheckBox('Sort rows by X')
        self.sort_x.setToolTip('Order text data by its X channel, e.g. sweeps recorded high to low. '
                               'The dataset comments record the sort.')
        self.preview_first = W.QCheckBox('Choose columns on first file')
        self.preview_first.setToolTip('Preview the first file and apply its columns or channels to the rest')
        checks = W.QHBoxLayout()
        checks.addWidget(self.sort_x)
        checks.addWidget(self.preview_first)
        checks.addStretch()
        form.addRow(checks)
        self.auto_load = W.QCheckBox('Auto-load new files')
        self.auto_load.setToolTip('Watch the folder and load files as the instrument finishes writing them')
        self.auto_load.toggled.connect(self.auto_load_toggled)
        form.addRow(self.auto_load)
        layout.addWidget(load_box)

        buttons = W.QHBoxLayout()
        self.load_button = W.QPushButton('Load selected')
        self.load_button.setDefault(True)
        self.load_button.clicked.connect(self.load_selected)
        self.convert_button = W.QPushButton('New project from folder…')
        self.convert_button.setToolTip('Convert every supported file in this folder and its subfolders '
                                       'into a new HDF5 project')
        self.convert_button.clicked.connect(lambda: self.folder and self.convert_requested.emit(self.folder))
        buttons.addWidget(self.load_button)
        buttons.addStretch()
        buttons.addWidget(self.convert_button)
        layout.addLayout(buttons)

        self.watcher = C.QFileSystemWatcher(self)
        self.watcher.directoryChanged.connect(lambda path: self.refresh_timer.start())
        self.refresh_timer = C.QTimer(self, singleShot=True, interval=SETTLE_MS)
        self.refresh_timer.timeout.connect(self.refresh)
        self.selection_changed()

    def browse(self):
        folder = W.QFileDialog.getExistingDirectory(self, 'Choose data folder', self.folder or '')
        if folder:
            self.set_folder(folder)

    def set_folder(self, folder):
        folder = str(Path(folder).expanduser()) if folder else None
        if folder == self.folder:
            return
        self.folder = folder
        self.folder_edit.setText(folder or '')
        self.sizes, self.new, self.pending, self.scanned = {}, set(), set(), False
        if self.watcher.directories():
            self.watcher.removePaths(self.watcher.directories())
        if folder and Path(folder).is_dir():
            self.watcher.addPath(folder)
        self.refresh()
        self.folder_changed.emit(folder or '')

    def kinds(self):
        return [kind for kind, box in self.kind_boxes.items() if box.isChecked()]

    def relist(self, *args):
        """A filter change shows other files; they are not new arrivals."""
        self.scanned = False
        self.refresh()

    def refresh(self, *args):
        selected = set(self.selected_paths())
        self.list.clear()
        if not self.folder:
            self.summary.setText('Choose a data folder, or drop files and folders on the window.')
            return
        try:
            paths = scan_folder(self.folder, self.kinds(), self.recursive.isChecked())
        except (ValueError, OSError) as error:
            self.summary.setText(str(error))
            return
        sizes = {}
        for path in paths:
            key = resolved(path)
            try:
                sizes[key] = path.stat().st_size
            except OSError:
                continue
            if self.scanned and key not in self.sizes:
                self.new.add(key)
                if not is_project(key):
                    self.pending.add(key)
            item = W.QListWidgetItem(path.relative_to(self.folder).as_posix(), self.list)
            item.setData(PATH_ROLE, key)
            item.setToolTip(key)
            item.setSelected(key in selected)
        settled = [p for p in sorted(self.pending) if p in sizes and sizes[p] == self.sizes.get(p)]
        self.pending = {p for p in self.pending if p in sizes} - set(settled)
        self.sizes, self.scanned = sizes, True
        self.mark_items()
        if self.pending:
            self.refresh_timer.start()
        if settled and self.auto_load.isChecked():
            fresh = [p for p in settled if p not in self.loaded]
            if fresh:
                self.load_requested.emit(fresh, self.options(auto=True))

    def update_loaded(self, *args):
        self.set_loaded(self.loaded_sources())

    def set_loaded(self, sources):
        self.loaded = set(sources)
        self.mark_items()

    def mark_items(self):
        font = self.list.font()
        bold = G.QFont(font)
        bold.setBold(True)
        muted = self.palette().color(G.QPalette.ColorRole.PlaceholderText)
        check = self.style().standardIcon(W.QStyle.StandardPixmap.SP_DialogApplyButton)
        blank = G.QPixmap(self.list.iconSize())
        blank.fill(C.Qt.GlobalColor.transparent)
        blank = G.QIcon(blank)  # keeps every name aligned whether or not it is marked
        for row in range(self.list.count()):
            item = self.list.item(row)
            path = item.data(PATH_ROLE)
            loaded = path in self.loaded
            item.setFont(bold if path in self.new and not loaded else font)
            item.setForeground(muted if loaded else self.palette().color(G.QPalette.ColorRole.Text))
            item.setIcon(check if loaded else blank)
            item.setToolTip(path + ('\nAlready in the project' if loaded else
                                    '\nNew since the folder was opened' if path in self.new else ''))
        self.filter_list()

    def filter_list(self, *args):
        words = self.search.text().lower().split()
        hide_loaded = self.hide_loaded.isChecked()
        shown = loaded = new = 0
        for row in range(self.list.count()):
            item = self.list.item(row)
            path = item.data(PATH_ROLE)
            hidden = (any(word not in item.text().lower() for word in words)
                      or (hide_loaded and path in self.loaded))
            item.setHidden(hidden)
            shown += not hidden
            loaded += path in self.loaded
            new += path in self.new and path not in self.loaded
        parts = [f'{shown} of {self.list.count()} files' if shown != self.list.count() else f'{shown} files',
                 f'{loaded} loaded']
        if new:
            parts.append(f'{new} new')
        if self.auto_load.isChecked():
            parts.append('watching for new files')
        self.summary.setText(' · '.join(parts))

    def selected_paths(self):
        return [item.data(PATH_ROLE) for item in self.list.selectedItems() if not item.isHidden()]

    def selection_changed(self):
        paths = self.selected_paths()
        self.load_button.setEnabled(bool(paths))
        self.load_button.setText('Open project' if len(paths) == 1 and is_project(paths[0])
                                 else f'Load {len(paths)} files' if len(paths) > 1 else 'Load selected')
        self.convert_button.setEnabled(bool(self.folder))
        current = self.list.currentItem()
        path = current.data(PATH_ROLE) if current and current.isSelected() else (paths[0] if paths else None)
        self.preview.setPlainText(file_summary(path) if path else '')

    def options(self, auto=False):
        grouping = self.grouping.currentData()
        return dict(name_pattern=self.name_pattern.text(), start=self.start_number.value(),
                    # A watcher load never stops to ask; it reuses the last destination.
                    grouping='last' if auto and grouping == 'ask' else grouping,
                    sort_x=self.sort_x.isChecked(), preview=self.preview_first.isChecked() and not auto,
                    folder=self.folder)

    def load_selected(self):
        paths = self.selected_paths()
        projects = [p for p in paths if is_project(p)]
        if len(paths) == 1 and projects:
            self.open_project_requested.emit(paths[0])
        elif projects:
            W.QMessageBox.information(self, 'Rogi', 'Select data files to load, or one project to open.')
        elif paths:
            self.load_requested.emit(paths, self.options())

    def activate(self, item):
        path = item.data(PATH_ROLE)
        if is_project(path):
            self.open_project_requested.emit(path)
        elif file_kind(path):
            self.load_requested.emit([path], self.options())

    def advance_number(self, count):
        """{n} continues after the files just loaded, as Igor's Start num does."""
        if '{n}' in self.name_pattern.text():
            self.start_number.setValue(self.start_number.value() + count)

    def auto_load_toggled(self, on):
        if on and self.folder:
            # Files already listed count as seen; only later arrivals load.
            self.refresh()
        self.filter_list()
