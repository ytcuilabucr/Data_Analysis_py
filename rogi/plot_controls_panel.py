"""Channel and plot-control widgets; changes are coordinated through signals."""
from PySide6 import QtCore as C, QtWidgets as W
from .plotting import MARKERS, LEGENDS, validate_view


class PlotControlsPanel(C.QObject):
    activate_panel_requested = C.Signal(int)
    add_panel_requested = C.Signal()
    assign_panel_channel_requested = C.Signal()
    unassign_panel_channel_requested = C.Signal()
    remove_panel_requested = C.Signal()
    set_sync_x_requested = C.Signal(bool)
    apply_axes_requested = C.Signal()
    choose_color_requested = C.Signal()
    set_color_requested = C.Signal(str)
    appearance_changed_requested = C.Signal()
    legend_changed_requested = C.Signal()
    presentation_changed_requested = C.Signal()
    add_curve_requested = C.Signal(str)
    remove_curve_requested = C.Signal(str)
    curve_filter_changed_requested = C.Signal()

    def __init__(self, layout):
        super().__init__(layout.parentWidget())
        self._build_curves(layout)
        self._build_channels(layout)
        self._build_plot_controls(layout)

    def _build_curves(self, layout):
        """Curves of the active panel, and other datasets to add, without leaving the plot window."""
        group = W.QGroupBox("Curves — active panel")
        form = W.QVBoxLayout(group)
        self.curves = W.QListWidget()
        self.curves.setAccessibleName('Plotted curves')
        self.curves.setMaximumHeight(110)
        form.addWidget(self.curves)
        remove = W.QPushButton('Remove selected curve')
        remove.clicked.connect(lambda: self.curves.currentItem() and self.remove_curve_requested.emit(
            self.curves.currentItem().data(C.Qt.ItemDataRole.UserRole)))
        form.addWidget(remove)
        self.match_browser_filter = W.QCheckBox('Match file browser filter')
        self.match_browser_filter.setChecked(True)
        self.match_browser_filter.setToolTip('Offer only datasets shown by the file browser filter. '
                                             'Plotted curves are always listed above.')
        self.match_browser_filter.toggled.connect(self.curve_filter_changed_requested)
        form.addWidget(self.match_browser_filter)
        self.curve_choice = W.QComboBox()
        self.curve_choice.setAccessibleName('Dataset to add as a curve')
        self.curve_choice.setToolTip('Add another dataset to this plot as an additional curve. Type to search.')
        self.curve_choice.setMinimumContentsLength(12)
        self.curve_choice.setSizeAdjustPolicy(W.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        # Editable only for searching: typed text never becomes a new entry.
        self.curve_choice.setEditable(True)
        self.curve_choice.setInsertPolicy(W.QComboBox.InsertPolicy.NoInsert)
        self.curve_choice.lineEdit().setPlaceholderText('Search datasets…')
        completer = self.curve_choice.completer()
        completer.setFilterMode(C.Qt.MatchFlag.MatchContains)
        completer.setCaseSensitivity(C.Qt.CaseSensitivity.CaseInsensitive)
        completer.setCompletionMode(W.QCompleter.CompletionMode.PopupCompletion)
        form.addWidget(self.curve_choice)
        self.add_curve = W.QPushButton('Add curve')
        self.add_curve.clicked.connect(lambda: self.chosen_curve() and self.add_curve_requested.emit(
            self.chosen_curve()))
        form.addWidget(self.add_curve)
        layout.addWidget(group)

    def chosen_curve(self):
        """Dataset id whose label matches the combo text, or None while a search is partial."""
        index = self.curve_choice.findText(self.curve_choice.currentText(), C.Qt.MatchFlag.MatchFixedString)
        return self.curve_choice.itemData(index) if index >= 0 else None

    def set_curves(self, plotted, candidates, filtered=0):
        """plotted and candidates are (dataset id, label) pairs; filtered counts candidates the browser filter hides."""
        current = self.curves.currentItem().data(C.Qt.ItemDataRole.UserRole) if self.curves.currentItem() else None
        with C.QSignalBlocker(self.curves):
            self.curves.clear()
            for dataset_id, label in plotted:
                item = W.QListWidgetItem(label, self.curves)
                item.setData(C.Qt.ItemDataRole.UserRole, dataset_id)
                if dataset_id == current:
                    self.curves.setCurrentItem(item)
        chosen = self.curve_choice.currentData()
        with C.QSignalBlocker(self.curve_choice):
            self.curve_choice.clear()
            for dataset_id, label in candidates:
                self.curve_choice.addItem(label, dataset_id)
            index = self.curve_choice.findData(chosen)
            self.curve_choice.setCurrentIndex(max(index, 0))
        self.curve_choice.setEnabled(bool(candidates))
        self.add_curve.setEnabled(bool(candidates))
        self.match_browser_filter.setText('Match file browser filter'
                                          + (f' ({filtered} hidden)' if filtered else ''))

    def _build_channels(self, layout):
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
        self.panel_choice.currentIndexChanged.connect(self.activate_panel_requested.emit)
        channel_form.addRow('Active panel', self.panel_choice)
        add_panel = W.QPushButton('Add panel with selected channels')
        add_panel.clicked.connect(lambda: self.add_panel_requested.emit())
        channel_form.addRow(add_panel)
        assign = W.QPushButton('Assign selected channels to active panel')
        assign.clicked.connect(self.assign_panel_channel_requested.emit)
        channel_form.addRow(assign)
        unassign = W.QPushButton('Remove selected dataset from active panel')
        unassign.clicked.connect(self.unassign_panel_channel_requested.emit)
        channel_form.addRow(unassign)
        remove = W.QPushButton('Remove active panel')
        remove.clicked.connect(self.remove_panel_requested.emit)
        channel_form.addRow(remove)
        self.sync_x_control = W.QCheckBox('Synchronize X limits')
        self.sync_x_control.toggled.connect(self.set_sync_x_requested.emit)
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
            entry.setToolTip('Optional custom label; the axis unit is added unless the text ends in ) or ]. '
                            'Clear to follow the visible channel names and units.')
        for label, widget in [("Style", self.style),
                              ("Plot title", self.title), ("X label", self.xlabel), ("Y label", self.ylabel)]:
            form.addRow(label, widget)
        layout.addLayout(form)


    def _build_plot_controls(self, layout):
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
        apply.clicked.connect(self.apply_axes_requested.emit)
        controls.addRow(apply)
        self.color = W.QPushButton("Automatic color")
        self.color.clicked.connect(self.choose_color_requested.emit)
        reset_color = W.QPushButton("Reset color")
        reset_color.clicked.connect(lambda: self.set_color_requested.emit(""))
        controls.addRow("Dataset color", self.color)
        controls.addRow(reset_color)
        self.marker = W.QComboBox()
        for label, value in MARKERS.items():
            self.marker.addItem(label, value)
        self.marker.currentIndexChanged.connect(lambda *_: self.appearance_changed_requested.emit())
        controls.addRow("Dataset marker", self.marker)
        self.legend_position = W.QComboBox()
        self.legend_position.addItems(LEGENDS)
        self.legend_position.currentTextChanged.connect(lambda *_: self.legend_changed_requested.emit())
        controls.addRow("Legend", self.legend_position)
        self.cursor_enabled = W.QCheckBox("Coordinate cursor")
        self.cursor_enabled.toggled.connect(lambda *_: self.presentation_changed_requested.emit())
        controls.addRow(self.cursor_enabled)
        layout.addWidget(self.plot_panel)
        self.plot_panel.hide()
        self.log_notice = W.QLabel()
        self.log_notice.setWordWrap(True)
        layout.addWidget(self.log_notice)
        self.coordinates = W.QLabel("")
        hint = W.QLabel("Changing channels for a hidden dataset shows it alone. Add curves above, or check datasets, to compare.")
        hint.setWordWrap(True)
        layout.addWidget(hint)


    def sync_axis_controls(self, view):
        for axis, (scale, auto, low, high) in self.axis_controls.items():
            state = view[axis]
            scale.setCurrentText(state['scale'])
            auto.setChecked(state['auto'])
            limits = state['limits'] or (0, 1)
            low.setText(f"{limits[0]:.12g}")
            high.setText(f"{limits[1]:.12g}")
            low.setEnabled(not state['auto'])
            high.setEnabled(not state['auto'])


    def read_axes(self):
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
        return proposed
