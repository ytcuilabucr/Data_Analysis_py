"""Dataset list, group navigation and filtering, independent of other panels."""
from dataclasses import dataclass, field
from PySide6 import QtCore as C, QtWidgets as W
from .grouping import group_path, path_key, path_label, node_label, field_labels
from .metadata import metadata_search_text, acquisition_timestamp, channel_count


@dataclass
class BrowserState:
    datasets: list = field(default_factory=list)
    loading: bool = False


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



class BrowserPanel(W.QWidget):
    selection_requested = C.Signal(int)
    action_requested = C.Signal(str, object)
    attributes_requested = C.Signal(object, str, object, str)

    def __init__(self, state):
        super().__init__()
        self.state = state
        layout = self._build_filters()
        self._build_actions(layout)

    @property
    def datasets(self):
        return self.state.datasets

    @property
    def loading(self):
        return self.state.loading

    def _build_filters(self):
        self.browser = DatasetBrowser()
        self.browser.setMinimumWidth(480)
        self.browser.setSelectionMode(W.QAbstractItemView.SelectionMode.ExtendedSelection)
        self.browser.setToolTip("Highlight rows to select them; check boxes to show them on the plot.")
        browser_layout = W.QVBoxLayout(self)
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
        return browser_layout

    def _build_actions(self, browser_layout):
        organize = W.QToolButton()
        organize.setText("Organize")
        organize.setPopupMode(W.QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = W.QMenu(organize)
        self.organization_actions = {}
        for label, function in [
                ("Rename…", lambda: self.action_requested.emit('rename_dataset', ())), ("Assign group…", lambda: self.action_requested.emit('assign_group', ())),
                ("Group by metadata…", lambda: self.action_requested.emit('group_by_metadata', ())),
                ("View metadata…", lambda: self.action_requested.emit('view_metadata', ())),
                ("Favorite selected", lambda: self.action_requested.emit('annotate_selected', ('favorite', True,))),
                ("Unfavorite selected", lambda: self.action_requested.emit('annotate_selected', ('favorite', False,))),
                ("Edit tags…", lambda: self.action_requested.emit('edit_tags', ())),
                ("Edit comments…", lambda: self.action_requested.emit('edit_comments', ())),
                ("Ungroup selected", lambda: self.action_requested.emit('set_selected_group', ("",))),
                ("Show selected", lambda: self.action_requested.emit('set_selected_visibility', (True,))),
                ("Hide selected", lambda: self.action_requested.emit('set_selected_visibility', (False,))),
                ("Select all shown", self.select_all_shown),
                ("Clear selection", self.browser.clearSelection),
                ("Remove selected…", lambda: self.action_requested.emit('remove_selected', ()))]:
            action = menu.addAction(label)
            action.triggered.connect(lambda checked=False, fn=function: fn())
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
        self.search.textChanged.connect(self.filter_browser)
        self.group_filter.currentIndexChanged.connect(self.filter_browser)
        self.browser.itemSelectionChanged.connect(self.selection_changed)


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
        self.selection_requested.emit(self.browser.currentRow())


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


    def activate_dataset(self, dataset_id):
        for row in range(self.browser.count()):
            item = self.browser.item(row)
            if item.data(C.Qt.ItemDataRole.UserRole) == dataset_id and not item.isHidden():
                self.browser.setCurrentRow(row, C.QItemSelectionModel.SelectionFlag.ClearAndSelect)
                self.selection_requested.emit(row)
                return


    def visibility(self, item):
        if not self.loading:
            d = self.dataset_for_item(item)
            visible = item.checkState() == C.Qt.CheckState.Checked
            active = self.current()
            target_id = d.id if visible else (active.id if active else None)
            self.attributes_requested.emit([d], 'visible', visible, f"{'Show' if visible else 'Hide'} {d.name}")
            if target_id is not None:
                self.activate_dataset(target_id)


