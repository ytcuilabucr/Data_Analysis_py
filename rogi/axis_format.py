"""Format Axis dialog: label text, font, ticks and range of one line-plot axis.

Also the shared pieces of the plot formatting dialogs: live preview with one undo
step on OK, and a color choice.

Edits preview on the plot as they are made. OK records them as one undo step;
Cancel puts the axis back as it was. The X label and both axis styles are shared
by all panels; the Y label and the ranges belong to one panel, except that a
synchronized X range follows every panel. The look of this axis (font, ticks,
grid) can be copied to the other axis in the same step.
"""
from copy import deepcopy
from PySide6 import QtCore as C, QtGui as G, QtWidgets as W
from matplotlib import font_manager
from .history import ChangeCommand
from .operations import dialog_parent
from .plot_actions import automatic_labels
from .plotting import (AXIS_OWN_KEYS, AXIS_STYLE, FONT_SIZES, MINOR_TICKS, NUMBER_FORMATS, TICK_DIRECTIONS,
                       check_label, validate_axis_style, validate_view)
from .units import display_unit

GENERIC_FAMILIES = ('sans-serif', 'serif', 'monospace')
TICK_LENGTHS = (0, 2, 3.5, 5, 7, 10)
PREVIEW_DELAY_MS = 150  # a redraw replots every curve; wait for typing to pause


def label_text(window, axis, index):
    if axis == 'x':
        return window.xlabel.text()
    return window.ylabel.text() if index == window.active_panel else window.panels[index].get('ylabel', '')


def other_axis(axis):
    return 'y' if axis == 'x' else 'x'


def capture(window, axis, index):
    """Everything the dialog can change, for preview, Cancel and undo."""
    panels = range(len(window.panels)) if axis == 'x' and window.sync_x else [index]
    return dict(text=label_text(window, axis, index), style=deepcopy(window.plot_style[axis + '_axis']),
                other=deepcopy(window.plot_style[other_axis(axis) + '_axis']),
                views={i: deepcopy(window.panels[i]['view'][axis]) for i in panels})


def apply_state(window, axis, index, state):
    if axis == 'x':
        window.xlabel.setText(state['text'])
    elif index < len(window.panels):
        window.panels[index]['ylabel'] = state['text']
        if index == window.active_panel:
            window.ylabel.setText(state['text'])
    window.plot_style[axis + '_axis'] = deepcopy(state['style'])
    window.plot_style[other_axis(axis) + '_axis'] = deepcopy(state['other'])
    for i, view in state['views'].items():
        if i < len(window.panels):  # a panel removed since stays removed
            window.panels[i]['view'][axis] = deepcopy(view)
    window.redraw()
    window.navigation.update()


def font_families():
    return GENERIC_FAMILIES + tuple(sorted({font.name for font in font_manager.fontManager.ttflist}))


def size_box(current, sizes=FONT_SIZES):
    box = W.QComboBox()
    box.addItem('Default', None)
    if current is not None and current not in sizes:
        sizes = tuple(sorted(sizes + (current,)))  # a size typed into a saved project
    for size in sizes:
        box.addItem(f'{size:g} pt', size)
    box.setCurrentIndex(box.findData(current))
    return box


def choice_box(choices, current):
    box = W.QComboBox()
    for text, value in choices.items():
        box.addItem(text, value)
    box.setCurrentIndex(box.findData(current))
    return box


class ColorChoice(W.QWidget):
    """A color button with Reset; '' means Matplotlib's automatic color."""
    changed = C.Signal()

    def __init__(self, color, title, parent=None):
        super().__init__(parent)
        self.color, self.title = color, title
        self.button = W.QPushButton()
        self.button.clicked.connect(self.choose)
        reset = W.QPushButton("Reset")
        reset.clicked.connect(lambda: self.set_color(''))
        layout = W.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.button)
        layout.addWidget(reset)
        self.show_color()

    def choose(self):
        color = W.QColorDialog.getColor(G.QColor(self.color or 'black'), self, self.title)
        if color.isValid():
            self.set_color(color.name())

    def set_color(self, color):
        self.color = color
        self.show_color()
        self.changed.emit()

    def show_color(self):
        self.button.setText(self.color or "Automatic")
        self.button.setStyleSheet(f"color: {self.color};" if self.color else "")


class PreviewDialog(W.QDialog):
    """Applies edits to the plot as they are made; OK keeps them as one undo step, Cancel restores.

    Subclasses build their fields, set self.window, self.before (the captured
    state) and self.undo_label, call finish_layout() and watch(), and implement
    read() (the edited state, or ValueError) and apply(state).
    """

    def finish_layout(self, layout):
        self.status = W.QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.buttons = W.QDialogButtonBox(W.QDialogButtonBox.StandardButton.Ok | W.QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.applied = self.before
        self.timer = C.QTimer(self, singleShot=True, interval=PREVIEW_DELAY_MS)
        self.timer.timeout.connect(self.preview)

    def watch(self, *widgets):
        """Preview after any of these widgets changes."""
        for widget in widgets:
            for name in ('textChanged', 'currentIndexChanged', 'valueChanged', 'toggled', 'changed', 'itemChanged'):
                if hasattr(widget, name):
                    getattr(widget, name).connect(self.timer.start)
                    break

    def preview(self):
        try:
            state = self.read()
        except ValueError as error:
            self.status.setText(str(error))
            self.buttons.button(W.QDialogButtonBox.StandardButton.Ok).setEnabled(False)
            return None
        self.status.clear()
        self.buttons.button(W.QDialogButtonBox.StandardButton.Ok).setEnabled(True)
        if state != self.applied:
            self.apply(state)
            self.applied = state
        return state

    def accept(self):
        self.timer.stop()
        after = self.preview()
        if after is None:
            return
        if after == self.before:
            self.restore()
        else:
            before = self.before
            # Pushing runs the command once, which applies the edited state again.
            self.window.history.push(ChangeCommand(self.window, self.undo_label,
                                                   lambda: self.apply(after), lambda: self.apply(before)))
        super().accept()

    def reject(self):
        self.timer.stop()
        self.restore()
        super().reject()

    def restore(self):
        if self.applied is not self.before:
            self.apply(self.before)
            self.applied = self.before


def row(*widgets):
    widget = W.QWidget()
    layout = W.QHBoxLayout(widget)
    layout.setContentsMargins(0, 0, 0, 0)
    for item in widgets:
        layout.addWidget(item)
    return widget


class FormatAxisDialog(PreviewDialog):
    def __init__(self, window, axis, index, parent=None):
        super().__init__(parent)
        self.window, self.axis, self.index = window, axis, index
        name = axis.upper()
        self.undo_label = f"Format {name} axis"
        several = len(window.panels) > 1
        self.setWindowTitle(f"Format {name} axis" + (f" — panel {index + 1}" if several and axis == 'y' else ''))
        self.before = capture(window, axis, index)
        x_label, y_label, x_units, y_units = automatic_labels(window, index)
        self.automatic, self.units = (x_label, x_units) if axis == 'x' else (y_label, y_units)
        style = self.before['style']
        view = self.before['views'][index]
        layout = W.QVBoxLayout(self)
        tabs = W.QTabWidget()
        layout.addWidget(tabs)

        page = W.QWidget()
        form = W.QFormLayout(page)
        self.text = W.QLineEdit(self.before['text'])
        self.text.setPlaceholderText(self.automatic)
        self.text.setAccessibleName(f"{name} label")
        automatic_label = W.QPushButton("Automatic")
        automatic_label.setToolTip("Clear the text to follow the visible channel names and units.")
        automatic_label.clicked.connect(self.text.clear)
        form.addRow("Label", row(self.text, automatic_label))
        known = set(self.units) - {''}
        unit = (f" ({display_unit(next(iter(known)))})" if len(known) == 1 and len(set(self.units)) == 1
                else " when all curves share one")
        self.unit = W.QCheckBox("Append the axis unit" + unit)
        self.unit.setChecked(style['unit'])
        self.unit.setToolTip("A label already ending in ) or ] is left as typed.")
        form.addRow(self.unit)
        scope = ("The X label is shared by all panels." if axis == 'x'
                 else f"This Y label belongs to panel {index + 1} only." if several else "")
        hint = W.QLabel(("Leave empty for the automatic label, shown in grey. "
                         "Write math between dollar signs: $\\mu$m, I$_{tip}$, 10$^{-3}$. " + scope).strip())
        hint.setWordWrap(True)
        form.addRow(hint)
        tabs.addTab(page, "Label")

        page = W.QWidget()
        form = W.QFormLayout(page)
        self.family = W.QComboBox()
        self.family.addItem('Default', '')
        families = font_families()
        if style['family'] and style['family'] not in families:
            families += (style['family'],)  # saved on a computer with other fonts
        for family in families:
            self.family.addItem(family, family)
        self.family.setCurrentIndex(self.family.findData(style['family']))
        form.addRow("Font", self.family)
        self.label_size = size_box(style['label_size'])
        form.addRow("Label size", self.label_size)
        self.tick_size = size_box(style['tick_size'])
        form.addRow("Tick label size", self.tick_size)
        self.bold = W.QCheckBox("Bold label")
        self.bold.setChecked(style['bold'])
        self.italic = W.QCheckBox("Italic label")
        self.italic.setChecked(style['italic'])
        form.addRow(self.bold)
        form.addRow(self.italic)
        self.color = ColorChoice(style['color'], f"{name} axis color")
        form.addRow("Color", self.color)
        defaults = W.QPushButton("Default font")
        defaults.clicked.connect(self.default_font)
        form.addRow(defaults)
        note = W.QLabel(f"Font and color also apply to the tick labels. These settings apply to the {name} axis "
                        "of every panel.")
        note.setWordWrap(True)
        form.addRow(note)
        tabs.addTab(page, "Font")

        page = W.QWidget()
        form = W.QFormLayout(page)
        self.direction = choice_box(TICK_DIRECTIONS, style['tick_direction'])
        form.addRow("Direction", self.direction)
        self.length = size_box(style['tick_length'], TICK_LENGTHS)
        form.addRow("Length", self.length)
        self.minor = choice_box(MINOR_TICKS, style['minor_ticks'])
        self.minor.setToolTip("Automatic: none on linear scales, Matplotlib's minor ticks on log scales.")
        form.addRow("Minor ticks", self.minor)
        self.number_format = choice_box(NUMBER_FORMATS, style['number_format'])
        self.decimals = W.QSpinBox()
        self.decimals.setRange(0, 12)
        self.decimals.setValue(style['decimals'])
        self.decimals.setSuffix(" decimals")
        form.addRow("Numbers", row(self.number_format, self.decimals))
        self.fixed_step = W.QCheckBox("Every")
        self.fixed_step.setChecked(style['tick_step'] is not None)
        self.step = W.QLineEdit(f"{style['tick_step']:.12g}" if style['tick_step'] else '')
        self.step.setPlaceholderText("spacing")
        self.step.setAccessibleName(f"{name} tick spacing")
        form.addRow("Major ticks", row(self.fixed_step, self.step))
        self.grid = W.QCheckBox("Grid lines at major ticks")
        self.grid.setChecked(style['grid'])
        form.addRow(self.grid)
        defaults = W.QPushButton("Default ticks")
        defaults.clicked.connect(self.default_ticks)
        form.addRow(defaults)
        note = W.QLabel("Fixed spacing applies to linear scales; log scales keep one major tick per decade. "
                        "A spacing that would draw more ticks than fit falls back to automatic ticks. "
                        f"These settings apply to the {name} axis of every panel.")
        note.setWordWrap(True)
        form.addRow(note)
        tabs.addTab(page, "Ticks")

        page = W.QWidget()
        form = W.QFormLayout(page)
        self.scale = W.QComboBox()
        self.scale.addItems(['linear', 'log'])
        self.scale.setCurrentText(view['scale'])
        form.addRow("Scale", self.scale)
        self.auto = W.QCheckBox("Automatic limits")
        self.auto.setChecked(view['auto'])
        form.addRow(self.auto)
        limits = view['limits'] or (0, 1)
        self.low, self.high = W.QLineEdit(f"{limits[0]:.12g}"), W.QLineEdit(f"{limits[1]:.12g}")
        form.addRow("Minimum", self.low)
        form.addRow("Maximum", self.high)
        for field in (self.low, self.high):
            field.setEnabled(not view['auto'])
        self.auto.toggled.connect(lambda checked: (self.low.setEnabled(not checked), self.high.setEnabled(not checked)))
        self.invert = W.QCheckBox("Invert axis (values decrease " + ("to the right)" if axis == 'x' else "upward)"))
        self.invert.setChecked(style['invert'])
        self.invert.setToolTip(f"Applies to the {name} axis of every panel.")
        form.addRow(self.invert)
        scope = ("X limits are synchronized: the range applies to every panel." if axis == 'x' and window.sync_x
                 else f"The range applies to panel {index + 1}." if several else "")
        if scope:
            note = W.QLabel(scope)
            note.setWordWrap(True)
            form.addRow(note)
        tabs.addTab(page, "Scale && range")

        other = other_axis(axis).upper()
        self.copy_style = W.QCheckBox(f"Use this font, ticks and grid for the {other} axis too")
        self.copy_style.setToolTip(f"The {other} axis keeps its own label, unit setting, tick spacing and inversion.")
        layout.addWidget(self.copy_style)
        self.finish_layout(layout)
        self.enable_tick_fields()
        self.watch(self.text, self.low, self.high, self.step, self.family, self.label_size, self.tick_size,
                   self.scale, self.direction, self.length, self.minor, self.number_format, self.decimals,
                   self.unit, self.bold, self.italic, self.auto, self.fixed_step, self.grid, self.invert,
                   self.copy_style, self.color)
        for widget in (self.number_format, self.scale):
            widget.currentIndexChanged.connect(self.enable_tick_fields)
        self.fixed_step.toggled.connect(self.enable_tick_fields)

    def enable_tick_fields(self, *args):
        self.decimals.setEnabled(self.number_format.currentData() == 'fixed')
        linear = self.scale.currentText() == 'linear'
        self.fixed_step.setEnabled(linear)
        self.step.setEnabled(linear and self.fixed_step.isChecked())

    def default_font(self):
        for box, key in ((self.family, 'family'), (self.label_size, 'label_size'), (self.tick_size, 'tick_size')):
            box.setCurrentIndex(box.findData(AXIS_STYLE[key]))
        self.bold.setChecked(AXIS_STYLE['bold'])
        self.italic.setChecked(AXIS_STYLE['italic'])
        self.color.set_color(AXIS_STYLE['color'])

    def default_ticks(self):
        for box, key in ((self.direction, 'tick_direction'), (self.length, 'tick_length'),
                         (self.minor, 'minor_ticks'), (self.number_format, 'number_format')):
            box.setCurrentIndex(box.findData(AXIS_STYLE[key]))
        self.decimals.setValue(AXIS_STYLE['decimals'])
        self.fixed_step.setChecked(AXIS_STYLE['tick_step'] is not None)
        self.grid.setChecked(AXIS_STYLE['grid'])

    def tick_step(self):
        if not self.fixed_step.isChecked():
            return None
        try:
            return float(self.step.text())
        except ValueError:
            raise ValueError("Enter a number for the tick spacing.") from None

    def read(self):
        """The edited state, or ValueError naming the first problem."""
        text = self.text.text()
        if text.strip():
            check_label(text)
        style = dict(label_size=self.label_size.currentData(), tick_size=self.tick_size.currentData(),
                     family=self.family.currentData(), color=self.color.color, bold=self.bold.isChecked(),
                     italic=self.italic.isChecked(), unit=self.unit.isChecked(),
                     tick_direction=self.direction.currentData(), tick_length=self.length.currentData(),
                     minor_ticks=self.minor.currentData(), number_format=self.number_format.currentData(),
                     decimals=self.decimals.value(), tick_step=self.tick_step(), grid=self.grid.isChecked(),
                     invert=self.invert.isChecked())
        validate_axis_style(style)
        other = self.before['other']
        if self.copy_style.isChecked():
            other = {**other, **{key: value for key, value in style.items() if key not in AXIS_OWN_KEYS}}
        scale, auto, limits = self.scale.currentText(), self.auto.isChecked(), None
        if not auto:
            try:
                limits = [float(self.low.text()), float(self.high.text())]
            except ValueError:
                raise ValueError("Enter a number for the minimum and the maximum.") from None
            if limits[0] >= limits[1]:
                raise ValueError("The minimum must be less than the maximum.")
        validate_view({self.axis + 'scale': scale, self.axis + 'auto': auto, self.axis + 'lim': limits})
        views = {i: dict(scale=scale, auto=auto, limits=limits or before['limits'])
                 for i, before in self.before['views'].items()}
        return dict(text=text, style=style, other=other, views=views)

    def apply(self, state):
        apply_state(self.window, self.axis, self.index, state)


def format_axis(window, axis, index):
    FormatAxisDialog(window, axis, index, dialog_parent(window)).exec()
