"""Qt worker execution with a responsive, synchronous compatibility facade.

Only the callable runs in the worker. Results, editing locks and dialogs belong
to the GUI thread. A local event loop preserves callers' return/error semantics;
input is locked while it runs. Cancellation is cooperative, never terminate().
"""
from threading import Event
from PySide6 import QtCore as C, QtWidgets as W


class Cancelled(ValueError):
    pass


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

    widget.window() is not enough: from inside a floating dock it is the dock.
    """
    while widget is not None:
        if hasattr(widget, 'project_actions'):
            return widget
        widget = widget.parentWidget()
    return None


def set_editing_enabled(window, enabled):
    """Shared by fits and other operations; preserve the fit editing boundary."""
    enabled = enabled and not getattr(window, 'operation_active', False)
    window.centralWidget().setEnabled(enabled)
    # The plot dock floats as its own window; lock it explicitly rather than
    # relying on where it sits in the widget tree.
    if getattr(window, 'plot_dock', None) is not None:
        window.plot_dock.widget().setEnabled(enabled)
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
    dialog = W.QProgressDialog(label + '…', 'Cancel' if cancellable else '', 0, 0, root)
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
