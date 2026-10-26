"""Qt worker execution with a responsive, synchronous compatibility facade.

Only the callable runs in the worker. Results, editing locks and dialogs belong
to the GUI thread. A local event loop preserves callers' return/error semantics;
input is locked while it runs. Cancellation is cooperative, never terminate().
"""
import gc
from threading import Event
from PySide6 import QtCore as C, QtWidgets as W


class Cancelled(ValueError):
    pass


class MainThreadCollector(C.QObject):
    """Run Python's cyclic garbage collector only on the GUI thread.

    Automatic collection starts in whichever thread happens to allocate, including
    worker threads. Collecting a cycle that holds Qt wrappers there makes shiboken
    defer the C++ delete to the GUI thread, which segfaults if Qt has already
    destroyed the object (macOS: "Python quit unexpectedly", crash report frame
    mainThreadDeletionHandler). Thresholds keep the normal collection cadence.
    """

    def __init__(self, parent=None, interval_ms=500):
        super().__init__(parent)
        self.threshold = gc.get_threshold()
        gc.disable()
        self.timer = C.QTimer(self)
        self.timer.timeout.connect(self.check)
        self.timer.start(interval_ms)

    def check(self):
        counts = gc.get_count()
        generation = -1
        for level, (count, threshold) in enumerate(zip(counts, self.threshold)):
            if threshold and count > threshold:
                generation = level
        if generation >= 0:
            gc.collect(generation)


def collect_on_main_thread(app):
    """Install once per QApplication; returns the existing collector if present."""
    existing = app.findChild(MainThreadCollector)
    return existing if existing is not None else MainThreadCollector(app)


class OperationWorker(C.QThread):
    result = C.Signal(object)
    failed = C.Signal(object)
    committing = C.Signal()

    def __init__(self, function, parent=None):
        super().__init__(parent)
        self.function = function
        self.cancelled = Event()

    def check_cancelled(self):
        if self.cancelled.is_set():
            raise Cancelled('Operation cancelled.')

    def run(self):
        try:
            self.result.emit(self.function())
        except Exception as error:
            self.failed.emit(error)


def coordinator(widget):
    """The window that owns project actions and the editing lock.

    widget.window() is not enough: from inside the plot window it is the plot window.
    """
    while widget is not None:
        if hasattr(widget, 'project_actions'):
            return widget
        widget = widget.parentWidget()
    return None


def dialog_parent(window):
    """Open dialogs over the plot or Files window when the user is working there, not the file window."""
    active = W.QApplication.activeWindow()
    return active if active is not None and coordinator(active) is window else window


def set_editing_enabled(window, enabled):
    """Shared by fits and other operations; preserve the fit editing boundary."""
    enabled = enabled and not getattr(window, 'operation_active', False)
    window.centralWidget().setEnabled(enabled)
    # The plot and Files windows are separate top-level windows.
    for child in ('plot_window', 'files_window'):
        if getattr(window, child, None) is not None:
            getattr(window, child).centralWidget().setEnabled(enabled)
    window.edit_menu.setEnabled(enabled)
    window.file_menu.setEnabled(enabled)
    # View actions can also mutate plot state during a worker operation.
    window.show_fitting.parent().setEnabled(enabled)
    for action in window.project_actions.values():
        action.setEnabled(enabled)
    window.copy_action.setEnabled(False)
    window.paste_action.setEnabled(False)
    window.undo_action.setEnabled(enabled and window.history.canUndo())
    window.redo_action.setEnabled(enabled and window.history.canRedo())
    window.findChild(W.QToolBar).setEnabled(enabled)
    if enabled:
        window.update_clipboard_actions()
        # The loop above enabled every project command; restore selection-dependent ones.
        window.update_analysis_actions()


def run_in_background(function):
    """Run short data-only work in a worker while the GUI keeps processing events.

    Unlike run_operation nothing is locked and no dialog is shown, so interactive
    redraws do not flash the window. Callers must tolerate re-entrant events
    during the wait (see images.deferred_while_busy).
    """
    loop = C.QEventLoop()
    results, errors = [], []
    worker = OperationWorker(function)
    worker.result.connect(results.append)
    worker.failed.connect(errors.append)
    worker.finished.connect(loop.quit)
    try:
        worker.start()
        loop.exec()
        worker.wait()
    finally:
        worker.function = None
        worker.deleteLater()
    if errors:
        raise errors[0]
    return results[0]


def run_operation(parent, label, function, *, cancellable=False, cooperative=False):
    """Run data-only work; readonly cancellation discards the completed result.

    Cooperative callables receive check_cancelled and begin_commit callbacks.
    Saves are deliberately non-cancellable once writing starts.
    """
    root = coordinator(parent)
    coordinated = root is not None
    if not coordinated:
        root = parent.window() if parent is not None else None
    if coordinated and getattr(root, 'operation_active', False):
        raise ValueError('Wait for the current operation to finish.')
    loop = C.QEventLoop()
    results, errors = [], []
    worker = OperationWorker(None, parent)
    def execute():
        worker.check_cancelled()
        value = function(worker.check_cancelled, worker.committing.emit) if cooperative else function()
        if cancellable and not cooperative:
            worker.check_cancelled()
        return value
    worker.function = execute
    worker.result.connect(results.append)
    worker.failed.connect(errors.append)
    worker.finished.connect(loop.quit)
    dialog = W.QProgressDialog(label + '…', 'Cancel' if cancellable else '', 0, 0,
                               dialog_parent(root) if coordinated else root)
    dialog.setWindowModality(C.Qt.WindowModality.ApplicationModal)
    dialog.setMinimumDuration(150)
    dialog.setAutoClose(False)
    dialog.setAutoReset(False)
    dialog.setValue(0)
    if not cancellable:
        dialog.setCancelButton(None)
    dialog.canceled.connect(worker.cancelled.set)
    worker.committing.connect(lambda: (dialog.setLabelText('Saving project (cannot cancel)…'),
                                      dialog.setCancelButton(None)))
    old_worker = getattr(root, 'worker', None) if coordinated else None
    if coordinated:
        root.operation_active = True
        root.worker = worker
        set_editing_enabled(root, False)
        root.statusBar().showMessage(label + '…')
    dialog_parent_enabled = parent.isEnabled() if isinstance(parent, W.QDialog) else None
    if dialog_parent_enabled is not None:
        parent.setEnabled(False)
    try:
        worker.start()
        loop.exec()
        worker.wait()
    finally:
        if dialog_parent_enabled is not None:
            parent.setEnabled(dialog_parent_enabled)
        dialog.reset()
        dialog.close()
        dialog.deleteLater()
        if coordinated:
            root.worker = old_worker
            root.operation_active = False
            set_editing_enabled(root, not (old_worker and old_worker.isRunning()))
            root.statusBar().showMessage(label + ' finished', 4000)
            pending = getattr(root, '_pending_canvases', set())
            root._pending_canvases = set()
            for canvas in pending:
                if canvas.figure.stale and not canvas._is_drawing:
                    canvas.draw_idle()
        worker.function = None
        worker.deleteLater()
    if errors:
        raise errors[0]
    return results[0]
