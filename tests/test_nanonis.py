import numpy as np
import pytest
from rogi.spm import parse_spm
from rogi.project import convert_folder, load_project


def scan_bytes(endian='MSBFIRST'):
    header = (':NANONIS_VERSION:\n2\n:SCANIT_TYPE:\nFLOAT ' + endian + '\n'
              ':SCAN_PIXELS:\n3 2\n:DATA_INFO:\n'
              'Channel\tName\tUnit\tDirection\tCalibration\tOffset\n'
              '0\tZ\tm\tboth\t1\t0\n'
              '1\tCurrent\tA\tforward\t1\t0\n:SCANIT_END:\n\n').encode()
    data = np.arange(18, dtype=float).reshape(3, 6)
    data[0, 1] = np.nan
    return header + b'\x1a\x04' + data.astype('>f4' if endian == 'MSBFIRST' else '<f4').tobytes()


@pytest.mark.parametrize('endian', ['MSBFIRST', 'LSBFIRST'])
def test_nanonis_channels_units_and_pixels(endian):
    ds = parse_spm(scan_bytes(endian))
    assert len(ds) == 3
    assert ds[0].columns[-1] == 'Z (forward) (m)'
    assert ds[1].columns[-1] == 'Z (backward) (m)'
    assert ds[2].columns[-1] == 'Current (forward) (A)'
    np.testing.assert_array_equal(ds[1].values[:, 3], np.arange(6, 12))
    np.testing.assert_array_equal(ds[0].values[:, 1:3], [[0,0], [1,0], [2,0], [0,1], [1,1], [2,1]])
    assert np.isnan(ds[0].values[1, 3])
    assert ds[0].instrument_metadata['format'] == 'nanonis_sxm'


@pytest.mark.parametrize('suffix', ['.sxm', '.spm'])
def test_nanonis_folder_and_project(tmp_path, suffix):
    folder = tmp_path / 'input'
    folder.mkdir()
    (folder / ('scan' + suffix)).write_bytes(scan_bytes())
    output = tmp_path / 'scan.h5'
    assert convert_folder(folder, output) == 1
    ds, _ = load_project(output)
    assert len(ds) == 1
    assert len(ds[0].instrument_metadata['channels']) == 3
    assert ds[0].source_text.startswith(':NANONIS_VERSION:')
    assert ds[0].instrument_metadata['format'] == 'nanonis_sxm'


@pytest.mark.parametrize('data,message', [
    (scan_bytes()[:-1], 'data length'),
    (scan_bytes().replace(b'3 2', b'0 2'), 'dimensions'),
    (scan_bytes().replace(b'both', b'nope'), 'direction'),
    (scan_bytes().replace(b'FLOAT', b'INT32'), 'FLOAT'),
    (scan_bytes().replace(b'\x1a\x04', b'xx'), 'marker'),
    (scan_bytes().replace(b':SCANIT_END:', b':NO_END:'), 'SCANIT_END'),
])
def test_invalid_nanonis(data, message):
    with pytest.raises(ValueError, match=message):
        parse_spm(data)
