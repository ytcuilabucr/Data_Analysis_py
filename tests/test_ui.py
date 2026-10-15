import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('MPLCONFIGDIR', '/tmp/rogi-matplotlib-tests')
import time
from PySide6 import QtWidgets as W
from rogi.ui import MainWindow, ImportDialog
from rogi.project import load_project


def test_desktop_workflow(tmp_path, monkeypatch):
    app = W.QApplication.instance() or W.QApplication([])
    path = tmp_path/'input.csv'
    path.write_text('x,y\n0,1\n1,3\n2,5\n3,7\n4,9')
    dialog = ImportDialog(path)
    assert dialog.preview.rowCount() == 5
    dialog.import_data()
    window = MainWindow()
    window.show()
    window.add_dataset(dialog.dataset)
    window.make_copy()
    assert window.table_model.setData(window.table_model.index(0, 1), '1.01')
    window.start_fit()
    deadline = time.monotonic()+15
    while window.worker.isRunning() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.01)
    app.processEvents()
    assert window.current().fit is not None
    assert 'slope' in window.result.toPlainText()
    assert len(window.ax.lines) >= 3
    for extension in ('png', 'svg'):
        window.figure.savefig(tmp_path/f'plot.{extension}')
        assert (tmp_path/f'plot.{extension}').stat().st_size > 1000
    window.path = tmp_path/'project.json'
    window.title.setText('Synthetic workflow')
    assert window.save()
    datasets, settings = load_project(window.path)
    assert len(datasets) == 2 and settings['title'] == 'Synthetic workflow'
    monkeypatch.setattr(W.QFileDialog, 'getOpenFileName', lambda *a, **k: (str(window.path), ''))
    window.open_project()
    assert window.current().fit['parameters']['slope'] > 1.99
    assert window.title.text() == 'Synthetic workflow'
    window.dirty = False
    window.close()
    dialog.close()
