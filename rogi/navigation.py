"""Compact, text-only navigation shared by line plots and image maps."""
from PySide6 import QtCore as C
from matplotlib.backends.backend_qtagg import NavigationToolbar2QT


class PlotNavigationToolbar(NavigationToolbar2QT):
    toolitems = (
        ('Reset view', 'Return to the initial view', 'home', 'home'),
        ('Pan', 'Drag the plot to move the view; click again to turn off', 'move', 'pan'),
        ('Zoom', 'Drag a rectangle to zoom in; click again to turn off', 'zoom_to_rect', 'zoom'),
    )

    def __init__(self, canvas, parent=None):
        super().__init__(canvas, parent, coordinates=False)
        self.setToolButtonStyle(C.Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.setMovable(False)
