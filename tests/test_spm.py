import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('MPLCONFIGDIR', '/tmp/rogi-matplotlib-tests')

import numpy as np
import pytest
from PySide6 import QtWidgets as W, QtCore as C

from rogi.spm import parse_spm
from rogi.project import convert_folder, save_project, load_project
from rogi.ui import SpmImportDialog, MainWindow


def spm_bytes(size=2):
    header = ('\\*File list\r\n\\Version: 0x09100000\r\n'
              '\\*Ciao scan list\r\n\\Scan size: 10 10 um\r\n')
    signals = [[-32768, -1, 0, 32767], [12, 3, -4, 5]]
    for i, label in enumerate(['Height', 'Deflection']):
        header += (f'\\*Ciao image list\r\n\\Data offset: {4096+i*4*size}\r\n'
                   f'\\Data length: {4*size}\r\n\\Bytes/pixel: {size}\r\n'
                   '\\Samps/line: 2\r\n\\Number of lines: 2\r\n'
                   f'\\@2:Image Data: S [Channel] "{label}"\r\n'
                   '\\@2:Z scale: V [Sens. Zsens] (0.1 V/LSB) 10 V\r\n')
    header += '\\*File list end\r\n\x1a'
    return header.encode('latin-1').ljust(4096, b'\0') + np.array(signals, dtype=f'<i{size}').tobytes()


@pytest.mark.parametrize('size', [2, 4])
def test_signed_channels_and_coordinates(size):
    datasets = parse_spm(spm_bytes(size), name='scan', source='scan.spm')
    assert len(datasets) == 2
    d = datasets[0]
    assert d.name == 'scan — 1: Height'
    assert d.columns == ['Sample', 'X pixel', 'Y pixel', 'Height (raw counts)']
    np.testing.assert_array_equal(d.values, [[0, 0, 0, -32768], [1, 1, 0, -1],
                                           [2, 0, 1, 0], [3, 1, 1, 32767]])
    assert d.ycol == 3 and d.raw and not d.values.flags.writeable
    assert d.instrument_metadata['format'] == 'nanoscope'
    assert '@2:Z scale' in d.source_text
    assert d.derived().instrument_metadata == d.instrument_metadata


@pytest.mark.parametrize('extension', ['.json', '.h5'])
def test_spm_project_roundtrip(tmp_path, extension):
    datasets = parse_spm(spm_bytes())
    path = tmp_path / ('project' + extension)
    save_project(path, datasets, {})
    restored, _ = load_project(path)
    for actual, expected in zip(restored, datasets):
        np.testing.assert_array_equal(actual.values, expected.values)
        assert actual.source_text == expected.source_text
        assert actual.instrument_metadata == expected.instrument_metadata
        assert actual.ycol == 3


@pytest.mark.parametrize('data,message', [
    (b'other vendor', 'Unsupported SPM format'),
    (b'\\*File list', 'Incomplete SPM header'),
    (spm_bytes()[:-1], 'truncated'),
    (spm_bytes().replace(b'Samps/line: 2', b'Samps/line: 3'), 'dimensions'),
    (spm_bytes().replace(b'Bytes/pixel: 2', b'Bytes/pixel: 8'), '16-bit'),
    (spm_bytes().replace(b'Data offset: 4104', b'Data offset: 4096'), 'overlapping'),
    (spm_bytes().replace(b'Ciao scan list', b'Ciao force image list'), 'force'),
])
def test_bad_spm(data, message):
    with pytest.raises(ValueError, match=message):
        parse_spm(data)


def test_folder_conversion_atomic(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'scan.SPM').write_bytes(spm_bytes())
    output = tmp_path / 'project.h5'
    assert convert_folder(source, output) == 1
    datasets, _ = load_project(output)
    assert [d.visible for d in datasets] == [True]
    assert len(datasets[0].instrument_metadata['channels']) == 2
    original = output.read_bytes()
    (source / 'broken.spm').write_bytes(spm_bytes()[:-1])
    with pytest.raises(ValueError, match='broken.spm'):
        convert_folder(source, output)
    assert output.read_bytes() == original


def test_preview_selection(tmp_path):
    app = W.QApplication.instance() or W.QApplication([])
    path = tmp_path / 'scan.spm'
    path.write_bytes(spm_bytes())
    dialog = SpmImportDialog(path)
    try:
        assert dialog.preview.rowCount() == 4
        assert dialog.preview.item(0, 3).text() == '-32768'
        for i in range(2):
            dialog.channel_list.item(i).setCheckState(C.Qt.CheckState.Unchecked)
        dialog.import_data()
        assert dialog.result() == 0 and not dialog.datasets
        dialog.channel_list.item(1).setCheckState(C.Qt.CheckState.Checked)
        dialog.channel_list.setCurrentRow(1)
        assert dialog.preview.item(0, 3).text() == '12'
        dialog.import_data()
        assert dialog.result() == W.QDialog.DialogCode.Accepted
        assert len(dialog.datasets) == 1
        assert dialog.datasets[0].name == 'scan'
        assert 'Deflection' in dialog.datasets[0].columns[-1]
    finally:
        dialog.close()


def test_import_action(tmp_path, monkeypatch):
    app = W.QApplication.instance() or W.QApplication([])
    path = tmp_path / 'scan.SPM'
    path.write_bytes(spm_bytes())
    monkeypatch.setattr(W.QFileDialog, 'getOpenFileNames', lambda *a: ([str(path)], ''))
    def accept(dialog):
        dialog.import_data()
        return dialog.result()
    monkeypatch.setattr(SpmImportDialog, 'exec', accept)
    window = MainWindow()
    try:
        window.open_files()
        assert len(window.datasets) == 1
        assert window.browser.count() == 1
        assert len(window.datasets[0].instrument_metadata['channels']) == 2
        window.history.undo()
        assert len(window.datasets) == 0
    finally:
        window.dirty = False
        window.close()


def test_nanoscope_92_uses_32bit_despite_header():
    data = spm_bytes(4).replace(b'0x09100000', b'0x09300201').replace(b'Bytes/pixel: 4', b'Bytes/pixel: 2')
    datasets = parse_spm(data)
    np.testing.assert_array_equal(datasets[0].values[:, 3], [-32768, -1, 0, 32767])


def test_force_segments():
    data = spm_bytes().replace(b'\\*File list\r', b'\\*Force file list\r')
    data = data.replace(b'Ciao image list', b'Ciao force image list')
    data = data.replace(b'Samps/line: 2', b'Samps/line: 1 3').replace(b'@2:Image Data', b'@4:Image Data')
    header = data[:data.index(b'\x1a') + 1]
    data = header.ljust(4096, b'\0') + spm_bytes()[4096:]
    d = parse_spm(data)[0]
    assert d.columns[1:3] == ['Segment', 'Sample in segment']
    np.testing.assert_array_equal(d.values[:, 1:3], [[0, 0], [1, 0], [1, 1], [1, 2]])
    np.testing.assert_array_equal(d.values[:, 3], [-32768, -1, 0, 32767])
