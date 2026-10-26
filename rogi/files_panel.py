"""Folder file list for bringing data in: browse, filter, preview and load files.

The panel only lists and selects files. It asks the window to load or open them
through its signals, and the window reports which sources are already loaded.
"""
from datetime import datetime
from pathlib import Path
import numpy as np
from PySide6 import QtCore as C, QtWidgets as W, QtGui as G
from .files import (KINDS, KIND_LABELS, scan_folder, file_kind, is_project, resolved, file_preview,
                    natural_key, size_text)

PATH_ROLE = C.Qt.ItemDataRole.UserRole
SORT_ROLE = C.Qt.ItemDataRole.UserRole + 1
NAME, MODIFIED, SIZE = range(3)
GROUPING = (('ask', 'Choose once (suggested from metadata)'),
            ('folders', 'Subfolder names'),
            ('root', 'Project root (ungrouped)'))
GROUPING_SHORT = dict(ask='choose once', folders='subfolder names', root='project root')
# New files are loaded only once their size stops changing between checks.
SETTLE_MS = 1000
THUMBNAIL = 120


class FileItem(W.QTreeWidgetItem):
    """Sorts names naturally (sweep_2 before sweep_10), dates and sizes by value."""

    def __lt__(self, other):
        column = self.treeWidget().sortColumn() if self.treeWidget() else NAME
        return self.data(column, SORT_ROLE) < other.data(column, SORT_ROLE)


class FileList(W.QTreeWidget):
    """Drags carry file URLs, so files can be dropped on the dataset list."""

    def mimeData(self, items):
        mime = C.QMimeData()
        mime.setUrls([C.QUrl.fromLocalFile(item.data(NAME, PATH_ROLE)) for item in items
                      if item.data(NAME, PATH_ROLE)])
        return mime


def thumbnail(image):
    """Grayscale pixmap of a scan channel, contrast from the 1st-99th percentile."""
    finite = image[np.isfinite(image)]
    if not finite.size:
        return None
    low, high = np.percentile(finite, (1, 99))
    scaled = np.clip((image - low) / ((high - low) or 1), 0, 1)
    pixels = np.ascontiguousarray(np.nan_to_num(scaled[::-1]) * 255, dtype=np.uint8)
    height, width = pixels.shape
    picture = G.QImage(pixels.data, width, height, width, G.QImage.Format.Format_Grayscale8).copy()
    return G.QPixmap.fromImage(picture).scaled(THUMBNAIL, THUMBNAIL, C.Qt.AspectRatioMode.KeepAspectRatio,
                                               C.Qt.TransformationMode.SmoothTransformation)


class FilesPanel(W.QWidget):
    load_requested = C.Signal(list, dict)
    open_project_requested = C.Signal(str)
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
        self.watch = W.QPushButton('Watch')
        self.watch.setCheckable(True)
        self.watch.setToolTip('Watch the folder and load new files as the instrument finishes writing them')
        self.watch.toggled.connect(self.watch_toggled)
        row.addWidget(self.folder_edit, 1)
        row.addWidget(browse)
        row.addWidget(self.refresh_button)
        row.addWidget(self.watch)
        layout.addLayout(row)

        options = W.QHBoxLayout()
        self.search = W.QLineEdit()
        self.search.setPlaceholderText('Filter files')
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.filter_list)
        self.types_button = W.QToolButton()
        self.types_button.setPopupMode(W.QToolButton.ToolButtonPopupMode.InstantPopup)
        self.types_button.setToolTip('File types to list')
        types_menu = W.QMenu(self.types_button)
        self.kind_actions = {}
        for kind in KINDS:
            action = self.kind_actions[kind] = types_menu.addAction(f'{KIND_LABELS[kind]}  ({" ".join(KINDS[kind])})')
            action.setCheckable(True)
            action.setChecked(True)
            action.toggled.connect(self.relist)
        self.types_button.setMenu(types_menu)
        self.recursive = W.QCheckBox('Subfolders')
        self.recursive.setToolTip('Include files in subfolders')
        self.recursive.toggled.connect(self.relist)
        self.hide_loaded = W.QCheckBox('Hide loaded')
        self.hide_loaded.toggled.connect(self.filter_list)
        options.addWidget(self.search, 1)
        options.addWidget(self.types_button)
        options.addWidget(self.recursive)
        options.addWidget(self.hide_loaded)
        layout.addLayout(options)

        self.list = FileList()
        self.list.setHeaderLabels(['Name', 'Modified', 'Size'])
        self.list.setSelectionMode(W.QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list.setIconSize(C.QSize(12, 12))
        self.list.setDragEnabled(True)
        self.list.setDragDropMode(W.QAbstractItemView.DragDropMode.DragOnly)
        self.list.setUniformRowHeights(True)
        # Run numbers sit at the end of long instrument names; keep both ends visible.
        self.list.setTextElideMode(C.Qt.TextElideMode.ElideMiddle)
        self.list.setSortingEnabled(True)
        self.list.sortByColumn(NAME, C.Qt.SortOrder.AscendingOrder)
        header = self.list.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(NAME, W.QHeaderView.ResizeMode.Stretch)
        for column in (MODIFIED, SIZE):
            header.setSectionResizeMode(column, W.QHeaderView.ResizeMode.ResizeToContents)
        self.list.itemSelectionChanged.connect(self.selection_changed)
        self.list.itemDoubleClicked.connect(self.activate)
        layout.addWidget(self.list, 3)
        self.summary = W.QLabel()
        layout.addWidget(self.summary)

        # The preview appears only while a file is highlighted.
        self.preview_box = W.QWidget()
        preview_layout = W.QHBoxLayout(self.preview_box)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        self.thumbnail = W.QLabel()
        self.thumbnail.setAlignment(C.Qt.AlignmentFlag.AlignTop)
        self.thumbnail.setToolTip('First scan channel whose values vary')
        self.preview = W.QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setLineWrapMode(W.QPlainTextEdit.LineWrapMode.NoWrap)
        self.preview.setFont(G.QFontDatabase.systemFont(G.QFontDatabase.SystemFont.FixedFont))
        preview_layout.addWidget(self.thumbnail)
        preview_layout.addWidget(self.preview, 1)
        self.preview_box.setMaximumHeight(160)
        layout.addWidget(self.preview_box, 1)

        # Load options stay folded behind a one-line summary; most loads use the defaults.
        toggle_row = W.QHBoxLayout()
        self.options_toggle = W.QToolButton()
        self.options_toggle.setText('Load options')
        self.options_toggle.setCheckable(True)
        self.options_toggle.setToolButtonStyle(C.Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.options_toggle.setArrowType(C.Qt.ArrowType.RightArrow)
        self.options_toggle.setAutoRaise(True)
        self.options_toggle.toggled.connect(self.show_options)
        self.options_summary = W.QLabel()
        self.options_summary.setForegroundRole(G.QPalette.ColorRole.PlaceholderText)
        toggle_row.addWidget(self.options_toggle)
        toggle_row.addWidget(self.options_summary, 1)
        layout.addLayout(toggle_row)

        self.options_box = W.QWidget()
        form = W.QFormLayout(self.options_box)
        form.setContentsMargins(18, 0, 0, 0)
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
        self.options_box.setVisible(False)
        layout.addWidget(self.options_box)
        for signal in (self.name_pattern.textChanged, self.start_number.valueChanged,
                       self.grouping.currentIndexChanged, self.sort_x.toggled, self.preview_first.toggled):
            signal.connect(self.update_options_summary)

        buttons = W.QHBoxLayout()
        buttons.addStretch()
        self.load_button = W.QPushButton('Load selected')
        self.load_button.setDefault(True)
        self.load_button.clicked.connect(self.load_selected)
        buttons.addWidget(self.load_button)
        layout.addLayout(buttons)

        self.watcher = C.QFileSystemWatcher(self)
        self.watcher.directoryChanged.connect(lambda path: self.refresh_timer.start())
        self.refresh_timer = C.QTimer(self, singleShot=True, interval=SETTLE_MS)
        self.refresh_timer.timeout.connect(self.refresh)
        self.update_types_button()
        self.update_options_summary()
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
        self.refresh()
        self.folder_changed.emit(folder or '')

    def kinds(self):
        return [kind for kind, action in self.kind_actions.items() if action.isChecked()]

    def update_types_button(self):
        kinds = self.kinds()
        self.types_button.setText('All types' if len(kinds) == len(KINDS) else
                                  'No types' if not kinds else ', '.join(KIND_LABELS[k] for k in kinds))

    def relist(self, *args):
        """A filter change shows other files; they are not new arrivals."""
        self.update_types_button()
        self.scanned = False
        self.refresh()

    def watch_folders(self, paths):
        """Watch the folder and, with Subfolders, every folder holding listed files."""
        folders = {self.folder} | ({str(Path(p).parent) for p in paths} if self.recursive.isChecked() else set())
        current = set(self.watcher.directories())
        if current - folders:
            self.watcher.removePaths(sorted(current - folders))
        if folders - current:
            self.watcher.addPaths(sorted(folders - current))

    def file_items(self):
        """Every file row, skipping subfolder rows."""
        items = []
        for row in range(self.list.topLevelItemCount()):
            top = self.list.topLevelItem(row)
            children = [top.child(i) for i in range(top.childCount())]
            items += children if top.data(NAME, PATH_ROLE) is None else [top]
        return items

    def refresh(self, *args):
        selected = set(self.selected_paths())
        scroll = self.list.verticalScrollBar().value()
        self.list.clear()
        if not self.folder:
            if self.watcher.directories():
                self.watcher.removePaths(self.watcher.directories())
            self.summary.setText('Choose a data folder, or drop files and folders on the window.')
            return
        try:
            paths = scan_folder(self.folder, self.kinds(), self.recursive.isChecked())
        except (ValueError, OSError) as error:
            self.summary.setText(str(error))
            return
        self.watch_folders(paths)
        sizes, folders = {}, {}
        self.list.setSortingEnabled(False)
        for path in paths:
            key = resolved(path)
            try:
                stat = path.stat()
            except OSError:
                continue
            sizes[key] = stat.st_size
            if self.scanned and key not in self.sizes:
                self.new.add(key)
                if not is_project(key):
                    self.pending.add(key)
            # Files in subfolders sit under one row per subfolder.
            parent = path.parent.relative_to(self.folder).as_posix()
            if parent == '.':
                item = FileItem(self.list)
            else:
                if parent not in folders:
                    folder = folders[parent] = FileItem(self.list)
                    folder.setText(NAME, parent)
                    folder.setIcon(NAME, self.style().standardIcon(W.QStyle.StandardPixmap.SP_DirIcon))
                    folder.setFlags(C.Qt.ItemFlag.ItemIsEnabled)
                    folder.setFirstColumnSpanned(True)
                    for column in (NAME, MODIFIED, SIZE):
                        folder.setData(column, SORT_ROLE, (0, natural_key(parent)))
                item = FileItem(folders[parent])
            item.setText(NAME, path.name)
            item.setText(MODIFIED, datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M'))
            item.setText(SIZE, size_text(stat.st_size))
            item.setTextAlignment(SIZE, C.Qt.AlignmentFlag.AlignRight | C.Qt.AlignmentFlag.AlignVCenter)
            item.setData(NAME, PATH_ROLE, key)
            item.setData(NAME, SORT_ROLE, (1, natural_key(path.name)))
            item.setData(MODIFIED, SORT_ROLE, (1, stat.st_mtime))
            item.setData(SIZE, SORT_ROLE, (1, stat.st_size))
            item.setSelected(key in selected)
        self.list.setSortingEnabled(True)
        self.list.expandAll()
        self.list.verticalScrollBar().setValue(scroll)
        settled = [p for p in sorted(self.pending) if p in sizes and sizes[p] == self.sizes.get(p)]
        self.pending = {p for p in self.pending if p in sizes} - set(settled)
        self.sizes, self.scanned = sizes, True
        self.mark_items()
        if self.pending:
            self.refresh_timer.start()
        if settled and self.watch.isChecked():
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
        text = self.palette().color(G.QPalette.ColorRole.Text)
        check = self.style().standardIcon(W.QStyle.StandardPixmap.SP_DialogApplyButton)
        blank = G.QPixmap(self.list.iconSize())
        blank.fill(C.Qt.GlobalColor.transparent)
        blank = G.QIcon(blank)  # keeps every name aligned whether or not it is marked
        for item in self.file_items():
            path = item.data(NAME, PATH_ROLE)
            loaded = path in self.loaded
            for column in (NAME, MODIFIED, SIZE):
                item.setFont(column, bold if path in self.new and not loaded else font)
                item.setForeground(column, muted if loaded else text)
            item.setIcon(NAME, check if loaded else blank)
            item.setToolTip(NAME, path + ('\nAlready in the project' if loaded else
                                          '\nNew since the folder was opened' if path in self.new else ''))
        self.filter_list()

    def filter_list(self, *args):
        words = self.search.text().lower().split()
        hide_loaded = self.hide_loaded.isChecked()
        items = self.file_items()
        shown = loaded = new = 0
        for item in items:
            path = item.data(NAME, PATH_ROLE)
            name = item.text(NAME).lower()
            parent = item.parent()
            if parent is not None:
                name = f'{parent.text(NAME).lower()}/{name}'
            hidden = (any(word not in name for word in words)
                      or (hide_loaded and path in self.loaded))
            item.setHidden(hidden)
            shown += not hidden
            loaded += path in self.loaded
            new += path in self.new and path not in self.loaded
        for row in range(self.list.topLevelItemCount()):
            top = self.list.topLevelItem(row)
            if top.childCount():
                top.setHidden(all(top.child(i).isHidden() for i in range(top.childCount())))
        parts = [f'{shown} of {len(items)} files' if shown != len(items) else f'{shown} files',
                 f'{loaded} loaded']
        if new:
            parts.append(f'{new} new')
        if self.watch.isChecked():
            parts.append('watching for new files')
        self.summary.setText(' · '.join(parts))

    def selected_paths(self):
        return [item.data(NAME, PATH_ROLE) for item in self.list.selectedItems()
                if item.data(NAME, PATH_ROLE) and not item.isHidden()]

    def selection_changed(self):
        paths = self.selected_paths()
        self.load_button.setEnabled(bool(paths))
        self.load_button.setText('Open project' if len(paths) == 1 and is_project(paths[0])
                                 else f'Load {len(paths)} files' if len(paths) > 1 else 'Load selected')
        current = self.list.currentItem()
        path = current.data(NAME, PATH_ROLE) if current and current.isSelected() else None
        path = path or (paths[0] if paths else None)
        self.preview_box.setVisible(bool(path))
        if not path:
            return
        text, image = file_preview(path)
        self.preview.setPlainText(text)
        pixmap = thumbnail(image) if image is not None else None
        self.thumbnail.setVisible(pixmap is not None)
        if pixmap is not None:
            self.thumbnail.setPixmap(pixmap)

    def show_options(self, shown):
        self.options_toggle.setArrowType(C.Qt.ArrowType.DownArrow if shown else C.Qt.ArrowType.RightArrow)
        self.options_box.setVisible(shown)

    def update_options_summary(self, *args):
        pattern = self.name_pattern.text().strip()
        parts = [f'Names {pattern}' + (f' from {self.start_number.value()}' if '{n}' in pattern else '')
                 if pattern else 'Names from files',
                 f'Group: {GROUPING_SHORT[self.grouping.currentData()]}',
                 'choose columns on first file' if self.preview_first.isChecked() else 'all columns']
        if self.sort_x.isChecked():
            parts.append('sort by X')
        self.options_summary.setText(' · '.join(parts))

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

    def activate(self, item, column=0):
        path = item.data(NAME, PATH_ROLE)
        if not path:
            return
        if is_project(path):
            self.open_project_requested.emit(path)
        elif file_kind(path):
            self.load_requested.emit([path], self.options())

    def advance_number(self, count):
        """{n} continues after the files just loaded, as Igor's Start num does."""
        if '{n}' in self.name_pattern.text():
            self.start_number.setValue(self.start_number.value() + count)

    def watch_toggled(self, on):
        if on and self.folder:
            # Files already listed count as seen; only later arrivals load.
            self.refresh()
        self.filter_list()
