"""Matplotlib canvas that defers drawing while a worker operation is running.

Rendering itself stays synchronous on the GUI thread: plots redraw on almost
every click, and routing each draw through a locked worker operation disabled
the whole window per click (visible flashing and swallowed input).
"""
from contextlib import contextmanager
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg


_held = [0]
_held_canvases = set()


@contextmanager
def hold_draws():
    """Skip every canvas draw while the GUI waits on background work; draw each once afterwards.

    Otherwise each wait renders whatever draw_idle is queued, and the next change renders again.
    """
    _held[0] += 1
    try:
        yield
    finally:
        _held[0] -= 1
        if not _held[0]:
            pending = list(_held_canvases)
            _held_canvases.clear()
            for canvas in pending:
                canvas.draw_idle()


class ResponsiveCanvas(FigureCanvasQTAgg):
    def draw(self):
        if _held[0]:
            _held_canvases.add(self)
            return
        root = self.window()
        if getattr(root, 'operation_active', False):
            # An earlier draw_idle may arrive inside an I/O worker's event loop.
            # Do not render the figure while the operation holds the editing lock;
            # run_operation redraws pending canvases once it finishes.
            if not hasattr(root, '_pending_canvases'):
                root._pending_canvases = set()
            root._pending_canvases.add(self)
            return
        super().draw()
