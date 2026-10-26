"""Format Legend dialog: entries, position and appearance of the line-plot legend.

Entry text, order and visibility belong to datasets, so they are the same in
every panel; the position and appearance are shared by all panels too, except
a legend dragged in one panel. Built on the Format Axis dialog's preview: OK is
one undo step and Cancel restores the legend.
"""
from copy import deepcopy
from PySide6 import QtCore as C, QtWidgets as W
from .axis_format import ColorChoice, PreviewDialog, row, size_box
from .operations import dialog_parent
from .plotting import LEGENDS, PLOT_STYLE, validate_plot_style

POSITIONS = LEGENDS[:-1]  # 'hidden' is the Show legend checkbox
SHOW, NAME, TEXT = range(3)


def legend_style(window):
    return {key: deepcopy(value) for key, value in window.plot_style.items() if key.startswith('legend_')}


def capture(window):
    return dict(position=window.legend_position.currentText(),
                anchors=[deepcopy(panel.get('legend_anchor')) for panel in window.panels],
                labels=dict(window.legend_labels), order=list(window.legend_order),
                hidden=list(window.legend_hidden), style=legend_style(window))


def apply_state(window, state):
    # Set quietly: the control's own handler would also clear dragged positions.
    with C.QSignalBlocker(window.legend_position):
        window.legend_position.setCurrentText(state['position'])
    for panel, anchor in zip(window.panels, state['anchors']):
        if anchor is None:
            panel.pop('legend_anchor', None)
        else:
            panel['legend_anchor'] = list(anchor)
    window.legend_labels = dict(state['labels'])
    window.legend_order = list(state['order'])
    window.legend_hidden = list(state['hidden'])
    window.plot_style.update(deepcopy(state['style']))
    window.redraw()


def panel_curves(window, index):
    """Visible datasets of a panel, in legend order."""
    rank = {dataset_id: n for n, dataset_id in enumerate(window.legend_order)}
    curves = [d for d in window.panel_datasets(window.panels[index]) if d.visible]
    return sorted(curves, key=lambda d: rank.get(d.id, len(rank)))


def spin(low, high, value, step, decimals=2, suffix=''):
    box = W.QDoubleSpinBox()
    box.setRange(low, high)
    box.setDecimals(decimals)
    box.setSingleStep(step)
    box.setValue(value)
    box.setSuffix(suffix)
    return box


class FormatLegendDialog(PreviewDialog):
    undo_label = "Format legend"

    def __init__(self, window, index, dataset_id=None, parent=None):
        super().__init__(parent)
        self.window, self.index = window, index
        several = len(window.panels) > 1
        self.setWindowTitle("Format legend" + (f" — panel {index + 1}" if several else ''))
        self.before = capture(window)
        self.anchors = list(self.before['anchors'])
        style = self.before['style']
        layout = W.QVBoxLayout(self)
        tabs = W.QTabWidget()
        layout.addWidget(tabs)

        page = W.QWidget()
        page_layout = W.QVBoxLayout(page)
        self.curves = panel_curves(window, index)
        self.table = W.QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Show", "Dataset", "Legend text"])
        self.table.setSelectionBehavior(W.QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(W.QAbstractItemView.SelectionMode.SingleSelection)
        self.table.verticalHeader().hide()
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(SHOW, W.QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(NAME, W.QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(TEXT, W.QHeaderView.ResizeMode.Stretch)
        hidden = set(self.before['hidden'])
        for d in self.curves:
            self.add_row(d, d.id not in hidden, self.before['labels'].get(d.id, d.name))
        page_layout.addWidget(self.table)
        up, down = W.QPushButton("Move up"), W.QPushButton("Move down")
        up.clicked.connect(lambda: self.move(-1))
        down.clicked.connect(lambda: self.move(1))
        page_layout.addWidget(row(up, down))
        self.fit_entries = W.QCheckBox("Show fit entries")
        self.fit_entries.setChecked(style['legend_fit_entries'])
        self.sd_entries = W.QCheckBox("Show ±SD band entries of averaged datasets")
        self.sd_entries.setChecked(style['legend_sd_entries'])
        self.residuals = W.QCheckBox("Show a legend in the residual panel")
        self.residuals.setChecked(style['legend_residuals'])
        for box in (self.fit_entries, self.sd_entries, self.residuals):
            page_layout.addWidget(box)
        note = W.QLabel("Clear a text, or type the dataset name, to use the dataset name. Text, order and Show "
                        "apply in every panel; fit and SD entries follow their curve."
                        + ("" if self.curves else " This panel has no visible curves."))
        note.setWordWrap(True)
        page_layout.addWidget(note)
        tabs.addTab(page, "Entries")

        page = W.QWidget()
        form = W.QFormLayout(page)
        self.show_legend = W.QCheckBox("Show legend")
        self.show_legend.setChecked(self.before['position'] != 'hidden')
        form.addRow(self.show_legend)
        self.position = W.QComboBox()
        self.position.addItems(POSITIONS)
        self.position.setCurrentText(self.before['position'] if self.before['position'] != 'hidden' else 'best')
        self.position.currentIndexChanged.connect(self.position_chosen)
        form.addRow("Position", self.position)
        self.dragged = W.QLabel()
        self.dragged.setWordWrap(True)
        self.reset_drag = W.QPushButton("Reset dragged position")
        self.reset_drag.clicked.connect(self.reset_anchor)
        form.addRow(self.dragged)
        form.addRow(self.reset_drag)
        note = W.QLabel("Outside positions place the legend beside or above the plot and shrink the plot to make "
                        "room. Drag the legend on the plot to place it anywhere in its panel. The position "
                        "applies to every panel.")
        note.setWordWrap(True)
        form.addRow(note)
        tabs.addTab(page, "Position")

        page = W.QWidget()
        form = W.QFormLayout(page)
        self.title = W.QLineEdit(style['legend_title'])
        self.title.setPlaceholderText("No title")
        form.addRow("Title", self.title)
        self.size = size_box(style['legend_size'])
        form.addRow("Font size", self.size)
        self.color = ColorChoice(style['legend_color'], "Legend text color")
        form.addRow("Text color", self.color)
        self.columns = W.QSpinBox()
        self.columns.setRange(1, 6)
        self.columns.setValue(style['legend_columns'])
        form.addRow("Columns", self.columns)
        self.marker_scale = spin(.25, 4, style['legend_marker_scale'], .25, suffix=" ×")
        form.addRow("Marker size", self.marker_scale)
        self.spacing = spin(0, 3, style['legend_spacing'], .1, suffix=" × font size")
        form.addRow("Entry spacing", self.spacing)
        self.frame = W.QCheckBox("Frame")
        self.frame.setChecked(style['legend_frame'])
        form.addRow(self.frame)
        self.frame_color = ColorChoice(style['legend_frame_color'], "Legend frame color")
        form.addRow("Frame color", self.frame_color)
        self.background = ColorChoice(style['legend_background'], "Legend background color")
        form.addRow("Background", self.background)
        self.opacity = spin(0, 100, style['legend_alpha'] * 100, 10, 0, " %")
        form.addRow("Opacity", self.opacity)
        self.rounded = W.QCheckBox("Rounded corners")
        self.rounded.setChecked(style['legend_rounded'])
        form.addRow(self.rounded)
        defaults = W.QPushButton("Default appearance")
        defaults.clicked.connect(self.default_appearance)
        form.addRow(defaults)
        tabs.addTab(page, "Appearance")

        self.finish_layout(layout)
        self.show_legend.toggled.connect(self.enable_fields)
        self.frame.toggled.connect(self.enable_fields)
        self.enable_fields()
        self.show_anchor()
        self.watch(self.table, self.fit_entries, self.sd_entries, self.residuals, self.show_legend, self.position,
                   self.title, self.size, self.color, self.columns, self.marker_scale, self.spacing, self.frame,
                   self.frame_color, self.background, self.opacity, self.rounded)
        if dataset_id is not None:
            self.edit_entry(dataset_id)

    def add_row(self, d, shown, text):
        row_index = self.table.rowCount()
        self.table.insertRow(row_index)
        show = W.QTableWidgetItem()
        show.setFlags(C.Qt.ItemFlag.ItemIsUserCheckable | C.Qt.ItemFlag.ItemIsEnabled | C.Qt.ItemFlag.ItemIsSelectable)
        show.setCheckState(C.Qt.CheckState.Checked if shown else C.Qt.CheckState.Unchecked)
        show.setData(C.Qt.ItemDataRole.UserRole, d.id)
        name = W.QTableWidgetItem(d.name)
        name.setFlags(name.flags() & ~C.Qt.ItemFlag.ItemIsEditable)
        for column, item in ((SHOW, show), (NAME, name), (TEXT, W.QTableWidgetItem(text))):
            self.table.setItem(row_index, column, item)

    def entries(self):
        """(dataset id, shown, text) for each table row, top first."""
        return [(self.table.item(r, SHOW).data(C.Qt.ItemDataRole.UserRole),
                 self.table.item(r, SHOW).checkState() == C.Qt.CheckState.Checked,
                 self.table.item(r, TEXT).text().strip()) for r in range(self.table.rowCount())]

    def move(self, step):
        current = self.table.currentRow()
        target = current + step
        if current < 0 or not 0 <= target < self.table.rowCount():
            return
        with C.QSignalBlocker(self.table):
            for column in range(self.table.columnCount()):
                upper, lower = self.table.takeItem(current, column), self.table.takeItem(target, column)
                self.table.setItem(target, column, upper)
                self.table.setItem(current, column, lower)
        self.table.selectRow(target)
        self.timer.start()

    def edit_entry(self, dataset_id):
        """Open with the clicked entry's text ready to type over."""
        for r, (entry_id, _, _) in enumerate(self.entries()):
            if entry_id == dataset_id:
                self.table.setCurrentCell(r, TEXT)
                self.table.editItem(self.table.item(r, TEXT))

    def position_chosen(self):
        # A chosen position replaces dragged ones, as the Legend control does.
        self.anchors = [None] * len(self.anchors)
        self.show_anchor()

    def reset_anchor(self):
        self.anchors[self.index] = None
        self.show_anchor()
        self.timer.start()

    def show_anchor(self):
        dragged = self.anchors[self.index] is not None
        self.dragged.setText("The legend in this panel was dragged; it stays where it was dropped."
                             if dragged else "")
        self.dragged.setVisible(dragged)
        self.reset_drag.setEnabled(dragged)

    def enable_fields(self, *args):
        self.position.setEnabled(self.show_legend.isChecked())
        for field in (self.frame_color, self.background, self.opacity, self.rounded):
            field.setEnabled(self.frame.isChecked())

    def default_appearance(self):
        self.title.clear()
        self.size.setCurrentIndex(self.size.findData(PLOT_STYLE['legend_size']))
        self.columns.setValue(PLOT_STYLE['legend_columns'])
        self.marker_scale.setValue(PLOT_STYLE['legend_marker_scale'])
        self.spacing.setValue(PLOT_STYLE['legend_spacing'])
        self.frame.setChecked(PLOT_STYLE['legend_frame'])
        self.opacity.setValue(PLOT_STYLE['legend_alpha'] * 100)
        self.rounded.setChecked(PLOT_STYLE['legend_rounded'])
        for choice, key in ((self.color, 'legend_color'), (self.frame_color, 'legend_frame_color'),
                            (self.background, 'legend_background')):
            choice.set_color(PLOT_STYLE[key])

    def read(self):
        entries = self.entries()
        names = {d.id: d.name for d in self.curves}
        listed = {entry_id for entry_id, _, _ in entries}
        labels = {k: v for k, v in self.before['labels'].items() if k not in listed}
        labels.update({entry_id: text for entry_id, _, text in entries if text and text != names[entry_id]})
        order = self.before['order']
        if [entry_id for entry_id, _, _ in entries] != [d.id for d in self.curves]:
            # Datasets outside this panel keep their place after the ones listed here.
            order = [entry_id for entry_id, _, _ in entries] + [i for i in order if i not in listed]
        hidden = [entry_id for entry_id, shown, _ in entries if not shown]
        hidden += [i for i in self.before['hidden'] if i not in listed]
        style = dict(self.before['style'], legend_title=self.title.text().strip(),
                     legend_size=self.size.currentData(), legend_color=self.color.color,
                     legend_columns=self.columns.value(), legend_marker_scale=self.marker_scale.value(),
                     legend_spacing=self.spacing.value(), legend_frame=self.frame.isChecked(),
                     legend_frame_color=self.frame_color.color, legend_background=self.background.color,
                     legend_alpha=round(self.opacity.value() / 100, 2), legend_rounded=self.rounded.isChecked(),
                     legend_fit_entries=self.fit_entries.isChecked(), legend_sd_entries=self.sd_entries.isChecked(),
                     legend_residuals=self.residuals.isChecked())
        validate_plot_style(style)
        position = self.position.currentText() if self.show_legend.isChecked() else 'hidden'
        return dict(position=position, anchors=list(self.anchors), labels=labels, order=order, hidden=hidden,
                    style=style)

    def apply(self, state):
        apply_state(self.window, state)


def format_legend(window, index, dataset_id=None):
    FormatLegendDialog(window, index, dataset_id, dialog_parent(window)).exec()
