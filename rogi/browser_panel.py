"""Dataset list, group navigation and filtering, independent of other panels."""
from collections import Counter
from dataclasses import dataclass, field
import re
from PySide6 import QtCore as C, QtWidgets as W
from .grouping import group_path, path_key, path_label, node_label, field_labels, grouping_fields
from .metadata import metadata_search_text, acquisition_timestamp, channel_count

FAVORITE = '★'  # Dataset.favorite shows and filters as this built-in tag.
# Group rows keep their path here; dataset rows keep their id under UserRole.
PATH_ROLE = C.Qt.ItemDataRole.UserRole + 1
LABEL_ROLE = C.Qt.ItemDataRole.UserRole + 2
HIDDEN_COLUMNS = (1, 2)  # Favorite and acquisition date: shown from the header menu.


@dataclass
class BrowserState:
    datasets: list = field(default_factory=list)
    loading: bool = False


SEPARATORS = re.compile(r'([\s,;_]+)')


def name_pieces(name):
    """(is_word, text) pieces; punctuation-only pieces such as '-' or '=' count as separators."""
    return [(bool(re.search(r'\w', text)) and not SEPARATORS.fullmatch(text), text)
            for text in SEPARATORS.split(name) if text]


def shared_words(names):
    """Casefolded words present in every name; none for fewer than two names."""
    if len(names) < 2:
        return set()
    return set.intersection(*({text.casefold() for word, text in name_pieces(n) if word} for n in names))


def shared_text(names):
    """The shared words in the order the first name uses them."""
    common = shared_words(names)
    words = [text for word, text in name_pieces(names[0]) if word and text.casefold() in common] if common else []
    return ' '.join(dict.fromkeys(words))


def short_names(names):
    """Display names without the words every name shares.

    A name stays whole when shortening would leave it empty or indistinguishable
    from another; the stored names never change.
    """
    common = shared_words(names)
    if not common:
        return list(names)
    short = []
    for name in names:
        out, between, dropped = '', '', False
        for word, text in name_pieces(name):
            if not word:
                between += text
            elif text.casefold() in common:
                dropped = True
            else:
                # Untouched spans keep their punctuation; across a gap one separator is enough.
                first = SEPARATORS.search(between)
                gap = between if not dropped else first[0] if first else ' '
                out += (gap if out else '') + text
                between, dropped = '', False
        short.append(out)
    counts = Counter(s.casefold() for s in short)
    return [s if s and counts[s.casefold()] == 1 else name for s, name in zip(short, names)]


def sort_value(item, column):
    text = item.text(column)
    if column == 3:
        return int(text) if text.isdigit() else -1
    return text.casefold()


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
        return sort_value(self, column) < sort_value(other, column)


class GroupItem(W.QTreeWidgetItem):
    """A group row in tree view: neither selectable nor plotted."""
    def __init__(self, path):
        super().__init__()
        self.setFlags(C.Qt.ItemFlag.ItemIsEnabled)
        self.setData(0, PATH_ROLE, list(path))
        font = self.font(0)
        font.setBold(True)
        self.setFont(0, font)

    def __lt__(self, other):
        column = self.treeWidget().sortColumn()
        return sort_value(self, column) < sort_value(other, column)


def is_group(item):
    return item.data(0, PATH_ROLE) is not None


class DatasetBrowser(W.QTreeWidget):
    """Dataset rows, optionally inside group rows.

    Row numbers (count, item, currentRow) address dataset rows only, in display
    order, so callers need not know whether group rows are shown.
    """
    currentRowChanged = C.Signal(int)

    def __init__(self):
        super().__init__()
        self.setRootIsDecorated(False)
        self.setSelectionBehavior(W.QAbstractItemView.SelectionBehavior.SelectRows)
        self.setHeaderLabels(['Dataset / plot', 'Favorite', 'Acquisition date', 'Channels', 'Tags', 'Comments'])
        for column, width in enumerate((220, 65, 165, 75, 140, 220)):
            self.setColumnWidth(column, width)
        for column in HIDDEN_COLUMNS:
            self.setColumnHidden(column, True)
        self.header().setSectionsClickable(True)
        self.header().sectionClicked.connect(self.sort_column)
        self.currentItemChanged.connect(lambda *_: self.currentRowChanged.emit(self.currentRow()))
        self.checkbox_id = None
        self.sort_order = C.Qt.SortOrder.AscendingOrder
        self.sorted_column = None
        self._leaves = None
        model = self.model()
        for signal in (model.rowsInserted, model.rowsRemoved, model.rowsMoved,
                       model.layoutChanged, model.modelReset):
            signal.connect(self.forget_rows)

    def forget_rows(self, *args):
        self._leaves = None

    def leaves(self):
        if self._leaves is None:
            leaves = []
            def walk(parent):
                for index in range(parent.childCount()):
                    child = parent.child(index)
                    if is_group(child):
                        walk(child)
                    else:
                        leaves.append(child)
            walk(self.invisibleRootItem())
            self._leaves = (leaves, {item.data(0, C.Qt.ItemDataRole.UserRole): row
                                     for row, item in enumerate(leaves)})
        return self._leaves

    def groups(self):
        found = []
        def walk(parent):
            for index in range(parent.childCount()):
                child = parent.child(index)
                if is_group(child):
                    found.append(child)
                    walk(child)
        walk(self.invisibleRootItem())
        return found

    def sort_column(self, column):
        self.sort_order = (C.Qt.SortOrder.DescendingOrder
                           if self.sorted_column == column and self.sort_order == C.Qt.SortOrder.AscendingOrder
                           else C.Qt.SortOrder.AscendingOrder)
        self.sorted_column = column
        self.sortItems(column, self.sort_order)
        self.header().setSortIndicatorShown(True)
        self.header().setSortIndicator(column, self.sort_order)

    def count(self):
        return len(self.leaves()[0])

    def item(self, row):
        leaves = self.leaves()[0]
        return leaves[row] if 0 <= row < len(leaves) else None

    def currentRow(self):
        item = self.currentItem()
        if item is None or is_group(item):
            return -1
        return self.leaves()[1].get(item.data(0, C.Qt.ItemDataRole.UserRole), -1)

    def setCurrentRow(self, row, flags=C.QItemSelectionModel.SelectionFlag.ClearAndSelect):
        self.setCurrentItem(self.item(row), flags)

    def setCurrentItem(self, item, flags=C.QItemSelectionModel.SelectionFlag.ClearAndSelect):
        super().setCurrentItem(item, 0, flags | C.QItemSelectionModel.SelectionFlag.Rows)

    def checkbox_at(self, position):
        item = self.itemAt(position)
        if (item is None or self.columnAt(position.x()) != 0
                or not item.flags() & C.Qt.ItemFlag.ItemIsUserCheckable):
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
    filter_changed = C.Signal()

    def __init__(self, state):
        super().__init__()
        self.state = state
        self.tag_choices = set()
        self.collapsed = set()
        self.column_choices = {}
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
        self.browser.setMinimumWidth(300)
        self.browser.setSelectionMode(W.QAbstractItemView.SelectionMode.ExtendedSelection)
        self.browser.setToolTip("Highlight rows to select them; check boxes to show them on the plot.")
        self.browser.setExpandsOnDoubleClick(False)  # A single click on a group row toggles it.
        self.browser.itemClicked.connect(self.toggle_group)
        self.browser.itemExpanded.connect(lambda item: self.collapsed.discard(self.group_key(item)))
        self.browser.itemCollapsed.connect(lambda item: self.collapsed.add(self.group_key(item)))
        header = self.browser.header()
        header.setContextMenuPolicy(C.Qt.ContextMenuPolicy.CustomContextMenu)
        header.customContextMenuRequested.connect(self.show_column_menu)
        browser_layout = W.QVBoxLayout(self)
        self.search = W.QLineEdit()
        self.search.setPlaceholderText("Search datasets / metadata, field = value, or tag:name…")
        self.search.setAccessibleName("Search datasets")
        self.group_filter = W.QComboBox()
        self.group_filter.setAccessibleName("Filter dataset group")
        self.group_filter.addItem("All groups", None)
        self.group_filter.addItem("Ungrouped", "")
        # Computed from Dataset.raw, never stored: regrouping cannot mix raw and derived data.
        self.kind_filter = W.QComboBox()
        self.kind_filter.setAccessibleName("Filter raw or derived data")
        self.kind_filter.setToolTip("Raw data are imported files (read-only). Derived data are editable copies "
                                    "and analysis results.")
        for label, kind in [("Raw and derived", None), ("Raw data only", "raw"), ("Derived only", "derived")]:
            self.kind_filter.addItem(label, kind)
        self.tag_button = W.QToolButton()
        self.tag_button.setText("Tags")
        self.tag_button.setAccessibleName("Filter by tag")
        self.tag_button.setToolTip("Show datasets carrying any of the ticked tags. ★ marks favorites.")
        self.tag_button.setPopupMode(W.QToolButton.ToolButtonPopupMode.InstantPopup)
        self.tag_menu = W.QMenu(self.tag_button)
        self.tag_menu.aboutToShow.connect(self.fill_tag_menu)
        self.tag_button.setMenu(self.tag_menu)
        self.tree_toggle = W.QToolButton()
        self.tree_toggle.setText("Tree")
        self.tree_toggle.setCheckable(True)
        self.tree_toggle.setChecked(True)
        self.tree_toggle.setToolTip("Show datasets inside their groups; off lists every dataset in one sortable list.")
        self.tree_toggle.toggled.connect(lambda *_: self.update_groups())
        self.shared_label = W.QLabel()
        self.shared_label.setWordWrap(True)
        self.shared_label.setEnabled(False)  # Greyed: context for the shortened names below.
        self.shared_label.setVisible(False)
        return browser_layout

    def _build_actions(self, browser_layout):
        organize = W.QToolButton()
        organize.setText("Organize")
        organize.setPopupMode(W.QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = W.QMenu(organize)
        self.organization_actions = {}
        for label, function in [
                ("Rename…", lambda: self.action_requested.emit('rename_dataset', ())), ("Assign group…", lambda: self.action_requested.emit('assign_group', ())),
                ("Group by metadata or title…", lambda: self.action_requested.emit('group_by_metadata', ())),
                ("View metadata…", lambda: self.action_requested.emit('view_metadata', ())),
                ("Toggle favorite ★", self.toggle_favorite),
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
        # Only search stays open; the rarer filters fold away behind a toggle.
        self.filters_toggle = W.QToolButton()
        self.filters_toggle.setText("Filters")
        self.filters_toggle.setCheckable(True)
        self.filters_toggle.setToolButtonStyle(C.Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.filters_toggle.setArrowType(C.Qt.ArrowType.RightArrow)
        self.filters_toggle.setAutoRaise(True)
        self.filters_box = W.QWidget()
        filters_layout = W.QVBoxLayout(self.filters_box)
        filters_layout.setContentsMargins(0, 0, 0, 0)
        for widget in (self.group_filter, self.kind_filter):
            filters_layout.addWidget(widget)
        self.filters_box.setVisible(False)
        self.filters_toggle.toggled.connect(self.filters_box.setVisible)
        self.filters_toggle.toggled.connect(lambda shown: self.filters_toggle.setArrowType(
            C.Qt.ArrowType.DownArrow if shown else C.Qt.ArrowType.RightArrow))
        row = W.QHBoxLayout()
        for widget in (organize, self.tag_button):
            row.addWidget(widget)
        row.addStretch()
        row.addWidget(self.tree_toggle)
        for widget in (self.search, self.filters_toggle, self.filters_box):
            browser_layout.addWidget(widget)
        browser_layout.addLayout(row)
        for widget in (self.shared_label, self.browser):
            browser_layout.addWidget(widget)
        self.selection_info = W.QLabel("0 selected")
        browser_layout.addWidget(self.selection_info)
        self.search.textChanged.connect(self.filter_browser)
        self.group_filter.currentIndexChanged.connect(self.filter_browser)
        self.kind_filter.currentIndexChanged.connect(self.filter_browser)
        self.browser.itemSelectionChanged.connect(self.selection_changed)


    def current(self):
        item = self.browser.currentItem()
        if item is None or item.isHidden() or not item.isSelected():
            return None
        return self.dataset_for_item(item)


    def dataset_for_item(self, item):
        dataset_id = item.data(C.Qt.ItemDataRole.UserRole)
        return next((d for d in self.datasets if d.id == dataset_id), None)


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


    def toggle_favorite(self):
        selected = self.selected_datasets()
        favorite = not all(d.favorite for d in selected)
        self.action_requested.emit('annotate_selected', ('favorite', favorite))


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
        self.update_tag_menu()
        dated = False
        # Adding/removing a field can introduce or remove a short-name collision.
        with C.QSignalBlocker(self.browser):
            for row in range(self.browser.count()):
                item = self.browser.item(row)
                dated = self.update_browser_item(item, self.dataset_for_item(item)) or dated
        if 2 not in self.column_choices:
            self.browser.setColumnHidden(2, not dated)
        self.arrange()


    def group_key(self, item):
        return path_key(item.data(0, PATH_ROLE) or [])


    def toggle_group(self, item, column):
        if is_group(item):
            item.setExpanded(not item.isExpanded())


    def arrange(self):
        """Place dataset rows under group rows (tree view) or at the top level, then label them."""
        browser = self.browser
        tree = self.tree_toggle.isChecked()
        browser.setRootIsDecorated(tree)
        leaves = browser.leaves()[0]
        by_id = {d.id: d for d in self.datasets}
        def target(item):
            d = by_id.get(item.data(C.Qt.ItemDataRole.UserRole))
            return path_key(group_path(d)) if tree and d is not None else ()
        wanted = {key[:depth] for key in map(target, leaves) for depth in range(1, len(key) + 1)}
        placed = all((self.group_key(item.parent()) if item.parent() else ()) == target(item) for item in leaves)
        if not placed or wanted != {self.group_key(g) for g in browser.groups()}:
            self.rebuild(leaves, by_id, tree)
        self.relabel(by_id, tree)


    def rebuild(self, leaves, by_id, tree):
        browser = self.browser
        selected = {item.data(C.Qt.ItemDataRole.UserRole) for item in browser.selectedItems()}
        current = browser.currentItem()
        current_id = current.data(0, C.Qt.ItemDataRole.UserRole) if current is not None else None
        order = {d.id: index for index, d in enumerate(self.datasets)}
        leaves = sorted(leaves, key=lambda item: order.get(item.data(C.Qt.ItemDataRole.UserRole), len(order)))
        with C.QSignalBlocker(browser):
            for item in leaves:
                parent = item.parent()
                (browser.invisibleRootItem() if parent is None else parent).removeChild(item)
            browser.clear()  # Only empty group rows remain.
            root, nodes = browser.invisibleRootItem(), {}
            for item in leaves:
                parent = root
                d = by_id.get(item.data(C.Qt.ItemDataRole.UserRole))
                path = group_path(d) if tree and d is not None else []
                for depth in range(1, len(path) + 1):
                    key = path_key(path[:depth])
                    if key not in nodes:
                        nodes[key] = GroupItem(path[:depth])
                        parent.addChild(nodes[key])
                    parent = nodes[key]
                parent.addChild(item)
            for key, node in nodes.items():
                node.setExpanded(key not in self.collapsed)
            for item in leaves:
                item.setSelected(item.data(C.Qt.ItemDataRole.UserRole) in selected)
                if item.data(C.Qt.ItemDataRole.UserRole) == current_id:
                    browser.setCurrentItem(item, C.QItemSelectionModel.SelectionFlag.NoUpdate)
        if browser.sorted_column is not None:
            browser.sortItems(browser.sorted_column, browser.sort_order)


    def relabel(self, by_id, tree):
        """Siblings drop the words they all share; tooltips keep the full names."""
        labels = field_labels(node['field'] for d in self.datasets for node in d.group_path
                              if node['field'] is not None)
        def label_children(parent):
            rows = [parent.child(index) for index in range(parent.childCount())]
            groups = [row for row in rows if is_group(row)]
            # Free-text groups (folders, titles) shorten like names; "field = value" labels
            # stay whole so units and field names are not dropped.
            nodes = [row.data(0, PATH_ROLE)[-1] for row in groups]
            free = short_names([node['value'] or '' for node in nodes if node['field'] is None])
            for row, node in zip(groups, nodes):
                row.setData(0, LABEL_ROLE, (free.pop(0) or node_label(node)) if node['field'] is None else node_label(node, labels))
                row.setToolTip(0, path_label(row.data(0, PATH_ROLE)))
                label_children(row)
            datasets = [(row, by_id.get(row.data(C.Qt.ItemDataRole.UserRole))) for row in rows if not is_group(row)]
            datasets = [(row, d) for row, d in datasets if d is not None]
            names = [d.name for _, d in datasets]
            for (row, d), short in zip(datasets, short_names(names)):
                suffix = '' if tree else self.display_group_path(group_path(d))
                row.setText(0, short + ("" if d.raw else " [derived]") + (f" — {suffix}" if suffix else ""))
            if is_group(parent) and names:
                shared = shared_text(names)
                parent.setToolTip(0, path_label(parent.data(0, PATH_ROLE))
                                  + (f"\nShared by its datasets: {shared}" if shared else ""))
            return names
        with C.QSignalBlocker(self.browser):
            names = label_children(self.browser.invisibleRootItem())
        shared = '' if tree else shared_text(names) if names else ''
        self.shared_label.setText(f"All share: {shared}")
        self.shared_label.setVisible(bool(shared))
        self.update_group_rows()


    def update_group_rows(self, expand=False):
        """Group rows show how many of their datasets pass the filters and hide when none do."""
        def visit(item):
            shown = 0
            for index in range(item.childCount()):
                child = item.child(index)
                shown += visit(child) if is_group(child) else not child.isHidden()
            if is_group(item):
                item.setText(0, f"{item.data(0, LABEL_ROLE)} ({shown})")
                item.setHidden(not shown)
                item.setExpanded(bool(expand and shown) or self.group_key(item) not in self.collapsed)
            return shown
        with C.QSignalBlocker(self.browser):
            visit(self.browser.invisibleRootItem())


    def tag_counts(self):
        counts = Counter(tag.casefold() for d in self.datasets for tag in dict.fromkeys(d.tags))
        favorites = sum(d.favorite for d in self.datasets)
        return ({FAVORITE: favorites} if favorites else {}) | dict(counts)


    def update_tag_menu(self):
        """Forget ticked tags no dataset carries any more, so no filter hides behind a missing entry."""
        stale = self.tag_choices - set(self.tag_counts())
        self.tag_choices -= stale
        self.tag_button.setText(f"Tags ({len(self.tag_choices)})" if self.tag_choices else "Tags")
        if stale:
            self.filter_browser()


    def fill_tag_menu(self):
        # Built on opening, so no action is deleted while it emits.
        self.tag_menu.clear()
        names = {}
        for d in self.datasets:
            for tag in d.tags:
                names.setdefault(tag.casefold(), tag)
        counts = self.tag_counts()
        if not counts:
            self.tag_menu.addAction("No tags yet: Organize → Edit tags…").setEnabled(False)
            return
        for key in sorted(counts, key=lambda key: (key != FAVORITE, key)):
            label = f"{FAVORITE} Favorites" if key == FAVORITE else names[key]
            action = self.tag_menu.addAction(f"{label} ({counts[key]})")
            action.setCheckable(True)
            action.setChecked(key in self.tag_choices)
            action.toggled.connect(lambda checked, key=key: self.choose_tag(key, checked))
        self.tag_menu.addSeparator()
        clear = self.tag_menu.addAction("Show all tags")
        clear.setEnabled(bool(self.tag_choices))
        clear.triggered.connect(self.clear_tags)


    def choose_tag(self, key, checked):
        (self.tag_choices.add if checked else self.tag_choices.discard)(key)
        self.update_tag_menu()
        self.filter_browser()


    def clear_tags(self):
        self.tag_choices.clear()
        self.update_tag_menu()
        self.filter_browser()


    def show_column_menu(self, position):
        menu = W.QMenu(self)
        for column in range(1, self.browser.columnCount()):
            action = menu.addAction(self.browser.headerItem().text(column))
            action.setCheckable(True)
            action.setChecked(not self.browser.isColumnHidden(column))
            action.toggled.connect(lambda shown, column=column: self.set_column_shown(column, shown))
        menu.exec(self.browser.header().mapToGlobal(position))


    def set_column_shown(self, column, shown):
        self.column_choices[column] = shown
        self.browser.setColumnHidden(column, not shown)


    def filter_browser(self, *args):
        query = self.search.text().strip().casefold()
        group = self.group_filter.currentData()
        hidden_ids = filter_dataset_ids(self.datasets, group, query, self.tag_choices,
                                        kind=self.kind_filter.currentData())
        with C.QSignalBlocker(self.browser):
            for row in range(self.browser.count()):
                item = self.browser.item(row)
                hidden = item.data(C.Qt.ItemDataRole.UserRole) in hidden_ids
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
        # Searching opens the groups holding matches; clearing restores the user's choice.
        self.update_group_rows(expand=bool(query or self.tag_choices))
        active = (group is not None) + (self.kind_filter.currentData() is not None)
        self.filters_toggle.setText(f"Filters ({active})" if active else "Filters")
        self.selection_changed()
        self.filter_changed.emit()

    def reset_filters(self):
        self.search.clear()
        self.tag_choices.clear()
        self.update_tag_menu()
        self.group_filter.setCurrentIndex(0)
        self.kind_filter.setCurrentIndex(0)

    def hidden_ids(self):
        """Ids of datasets the current filter hides from the browser."""
        rows = (self.browser.item(row) for row in range(self.browser.count()))
        return {item.data(C.Qt.ItemDataRole.UserRole) for item in rows if item.isHidden()}


    def update_browser_item(self, item, dataset):
        """Fill the columns; arrange() sets the shortened name. Returns whether the date is known."""
        item.setText(dataset.name + ("" if dataset.raw else " [derived]"))
        timestamp = acquisition_timestamp(dataset)
        item.setText(1, FAVORITE if dataset.favorite else '')
        item.setText(2, timestamp.replace('T', ' ') if timestamp else 'Unknown')
        item.setText(3, str(channel_count(dataset)))
        item.setText(4, ', '.join(([FAVORITE] if dataset.favorite else []) + dataset.tags))
        item.setText(5, dataset.comments)
        item.setToolTip(2, 'Earliest parsed acquisition timestamp from the instrument. Timezone unspecified. '
                          'Filesystem creation/modification times are not acquisition dates. '
                          'Numeric timestamps without a declared epoch are not interpreted.')
        item.setToolTip(3, 'Scan signal channels; for tables, the number of stored columns.')
        item.setToolTip(5, dataset.comments)
        item.setToolTip(f"{dataset.name} [{'raw, read-only' if dataset.raw else 'derived, editable'}]"
                        f"\nGroup: {dataset.group or 'Ungrouped'}"
                        f"\nSource: {dataset.source}\nID: {dataset.id}\nParent: {dataset.parent or 'None'}")
        return timestamp is not None


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




_search_text_cache = {}


def cached_search_text(d):
    """Casefolded metadata text, reused while the metadata objects are unchanged.

    Metadata is replaced, not edited, after import; holding the objects keeps
    their identities valid for the comparison.
    """
    entry = _search_text_cache.get(d.id)
    if entry is None or entry[0] is not d.instrument_metadata or entry[1] is not d.timestamps:
        entry = (d.instrument_metadata, d.timestamps, metadata_search_text(d).casefold())
        _search_text_cache[d.id] = entry
    return entry[2]


FIELD_QUERY = re.compile(r'(.+?)\s*=\s*(.+)')
TAG_QUERY = re.compile(r'(?:^|\s)tag:(\S*)')


def dataset_tags(d):
    """Casefolded tags, with favorites carrying the built-in ★ tag."""
    return [tag.casefold() for tag in d.tags] + [FAVORITE] * d.favorite


def tag_query(query):
    """Split ``tag:name`` terms from the rest of a search; each term must match part of some tag.

    ``tag:favorite`` and ``tag:★`` both mean favorites.
    """
    terms = [FAVORITE if term in ('favorite', 'favourite', 'fav') else term
             for term in TAG_QUERY.findall(query)]
    return [term for term in terms if term], TAG_QUERY.sub(' ', query).strip()


def field_query(datasets, query):
    """A ``key = value`` search names a field when some dataset has a metadata
    or title field containing key; it then matches that value exactly, so
    ``power = 10`` excludes ``power = 100``. Returns a per-dataset predicate or None."""
    match = FIELD_QUERY.fullmatch(query)
    if not match:
        return None
    key, value = match[1].strip(), match[2].strip()
    def matches(d):
        return any(key in k.casefold() and v.strip().casefold() == value
                   for k, v in grouping_fields(d).items())
    named = any(key in k.casefold() for d in datasets for k in grouping_fields(d))
    return matches if named else None


def filter_dataset_ids(datasets, group, query, tags=(), kind=None):
    """Compute visibility without Qt access; empty text filters need no indexing.

    tags are casefolded tag names (★ for favorites) of which a dataset needs any.
    kind is None (all), 'raw' (imported, read-only) or 'derived' (copies and analysis results).
    """
    hidden = set()
    terms, query = tag_query(query)
    if query:
        current = {d.id for d in datasets}
        for stale in _search_text_cache.keys() - current:
            del _search_text_cache[stale]
    exact = field_query(datasets, query) if query else None
    for d in datasets:
        matches = (group_path(d)[:len(group)] == group if isinstance(group, list)
                   else group is None or d.group == group)
        own = dataset_tags(d)
        if (not matches
                or (kind is not None and d.raw != (kind == 'raw'))
                or (exact and not exact(d))
                or (query and not exact
                    and query not in f"{d.name} {d.group} {d.source} {d.tags} {d.comments} "
                                     f"{cached_search_text(d)}".casefold())
                or (tags and not set(own) & set(tags))
                or not all(any(term in tag for tag in own) for term in terms)):
            hidden.add(d.id)
    return hidden
