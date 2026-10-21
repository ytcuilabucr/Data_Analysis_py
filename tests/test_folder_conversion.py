from pathlib import Path
import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('MPLCONFIGDIR', '/tmp/rogi-matplotlib-tests')

import numpy as np
import pytest
from PySide6 import QtWidgets as W, QtCore as C
from PySide6.QtCore import Qt

from rogi.project import convert_folder, load_project
from rogi.ui import MainWindow


def test_folder_conversion_round_trip(tmp_path):
    source = tmp_path / 'inputs'
    source.mkdir()
    (source / 'a.csv').write_text('x,y\n1,2\n3,4\n')
    (source / 'b.DAT').write_text('[Instrument]\n[Data]\nTime\tTime_Timestamp\tSignal\t\n'
                                '2026/01/01_00:00:00\t10\t20\n')
    (source / 'c.txt').write_text('x;y\n5;6\n')
    (source / 'ignore.bin').write_bytes(b'\xff')
    (source / 'subfolder').mkdir()
    output = tmp_path / 'converted.h5'
    assert convert_folder(source, output) == 3
    datasets, settings = load_project(output)
    assert [d.name for d in datasets] == ['a', 'b', 'c']
    assert [d.visible for d in datasets] == [True, False, False]
    np.testing.assert_array_equal(datasets[0].values, [[1, 2], [3, 4]])
    np.testing.assert_array_equal(datasets[1].values, [[10, 20]])
    np.testing.assert_array_equal(datasets[2].values, [[5, 6]])
    assert datasets[1].source_text == (source / 'b.DAT').read_text()
    assert settings['title'] == 'inputs'
    original = output.read_bytes()
    (source / 'broken.tsv').write_text('x\ty\n1\tnot-a-number')
    with pytest.raises(ValueError, match='broken.tsv'):
        convert_folder(source, output)
    assert output.read_bytes() == original


def test_empty_folder_conversion(tmp_path):
    with pytest.raises(ValueError, match='No CSV'):
        convert_folder(tmp_path, tmp_path / 'empty.h5')
    assert not (tmp_path / 'empty.h5').exists()


def test_spectrum_folder_conversion(tmp_path):
    folder = Path(__file__).resolve().parents[1] / 'example-data' / '260813' / 'Spectrum'
    output = tmp_path / 'spectrum.h5'
    assert convert_folder(folder, output) == len(list(folder.glob('*.dat')))
    datasets, _ = load_project(output)
    assert len(datasets) == 48
    assert all('Time_Timestamp' in d.columns for d in datasets)
    for dataset, path in zip(datasets, sorted(folder.glob('*.dat')), strict=True):
        text = path.read_bytes().decode('utf-8')
        lines = text.split('[Data]', 1)[1].strip().splitlines()
        expected = [[float(value) for value in line.rstrip('\t').split('\t')[1:]]
                    for line in lines[1:] if line.strip()]
        np.testing.assert_array_equal(dataset.values, expected)
        assert dataset.source_text == text
        assert len(set(dataset.columns)) == len(dataset.columns)


@pytest.mark.parametrize('time_value,expected_columns,expected_values', [
    ('2026/01/01_00:00:00', ['Signal', 'Time_Timestamp', 'Signal [2]'], [[1, 10, np.nan]]),
    ('2', ['Signal', 'Time', 'Time_Timestamp', 'Signal [2]'], [[1, 2, 10, np.nan]]),
])
def test_dat_conversion_varied_headers(tmp_path, time_value, expected_columns, expected_values):
    folder = tmp_path / 'input'
    folder.mkdir()
    text = ('[Different instrument]\nArbitrary metadata: value\n\n[Data]\n\n'
            'Signal \tTime\t Time_Timestamp \tSignal\t\n'
            f'1\t{time_value}\t10\t\t\n\n')
    (folder / 'measurement.dat').write_text(text)
    output = tmp_path / 'output.h5'
    assert convert_folder(folder, output) == 1
    datasets, _ = load_project(output)
    assert datasets[0].columns == expected_columns
    np.testing.assert_array_equal(datasets[0].values, expected_values)
    assert datasets[0].source_text == text


def test_folder_picker_workflow(tmp_path, monkeypatch):
    app = W.QApplication.instance() or W.QApplication([])
    source = tmp_path / 'inputs'
    source.mkdir()
    (source / 'data.tsv').write_text('x\ty\n1\t2\n')
    monkeypatch.setattr(W.QFileDialog, 'getExistingDirectory', lambda *a: str(source))
    monkeypatch.setattr(W.QFileDialog, 'getSaveFileName', lambda *a: (str(tmp_path / 'result'), ''))
    messages = []
    monkeypatch.setattr(W.QMessageBox, 'information', lambda *a: messages.append(a[-1]))
    window = MainWindow()
    try:
        window.convert_folder()
        datasets, _ = load_project(tmp_path / 'result.h5')
        assert datasets[0].name == 'data'
        assert 'Created and opened 1 dataset' in window.statusBar().currentMessage()
        assert window.datasets[0].name == 'data'
        assert window.path == tmp_path / 'result.h5'
        assert not window.dirty
        monkeypatch.setattr(W.QFileDialog, 'getExistingDirectory', lambda *a: '')
        window.convert_folder()
        assert not messages
    finally:
        window.dirty = False
        window.close()


def test_converted_spectrum_channel_changes_update_plot(tmp_path):
    app = W.QApplication.instance() or W.QApplication([])
    folder = Path(__file__).resolve().parents[1] / 'example-data' / '260813' / 'Spectrum'
    output = tmp_path / 'spectrum.h5'
    convert_folder(folder, output)
    window = MainWindow()
    try:
        window.open_project(str(output))
        assert window.current() is window.datasets[0]
        assert window.current().visible
        # Reproduce the screenshot: edit IV15 while only Sweeptheta14 is plotted.
        sweep = next(i for i, d in enumerate(window.datasets) if d.name.startswith('Sweeptheta14'))
        window.browser.item(0).setCheckState(Qt.CheckState.Unchecked)
        window.browser.item(sweep).setCheckState(Qt.CheckState.Checked)
        assert [line.get_label() for line in window.ax.lines
                if not line.get_label().startswith('_')] == [window.datasets[sweep].name]
        window.browser.setCurrentRow(0, C.QItemSelectionModel.SelectionFlag.ClearAndSelect)
        window.x.setCurrentText('Rotator_Theta')
        window.y.setCurrentText('Lockin1_X')
        edited = window.current()
        assert edited.visible
        assert window.browser.currentItem().checkState() == Qt.CheckState.Checked
        assert not window.datasets[sweep].visible
        line = next(line for line in window.ax.lines if line.get_label() == edited.name)
        np.testing.assert_array_equal(line.get_xdata(), edited.values[:, edited.columns.index('Rotator_Theta')])
        np.testing.assert_array_equal(line.get_ydata(), edited.values[:, edited.columns.index('Lockin1_X')])
        assert 'Rotator_Theta' in window.ax.get_xlabel()
        assert 'Lockin1_X' in window.ax.get_ylabel()
        window.save()
        window.open_project(str(output))
        assert window.x.currentText() == 'Rotator_Theta'
        assert window.y.currentText() == 'Lockin1_X'
    finally:
        window.dirty = False
        window.close()


def test_all_converted_lockin_channels_available_in_browser(tmp_path):
    app = W.QApplication.instance() or W.QApplication([])
    folder = Path(__file__).resolve().parents[1] / 'example-data' / '260813' / 'Spectrum'
    output = tmp_path / 'spectrum.h5'
    convert_folder(folder, output)
    window = MainWindow()
    try:
        window.open_project(str(output))
        lockin_files = 0
        for row, path in enumerate(sorted(folder.glob('*.dat'))):
            header = path.read_text().split('[Data]', 1)[1].strip().splitlines()[0]
            expected = [c.strip() for c in header.split('\t') if 'Lockin' in c]
            window.browser.setCurrentRow(row, C.QItemSelectionModel.SelectionFlag.ClearAndSelect)
            dataset = window.current()
            assert dataset.name == path.stem
            assert [c for c in dataset.columns if 'Lockin' in c] == expected
            for combo in (window.x, window.y):
                assert [combo.itemText(i) for i in range(combo.count())] == dataset.columns
            if expected:
                lockin_files += 1
                # Exercise a nondefault lock-in signal, not just presence in storage.
                window.y.setCurrentText('Lockin1_R')
                line = next(line for line in window.ax.lines if line.get_label() == dataset.name)
                np.testing.assert_array_equal(line.get_ydata(), dataset.values[:, dataset.columns.index('Lockin1_R')])
        assert lockin_files == 38
    finally:
        window.dirty = False
        window.close()


@pytest.mark.parametrize('numeric_time', [True, False])
def test_spectrum_helper_preserves_channels(tmp_path, monkeypatch, numeric_time):
    from scripts import prepare_spectrum

    folder = tmp_path / 'example-data' / 'Spectrum'
    folder.mkdir(parents=True)
    header = ('Time\tTime_Timestamp\tRotator_Theta\tLockin1_X\tLockin1_X\tLockin1_Y\tLockin1_R\tLockin1_Theta'
              if numeric_time else
              'Rotator_Theta\tTime\tTime_Timestamp\tLockin1_X\tLockin1_X\tLockin1_Y\tLockin1_R\tLockin1_Theta')
    row = '1\t2\t3\t4\tNA\t6\t7\t8' if numeric_time else '3\t2026/01/01_00:00:00\t2\t4\tNA\t6\t7\t8'
    text = f'\ufeff[Data]\r\n{header}\r\n{row}\r\n'
    (folder / 'Sweep.dat').write_bytes(text.encode('utf-8'))
    output = tmp_path / 'converted.h5'
    monkeypatch.setattr(prepare_spectrum, 'ROOT', tmp_path)
    monkeypatch.setattr(prepare_spectrum, 'OUTPUT', output)
    assert prepare_spectrum.convert() == (1, 1)
    raw, editable = load_project(output)[0]
    expected = [[1, 2, 3, 4, np.nan, 6, 7, 8]] if numeric_time else [[3, 2, 4, np.nan, 6, 7, 8]]
    np.testing.assert_array_equal(raw.values, expected)
    np.testing.assert_array_equal(editable.values, expected)
    assert raw.columns[-5:] == ['Lockin1_X', 'Lockin1_X [2]', 'Lockin1_Y', 'Lockin1_R', 'Lockin1_Theta']
    assert raw.source_text == text
    assert raw.source == 'Spectrum/Sweep.dat'
    assert not raw.values.flags.writeable
    assert editable.parent == raw.id
    before = output.read_bytes()
    with pytest.raises(FileExistsError):
        prepare_spectrum.convert()
    assert output.read_bytes() == before


def test_recursive_conversion_groups_and_atomic_failure(tmp_path):
    from test_spm import spm_bytes
    from test_nanonis import scan_bytes
    source = tmp_path / 'collection'
    for name in ('Spectrum', 'spm/day2', 'sxm'):
        (source / name).mkdir(parents=True)
    (source / 'root.csv').write_text('x,y\n0,1\n')
    (source / 'Spectrum' / 'same.dat').write_text('x\ty\n0\t2\n')
    (source / 'spm/day2' / 'same.SPM').write_bytes(spm_bytes())
    (source / 'sxm' / 'same.sxm').write_bytes(scan_bytes())
    (source / 'spm' / 'Experiment.pxp').write_bytes(b'unsupported')
    output = source / 'combined.h5'
    assert convert_folder(source, output) == 4
    datasets, settings = load_project(output)
    from collections import Counter
    assert Counter(d.group for d in datasets) == {'': 1, 'Spectrum': 1, 'spm/day2': 1, 'sxm': 1}
    assert len({d.id for d in datasets}) == 4
    assert sum(d.visible for d in datasets) == 1 and datasets[0].visible
    assert settings['title'] == 'collection'
    for d in datasets:
        assert Path(d.source).is_file()
        assert d.source_text
    assert convert_folder(source, output) == 4  # Existing output is not an input.
    previous = output.read_bytes()
    (source / 'spm/day2' / 'broken.dat').write_text('x\ty\n1\tbad\n')
    with pytest.raises(ValueError, match='spm/day2/broken.dat'):
        convert_folder(source, output)
    assert output.read_bytes() == previous


def test_recursive_conversion_does_not_follow_directory_symlinks(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'data.csv').write_text('x,y\n0,1\n')
    (source / 'loop').symlink_to(source, target_is_directory=True)
    assert convert_folder(source, tmp_path / 'output.h5') == 1
