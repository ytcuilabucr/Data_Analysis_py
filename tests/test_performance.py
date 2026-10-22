"""Exercise real offscreen GUI paths with a 10 ms timer, not worker-only timings."""
from dataclasses import fields
import time

import numpy as np
import pytest
from PySide6 import QtCore as C, QtWidgets as W

from scripts.benchmark import measure, synthetic_scan
from rogi.core import parse_text
from rogi.dialogs import SpmImportDialog
from rogi.operations import Cancelled
from rogi.project import convert_folder, load_project, save_project
from rogi.scanfile import bundle_channels
from rogi.spm import load_spm
from rogi.ui import MainWindow


@pytest.fixture
def performance_window(app):
    window = MainWindow()
    window.canvas.draw()
    app.processEvents()
    yield window
    window.dirty = False
    window.close()
    window.deleteLater()
    app.sendPostedEvents(None, C.QEvent.Type.DeferredDelete)
    app.processEvents()


def assert_dataset_equal(actual, expected):
    for field in fields(actual):
        a, b = getattr(actual, field.name), getattr(expected, field.name)
        if field.name == 'values':
            np.testing.assert_array_equal(a, b)
            assert a.flags.writeable == b.flags.writeable
        else:
            assert a == b, field.name


def responsive(operation):
    metrics, result = measure(operation, ready=lambda: not any(
        getattr(w, "operation_active", False) for w in W.QApplication.topLevelWidgets()))
    assert metrics['ticks'] >= 5
    assert metrics['max_gap_ms'] < 200, metrics
    return result


def test_large_scan_real_gui_operations_stay_responsive(performance_window, tmp_path, monkeypatch):
    w = performance_window
    source = tmp_path/'input'/'large.sxm'
    synthetic_scan(source)  # 1024 x 1024, eight channels, 32 MiB binary payload.
    expected = bundle_channels(load_spm(source))
    imported = []
    def import_scan():
        dialog = SpmImportDialog(source, w)
        dialog.import_data()
        imported.extend(dialog.datasets)
        dialog.deleteLater()
    responsive(import_scan)
    np.testing.assert_array_equal(imported[0].values, expected.values)
    assert imported[0].columns == expected.columns
    assert imported[0].source_text == expected.source_text
    assert not imported[0].values.flags.writeable
    # Independent imports mint new IDs; all other fields must be identical.
    expected.id = imported[0].id
    expected.instrument_metadata['source_dataset_id'] = expected.id
    assert_dataset_equal(imported[0], expected)

    target = tmp_path/'converted.h5'
    monkeypatch.setattr(W.QFileDialog, 'getExistingDirectory', lambda *a: str(source.parent))
    monkeypatch.setattr(W.QFileDialog, 'getSaveFileName', lambda *a: (str(target), ''))
    responsive(w.convert_folder)  # Includes the GUI's open-after-conversion path.
    saved, settings = load_project(target)
    np.testing.assert_array_equal(saved[0].values, expected.values)
    assert_dataset_equal(w.datasets[0], saved[0])
    responsive(lambda: w.open_project(target, confirm=False))
    assert_dataset_equal(w.datasets[0], saved[0])

    w.path = tmp_path/'saved.h5'
    expected_settings = w.settings()
    assert responsive(w.save)
    restored, settings = load_project(w.path)
    assert settings == expected_settings
    assert_dataset_equal(restored[0], w.datasets[0])
    responsive(lambda: (w.redraw(), w.canvas.draw()))
    assert not w.datasets[0].values.flags.writeable


@pytest.mark.parametrize('pixel_ratio', [1, 2])
def test_detached_render_matches_sync_pixels_and_keeps_callbacks_on_gui(performance_window, pixel_ratio):
    w = performance_window
    w.add_dataset(parse_text('x,y\n1,3\n2,5\n3,8'))
    w.canvas._set_device_pixel_ratio(pixel_ratio)
    w.canvas.draw()
    for scale in ['linear', 'log']:
        w.ax.set_xscale(scale)
        w.ax.set_xlim(1, 4)
        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
        FigureCanvasQTAgg.draw(w.canvas)
        expected = np.asarray(w.canvas.buffer_rgba()).copy()
        threads = []
        callback = w.canvas.mpl_connect('draw_event', lambda event: threads.append(C.QThread.currentThread()))
        w.canvas.draw()
        w.canvas.mpl_disconnect(callback)
        np.testing.assert_array_equal(np.asarray(w.canvas.buffer_rgba()), expected)
        assert threads and all(t is W.QApplication.instance().thread() for t in threads)


def test_worker_lock_cancel_error_and_close(performance_window, monkeypatch):
    w = performance_window
    errors, observed = [], []
    monkeypatch.setattr(w, 'error', errors.append)
    def inspect():
        observed.append(not w.centralWidget().isEnabled())
        observed.append(not w.file_menu.isEnabled())
        observed.append(not w.show_fitting.parent().isEnabled())
        observed.append(not w.close())
        w.worker.cancelled.set()
    C.QTimer.singleShot(20, inspect)
    with pytest.raises(Cancelled):
        w.run_operation('Test cancellation', lambda: time.sleep(.08), cancellable=True)
    assert all(observed) and w.centralWidget().isEnabled()
    def fail():
        assert C.QThread.currentThread() is not W.QApplication.instance().thread()
        raise OSError('worker failure')
    assert w.guard(lambda: w.run_operation('Failure', fail)) is False
    assert errors == ['worker failure']
    assert not w.operation_active and w.file_menu.isEnabled()


@pytest.mark.parametrize('suffix', ['h5', 'json'])
def test_worker_save_failure_is_atomic(performance_window, tmp_path, monkeypatch, suffix):
    w = performance_window
    w.datasets = [parse_text('x,y\n0,1\n1,2')]
    w.path = tmp_path/f'project.{suffix}'
    save_project(w.path, w.datasets, {})
    before = w.path.read_bytes()
    w.changed()
    import os
    def fail(*args):
        raise OSError('replace failed')
    monkeypatch.setattr(os, 'replace', fail)
    with pytest.raises(OSError, match='replace failed'):
        w.save()
    assert w.path.read_bytes() == before
    assert w.dirty and w.centralWidget().isEnabled()
    assert sorted(p.name for p in tmp_path.iterdir()) == [w.path.name]
    assert not w.datasets[0].values.flags.writeable


def test_conversion_cancellation_preserves_destination(performance_window, tmp_path):
    source = tmp_path/'input'
    source.mkdir()
    (source/'a.csv').write_text('x,y\n0,1\n1,2')
    target = tmp_path/'existing.h5'
    target.write_bytes(b'original')
    calls = []
    def cancel_before_save():
        calls.append(True)
        if len(calls) == 2:
            raise Cancelled('cancelled')
    with pytest.raises(Cancelled):
        performance_window.run_operation('Convert', lambda: convert_folder(
            source, target, cancel_check=cancel_before_save))
    assert target.read_bytes() == b'original'


def test_render_discards_snapshot_if_resized(performance_window, monkeypatch, app):
    from rogi import canvas
    w = performance_window
    original = canvas.render_snapshot
    def slow_render(payload, dpi=None):
        time.sleep(.04)
        return original(payload, dpi)
    monkeypatch.setattr(canvas, 'render_snapshot', slow_render)
    C.QTimer.singleShot(10, lambda: w.figure.set_size_inches(6, 4, forward=False))
    w.canvas.draw()
    w.canvas.draw()
    assert w.canvas.renderer.width == w.figure.bbox.width
    assert w.canvas.renderer.height == w.figure.bbox.height


def test_legacy_project_first_plot_and_metadata_filter(performance_window):
    from pathlib import Path
    from rogi.browser_panel import filter_dataset_ids
    path = Path(__file__).resolve().parents[1]/'example-data'/'260813.rogi.h5'
    if not path.exists():
        pytest.skip('Optional local instrument project is not checked into Git')
    w = performance_window
    datasets, _ = load_project(path)
    w.datasets = datasets
    responsive(lambda: (w.refresh_history_view(), w.canvas.draw()))
    expected = filter_dataset_ids(datasets, None, 'bias', False, '', '', '', '')
    responsive(lambda: w.search.setText('bias'))
    actual = {w.browser.item(i).data(C.Qt.ItemDataRole.UserRole)
              for i in range(w.browser.count()) if w.browser.item(i).isHidden()}
    assert actual == expected


def test_raster_validation_preserves_shuffled_pixels_and_rejects_duplicates():
    from rogi.core import Dataset
    from rogi.images import raster
    x, y = np.meshgrid(np.arange(64), np.arange(32))
    values = np.column_stack((np.arange(x.size), x.ravel(), y.ravel(), np.arange(x.size)))
    shuffled = values[np.random.default_rng(42).permutation(len(values))]
    dataset = Dataset('grid', ['Sample', 'X pixel', 'Y pixel', 'Signal'], shuffled)
    np.testing.assert_array_equal(raster(dataset), np.arange(x.size).reshape(x.shape))
    shuffled[0, 1:3] = shuffled[1, 1:3]
    duplicate = Dataset('grid', dataset.columns, shuffled)
    with pytest.raises(ValueError, match='duplicate'):
        raster(duplicate)
