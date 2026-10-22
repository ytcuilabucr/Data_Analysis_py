"""Full-resolution Agg rendering of detached figures in a worker thread.

Qt widgets and the live figure remain on the GUI thread. Pickling a Figure
excludes its GUI canvas and non-pickleable callbacks. The worker owns the copy;
only its completed renderer and axes layout are published back on the GUI thread.
"""
import pickle
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.backend_bases import DrawEvent
from PySide6 import QtCore as C
from .operations import run_operation


def render_snapshot(payload, dpi=None):
    figure = pickle.loads(payload)
    # Figure pickling deliberately resets HiDPI to its original logical DPI.
    if dpi is not None:
        figure.set_dpi(dpi)
    canvas = FigureCanvasAgg(figure)
    canvas.draw()
    positions = [(ax.get_position(original=True).frozen(), ax.get_position().frozen())
                 for ax in figure.axes]
    return canvas.renderer, positions


class ResponsiveCanvas(FigureCanvasQTAgg):
    def draw(self):
        if self._is_drawing:
            return
        root = self.window()
        if getattr(root, 'operation_active', False):
            # An earlier draw_idle may arrive inside an I/O worker's event loop.
            # Never start a second operation or change the locked figure.
            if not hasattr(root, '_pending_canvases'):
                root._pending_canvases = set()
            root._pending_canvases.add(self)
            return
        self._is_drawing = True
        self._draw_pending = False
        try:
            size = (self.figure.bbox.width, self.figure.bbox.height, self.figure.dpi)
            payload = pickle.dumps(self.figure, protocol=pickle.HIGHEST_PROTOCOL)
            renderer, positions = run_operation(self, 'Rendering plot', lambda: render_snapshot(payload, size[2]))
            if size != (self.figure.bbox.width, self.figure.bbox.height, self.figure.dpi):
                self.figure.stale = True
                C.QTimer.singleShot(0, self.draw_idle)
                return
            for ax, (original, active) in zip(self.figure.axes, positions):
                # Private position setter preserves constrained-layout membership.
                ax._set_position(original, which='original')
                ax._set_position(active, which='active')
            self.renderer = renderer
            self._lastKey = (self.figure.bbox.width, self.figure.bbox.height, self.figure.dpi)
            self.figure.stale = False
            DrawEvent('draw_event', self, renderer)._process()
        except Exception as error:
            if hasattr(root, 'error'):
                root.error(str(error))
            else:
                raise
        finally:
            self._is_drawing = False
        self.update()
