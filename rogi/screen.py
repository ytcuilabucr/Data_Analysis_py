"""Window sizing against the screen's available area (excludes menu bar and dock)."""
from PySide6 import QtCore as C, QtGui as G

# Title bar and borders before the window manager reports real frame margins.
FRAME_ALLOWANCE = C.QSize(16, 48)


def available_area(widget):
    screen = widget.screen() or G.QGuiApplication.primaryScreen()
    return screen.availableGeometry() if screen is not None else None


def fit_to_screen(widget, width=None, height=None):
    """Resize to width × height capped at the available area; None fills that dimension.

    A visible window uses its actual frame margins and fills the area from its
    top-left; a hidden one keeps its position and assumes FRAME_ALLOWANCE.
    """
    area = available_area(widget)
    if area is None:
        widget.resize(width or 1280, height or 850)
        return
    if widget.isVisible():
        frame = widget.frameGeometry().size() - widget.geometry().size()
    else:
        frame = FRAME_ALLOWANCE
    room = area.size() - frame
    size = C.QSize(room.width() if width is None else min(width, room.width()),
                   room.height() if height is None else min(height, room.height()))
    widget.resize(size.expandedTo(widget.minimumSize()))
    if width is None and height is None and widget.isVisible():
        widget.move(area.topLeft())
