"""Compact, text-only navigation shared by line plots and image maps."""
import io
from pathlib import Path
from PySide6 import QtCore as C, QtGui as G, QtWidgets as W
from matplotlib.backends.backend_qtagg import NavigationToolbar2QT

EXPORT_DPI = 180


def export_figure(parent, figure):
    path, chosen = W.QFileDialog.getSaveFileName(parent, "Export plot", "plot.png", "PNG (*.png);;SVG (*.svg)")
    if path:
        if not Path(path).suffix:
            path += '.svg' if chosen.startswith('SVG') else '.png'
        if Path(path).suffix.lower() not in ('.png', '.svg'):
            raise ValueError("Choose a .png or .svg filename.")
        figure.savefig(path, dpi=EXPORT_DPI)


def copy_figure(figure):
    """Put the figure on the clipboard as an image, at export resolution."""
    buffer = io.BytesIO()
    figure.savefig(buffer, format='png', dpi=EXPORT_DPI)
    W.QApplication.clipboard().setImage(G.QImage.fromData(buffer.getvalue(), 'PNG'))


class PlotNavigationToolbar(NavigationToolbar2QT):
    toolitems = (
        ('Reset view', 'Return to the initial view', 'home', 'home'),
        ('Pan', 'Drag the plot to move the view; click again to turn off', 'move', 'pan'),
        ('Zoom', 'Drag a rectangle to zoom in; click again to turn off', 'zoom_to_rect', 'zoom'),
        (None, None, None, None),
        ('Copy', 'Copy this plot to the clipboard as an image', 'filesave', 'copy_plot'),
        ('Export…', 'Save this plot as PNG or SVG', 'filesave', 'export_plot'),
    )

    def __init__(self, canvas, parent=None):
        super().__init__(canvas, parent, coordinates=False)
        self.setToolButtonStyle(C.Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.setMovable(False)

    def copy_plot(self):
        copy_figure(self.canvas.figure)

    def export_plot(self):
        try:
            export_figure(self.window(), self.canvas.figure)
        except (OSError, ValueError) as error:
            W.QMessageBox.warning(self.window(), "Export plot", str(error))
