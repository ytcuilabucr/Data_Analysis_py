import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('MPLCONFIGDIR', '/tmp/rogi-matplotlib-tests')
import time
import subprocess
import sys
from pathlib import Path
from PySide6 import QtWidgets as W
from PySide6.QtCore import Qt
from rogi.ui import MainWindow, ImportDialog
from rogi.project import load_project
from rogi.core import parse_text, fit_dataset
import pytest
import numpy as np


@pytest.mark.parametrize('entry_point', ['ui.py', '__main__.py', 'module'])
def test_application_entry_points(entry_point, tmp_path):
    root = Path(__file__).resolve().parents[1]
    # Run each entry point in isolation; replace only the blocking event loop.
    script = '''
import runpy
import sys
from PySide6 import QtWidgets as W

def check_window(app):
    assert any(isinstance(widget, W.QMainWindow) and widget.isVisible()
               for widget in app.topLevelWidgets())
    print("window opened")
    return 0

W.QApplication.exec = check_window
if sys.argv[1] != 'module':
    runpy.run_path(sys.argv[2], run_name='__main__')
else:
    runpy.run_module('rogi', run_name='__main__')
'''
    result = subprocess.run(
        [sys.executable, '-c', script, entry_point, str(root / 'rogi' / entry_point)],
        cwd=tmp_path if entry_point != 'module' else root,
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert 'window opened' in result.stdout


@pytest.mark.parametrize('control,value', [('style', 'Scatter'), ('y', 'other')])
def test_plot_options_preserve_pending_fit_controls(control, value):
    app = W.QApplication.instance() or W.QApplication([])
    window = MainWindow()
    try:
        dataset = parse_text('x,y,other\n0,1,10\n1,3,20\n2,5,30\n3,7,40\n4,9,50')
        dataset.fit = fit_dataset(dataset, 'Linear', 0, 4)
        window.add_dataset(dataset)
        window.lower.setText('1')
        window.upper.setText('3')
        window.model.setCurrentText('Gaussian')
        getattr(window, control).setCurrentText(value)
        assert window.lower.text() == '1'
        assert window.upper.text() == '3'
        assert window.model.currentText() == 'Gaussian'
        if control == 'y':
            assert 'curve is hidden' in window.result.toPlainText()
    finally:
        window.dirty = False
        window.close()


def test_changing_x_uses_new_column_range():
    app = W.QApplication.instance() or W.QApplication([])
    window = MainWindow()
    try:
        dataset = parse_text('x,y,other\n0,1,10\n1,3,20\n2,5,\n3,7,40\n4,9,50')
        dataset.fit = fit_dataset(dataset, 'Linear', 0, 4)
        window.add_dataset(dataset)
        window.model.setCurrentText('Gaussian')
        window.x.setCurrentText('other')
        assert float(window.lower.text()) == 10
        assert float(window.upper.text()) == 50
        assert window.model.currentText() == 'Gaussian'
        assert dataset.fit['xcol'] == 0
        assert 'curve is hidden' in window.result.toPlainText()
        window.add_dataset(parse_text('x,y\n0,1\n1,2'))
        window.browser.setCurrentRow(0)
        assert float(window.lower.text()) == 10
        assert float(window.upper.text()) == 50
    finally:
        window.dirty = False
        window.close()


def test_axis_channels_plot_and_persist(tmp_path):
    app = W.QApplication.instance() or W.QApplication([])
    window = MainWindow()
    try:
        data = parse_text('Time,Rotator_Theta,Lockin1_X,Lockin1_Y\n0,10,1,3\n1,20,2,4\n2,30,3,5')
        window.add_dataset(data)
        window.x.setCurrentText('Rotator_Theta')
        window.y.setCurrentText('Lockin1_Y')
        np.testing.assert_array_equal(window.ax.lines[0].get_xdata(), [10, 20, 30])
        np.testing.assert_array_equal(window.ax.lines[0].get_ydata(), [3, 4, 5])
        assert window.ax.get_ylabel() == 'Lockin1_Y'
        assert window.resax.get_xlabel() == 'Rotator_Theta'
        window.path = tmp_path / 'channels.h5'
        window.save()
        window.open_project(str(window.path))
        assert window.x.currentText() == 'Rotator_Theta'
        assert window.y.currentText() == 'Lockin1_Y'
        window.ylabel.setText('Custom signal')
        window.redraw()
        assert window.ax.get_ylabel() == 'Custom signal'
    finally:
        window.dirty = False
        window.close()


@pytest.mark.parametrize('fitting', [False, True])
def test_overlay_labels_follow_visible_channels(fitting):
    app = W.QApplication.instance() or W.QApplication([])
    window = MainWindow()
    try:
        window.add_dataset(parse_text('Time,Signal,Angle\n0,1,10\n1,2,20'))
        window.make_copy()
        window.show_fitting.setChecked(fitting)
        x_axis = window.resax if fitting else window.ax
        assert x_axis.get_xlabel() == 'Time'
        assert window.ax.get_ylabel() == 'Signal'

        window.x.setCurrentText('Angle')
        window.y.setCurrentText('Time')
        assert x_axis.get_xlabel() == 'Time, Angle'
        assert window.ax.get_ylabel() == 'Signal, Time'
        assert window.xlabel.placeholderText() == 'Time, Angle'
        assert window.ylabel.placeholderText() == 'Signal, Time'

        window.browser.item(0).setCheckState(Qt.CheckState.Unchecked)
        assert x_axis.get_xlabel() == 'Angle'
        assert window.ax.get_ylabel() == 'Time'
        window.xlabel.setText('Custom X')
        window.ylabel.setText('Custom Y')
        window.labels_changed()
        assert x_axis.get_xlabel() == 'Custom X'
        assert window.ax.get_ylabel() == 'Custom Y'
        window.xlabel.clear()
        window.ylabel.clear()
        window.labels_changed()
        assert x_axis.get_xlabel() == 'Angle'
        assert window.ax.get_ylabel() == 'Time'
        window.browser.item(1).setCheckState(Qt.CheckState.Unchecked)
        assert x_axis.get_xlabel() == 'X'
        assert window.ax.get_ylabel() == 'Y'
    finally:
        window.dirty = False
        window.close()


@pytest.mark.parametrize('extension', ['json', 'h5'])
def test_desktop_workflow(tmp_path, monkeypatch, extension):
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
    for image_extension in ('png', 'svg'):
        window.figure.savefig(tmp_path/f'plot.{image_extension}')
        assert (tmp_path/f'plot.{image_extension}').stat().st_size > 1000
    window.path = tmp_path/f'project.{extension}'
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


def test_spectrum_dat_imports():
    app = W.QApplication.instance() or W.QApplication([])
    paths = sorted((Path(__file__).resolve().parents[1] / 'example-data' / '260813' / 'Spectrum').glob('*.dat'))
    assert paths
    for path in paths:
        dialog = ImportDialog(path)
        try:
            dialog.import_data()
            data = dialog.dataset
            assert data is not None, f'{path.name}: {dialog.message.text()}'
            source = path.read_bytes().decode('utf-8')
            lines = source.split('[Data]', 1)[1].strip().splitlines()
            expected = [[float(value) for value in line.rstrip('\t').split('\t')[1:]]
                        for line in lines[1:] if line.strip()]
            np.testing.assert_array_equal(data.values, expected)
            assert data.source_text == source
            assert 'Time_Timestamp' in data.columns
            assert 'Time' not in data.columns
            assert len(set(data.columns)) == len(data.columns)
            assert all(name == name.strip() for name in data.columns)
            assert dialog.preview.columnCount() == len(data.columns)
        finally:
            dialog.close()


def test_plain_dat_import_still_supports_tabular_data(tmp_path):
    app = W.QApplication.instance() or W.QApplication([])
    path = tmp_path / 'plain.dat'
    path.write_text('Time\tSignal\n0\t1\n1\t2\n')
    dialog = ImportDialog(path)
    try:
        dialog.import_data()
        assert dialog.dataset.columns == ['Time', 'Signal']
        np.testing.assert_array_equal(dialog.dataset.values, [[0, 1], [1, 2]])
    finally:
        dialog.close()


def test_checkbox_clicks_preserve_active_channels_for_later_datasets():
    from PySide6 import QtCore as C, QtTest
    app = W.QApplication.instance() or W.QApplication([])
    window = MainWindow()
    try:
        for number in range(3):
            dataset = parse_text('x,y,other\n1,2,10\n2,3,20', name=f'Run {number}')
            dataset.visible = number == 0
            window.add_dataset(dataset)
        window.browser.setCurrentRow(0, C.QItemSelectionModel.SelectionFlag.ClearAndSelect)
        window.show()
        app.processEvents()
        for row in (1, 2, 0, 1):
            item = window.browser.item(row)
            rect = window.browser.visualRect(window.browser.indexFromItem(item, 0))
            before = window.current()
            checking = item.checkState() == Qt.CheckState.Unchecked
            QtTest.QTest.mouseClick(window.browser.viewport(), Qt.MouseButton.LeftButton,
                                   pos=C.QPoint(rect.left() + 8, rect.center().y()))
            app.processEvents()
            assert window.browser.item(row) is item
            assert window.current() is (window.datasets[row] if checking else before)
            assert window.x.count() == window.y.count() == 3
            # Clicking the label inspects any run, including initially hidden ones.
            QtTest.QTest.mouseClick(window.browser.viewport(), Qt.MouseButton.LeftButton,
                                   pos=rect.center())
            app.processEvents()
            assert window.current() is window.datasets[row]
            window.y.setCurrentText('other')
            assert window.datasets[row].ycol == 2
            assert window.x.count() == window.y.count() == 3
    finally:
        window.dirty = False
        window.close()


def test_channel_change_on_hidden_run_replaces_default_first_plot():
    app = W.QApplication.instance() or W.QApplication([])
    window = MainWindow()
    try:
        for number in range(3):
            dataset = parse_text('x,y,other\n1,2,10\n2,3,20', name=f'Run {number}')
            dataset.visible = number == 0
            window.add_dataset(dataset)
        window.browser.setCurrentRow(1)
        first_channels = (window.datasets[0].xcol, window.datasets[0].ycol)
        window.y.setCurrentText('other')
        assert [d.visible for d in window.datasets] == [False, True, False]
        assert window.ax.get_legend_handles_labels()[1] == ['Run 1']
        assert (window.datasets[0].xcol, window.datasets[0].ycol) == first_channels
        window.history.undo()
        assert [d.visible for d in window.datasets] == [True, False, False]
        window.history.redo()
        assert [d.visible for d in window.datasets] == [False, True, False]
        window.browser.item(0).setCheckState(Qt.CheckState.Checked)
        window.x.setCurrentText('other')
        assert [d.visible for d in window.datasets] == [True, True, False]
        assert window.ax.get_legend_handles_labels()[1] == ['Run 0', 'Run 1']
    finally:
        window.dirty = False
        window.close()


def test_check_later_file_uncheck_first_then_change_channels():
    from PySide6 import QtCore as C, QtTest
    app = W.QApplication.instance() or W.QApplication([])
    window = MainWindow()
    try:
        for number in range(3):
            d = parse_text('x,y,other\n1,2,10\n2,3,20', name=f'Run {number}')
            d.visible = number == 0
            window.add_dataset(d)
        window.browser.setCurrentRow(0, C.QItemSelectionModel.SelectionFlag.ClearAndSelect)
        window.show()
        app.processEvents()
        def click_checkbox(row):
            rect = window.browser.visualRect(window.browser.indexFromItem(window.browser.item(row), 0))
            QtTest.QTest.mouseClick(window.browser.viewport(), Qt.MouseButton.LeftButton,
                                   pos=C.QPoint(rect.left() + 8, rect.center().y()))
            app.processEvents()
        click_checkbox(1)
        click_checkbox(0)
        assert window.current() is window.datasets[1]
        assert window.info.text().startswith('Run 1\n')
        for channel in ('other', 'x', 'y', 'other'):
            window.y.setCurrentText(channel)
            assert window.current() is window.datasets[1]
            assert [d.visible for d in window.datasets] == [False, True, False]
            assert window.datasets[0].ycol == 1
            assert window.ax.get_legend_handles_labels()[1] == ['Run 1']
        click_checkbox(2)
        click_checkbox(1)
        window.x.setCurrentText('other')
        assert window.current() is window.datasets[2]
        assert [d.visible for d in window.datasets] == [False, False, True]
        assert window.datasets[0].xcol == 0
    finally:
        window.dirty = False
        window.close()
