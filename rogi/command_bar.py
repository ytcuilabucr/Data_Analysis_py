"""Toolbar-style command row that wraps onto more rows instead of folding into ».

Actions are added with the usual QWidget.addAction/insertAction; each one gets a
flat QToolButton that follows the action's text, enabled state and visibility.
"""
from PySide6 import QtCore as C, QtWidgets as W


class FlowLayout(W.QLayout):
    """Left-to-right rows that wrap at the available width."""

    def __init__(self, parent=None, spacing=2):
        super().__init__(parent)
        self.items = []
        self.setSpacing(spacing)

    def addItem(self, item):
        self.items.append(item)

    def insertWidget(self, index, widget):
        self.addChildWidget(widget)
        self.items.insert(index, W.QWidgetItem(widget))
        self.invalidate()

    def count(self):
        return len(self.items)

    def itemAt(self, index):
        return self.items[index] if 0 <= index < len(self.items) else None

    def takeAt(self, index):
        return self.items.pop(index) if 0 <= index < len(self.items) else None

    def expandingDirections(self):
        return C.Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self.arrange(C.QRect(0, 0, width, 0), move=False)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self.arrange(rect, move=True)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = C.QSize()
        for item in self.items:
            if not item.isEmpty():
                size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        return size + C.QSize(margins.left() + margins.right(), margins.top() + margins.bottom())

    def arrange(self, rect, move):
        margins = self.contentsMargins()
        area = rect.adjusted(margins.left(), margins.top(), -margins.right(), -margins.bottom())
        x, y, row_height = area.x(), area.y(), 0
        for item in self.items:
            if item.isEmpty():
                continue
            hint = item.sizeHint()
            if x > area.x() and x + hint.width() > area.right() + 1:
                x, y, row_height = area.x(), y + row_height + self.spacing(), 0
            if move:
                item.setGeometry(C.QRect(C.QPoint(x, y), hint))
            x += hint.width() + self.spacing()
            row_height = max(row_height, hint.height())
        return y + row_height - rect.y() + margins.bottom()


class CommandBar(W.QWidget):
    """Shows every action as a button; rows wrap when the window is narrow."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.flow = FlowLayout(self)
        self.flow.setContentsMargins(6, 4, 6, 0)
        self.buttons = {}

    def fit_rows(self):
        """Height follows the wrapped rows at the current width, never more."""
        if not self.isVisible():  # width is a placeholder until shown; a tall bar would grow the window
            return
        height = self.flow.heightForWidth(self.width())
        if height != self.height() or self.minimumHeight() != height:
            self.setFixedHeight(height)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fit_rows()

    def actionEvent(self, event):
        action = event.action()
        if event.type() == C.QEvent.Type.ActionAdded:
            button = W.QToolButton(self)
            button.setDefaultAction(action)
            button.setAutoRaise(True)
            button.setVisible(action.isVisible())
            widgets = [item.widget() for item in self.flow.items]
            before = self.buttons.get(event.before())
            self.flow.insertWidget(widgets.index(before) if before in widgets else len(widgets), button)
            self.buttons[action] = button
        elif event.type() == C.QEvent.Type.ActionChanged:
            self.buttons[action].setVisible(action.isVisible())
            self.flow.invalidate()
            self.fit_rows()
        elif event.type() == C.QEvent.Type.ActionRemoved:
            button = self.buttons.pop(action)
            self.flow.removeWidget(button)
            button.deleteLater()
        super().actionEvent(event)
