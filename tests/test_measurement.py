import json
import h5py
import numpy as np
import pytest
from PySide6 import QtWidgets as W
from rogi.dialogs import ImportDialog
from rogi.files import file_kind, is_project, is_data_file, scan_folder, file_preview, read_datasets
from rogi.measurement import is_measurement, load_measurement
from rogi.project import convert_folder, load_project, save_project
from rogi.ui import MainWindow

WAVELENGTH = 'YSL AOTF - 1.wavelength'
POWER = 'YSL AOTF - 1.power'
METER = 'Agilent 34410A - 2'


def measurement(path, powers=None, wavelengths=(430.0, 432.0, 434.0), status='success', fill=None):
    """A stepped-measurement file: wavelength only, or power (outer) x wavelength."""
    axes = ([(POWER, list(powers))] if powers else []) + [(WAVELENGTH, list(wavelengths))]
    shape = tuple(len(points) for _, points in axes)
    signal = np.arange(np.prod(shape), dtype=float).reshape(shape) / 10 if fill is None else fill
    with h5py.File(path, 'w') as file:
        file.attrs.update(mode='stepped', schema_version=1, status=status, reason='', uid='abc')
        data = file.create_group('data')
        data.create_dataset(METER, data=signal).attrs.update(label=METER, units='V')
        data['seq'] = np.arange(signal.size).reshape(shape)
        data['timestamp'] = 1.7e9 + np.arange(signal.size, dtype=float).reshape(shape)
        setpoints = file.create_group('setpoints')
        for name, points in axes:
            setpoints[name] = np.array(points)
        plan = dict(axes=[dict(device=name, points=points, settle_s=0.5, snake=False) for name, points in axes],
                    mode='stepped', shape=list(shape))
        file.create_group('plan').attrs.update(plan_json=json.dumps(plan), axis_names=[n for n, _ in axes])
        file.create_group('snapshot').attrs['YSL AOTF - 1'] = json.dumps(dict(power=100.0))
        file.create_group('provenance').attrs['name'] = path.stem
    return path


@pytest.fixture
def window():
    window = MainWindow()
    yield window
    window.dirty = False
    window.close()


def test_wavelength_only_scan_is_one_spectrum(tmp_path):
    path = measurement(tmp_path / 'single.h5')
    [dataset] = load_measurement(path)
    assert dataset.name == 'single'
    assert dataset.columns == [WAVELENGTH, METER, 'timestamp', 'seq']
    assert dataset.column_units == ['nm', 'V', 's', '']
    assert dataset.values[:, 0].tolist() == [430, 432, 434]
    assert dataset.values[:, 1].tolist() == [0, 0.1, 0.2]
    assert dataset.raw and not dataset.values.flags.writeable
    assert json.loads(dataset.source_text)['snapshot']['YSL AOTF - 1'] == '{"power": 100.0}'


def test_outer_sweep_gives_one_spectrum_per_setpoint(tmp_path):
    datasets = load_measurement(measurement(tmp_path / 'sweep.h5', powers=(10, 30, 100)))
    assert [d.name for d in datasets] == [f'sweep, {POWER} = {p}' for p in (10, 30, 100)]
    assert datasets[1].values[:, 1].tolist() == pytest.approx([0.3, 0.4, 0.5])
    assert datasets[2].values[:, 3].tolist() == [6, 7, 8]


def test_unmeasured_setpoints_of_an_aborted_scan_are_skipped(tmp_path):
    signal = np.full((2, 3), np.nan)
    signal[0, :2] = 1.0
    datasets = load_measurement(measurement(tmp_path / 'stop.h5', powers=(10, 30), status='aborted', fill=signal))
    assert [d.name for d in datasets] == [f'stop, {POWER} = 10']
    assert np.isnan(datasets[0].values[2, 1]) and 'aborted' in datasets[0].comments


def test_measurements_are_data_files_not_projects(tmp_path):
    scan = measurement(tmp_path / 'scan.h5')
    project = tmp_path / 'project.h5'
    save_project(project, load_measurement(scan), {'title': 'P'})
    (tmp_path / 'other.h5').write_bytes(b'not hdf5')
    assert is_measurement(scan) and not is_measurement(project)
    assert file_kind(scan) == 'measurement' and file_kind(project) == 'project'
    assert is_data_file(scan) and not is_project(scan) and is_project(project)
    assert [p.name for p in scan_folder(tmp_path, ['measurement'])] == ['scan.h5']
    assert [p.name for p in scan_folder(tmp_path, ['project'])] == ['other.h5', 'project.h5']
    assert 'Measurement HDF5 · 3 wavelength' in file_preview(scan)[0]


def test_bad_measurements_raise_value_errors(tmp_path):
    path = measurement(tmp_path / 'bad.h5')
    with h5py.File(path, 'a') as file:
        del file['setpoints'][WAVELENGTH]
    with pytest.raises(ValueError, match='Missing setpoints'):
        load_measurement(path)
    with h5py.File(path, 'a') as file:
        file['plan'].attrs['plan_json'] = '{"axes": [{"points": []}]}'
    with pytest.raises(ValueError, match='Unreadable measurement plan'):
        read_datasets(path)


def test_folder_conversion_includes_measurements(tmp_path):
    folder = tmp_path / 'data'
    folder.mkdir()
    measurement(folder / 'a.h5', powers=(10, 30))
    measurement(folder / 'b.h5')
    destination = tmp_path / 'out.h5'
    assert convert_folder(folder, destination) == 3
    assert [d.name for d in load_project(destination)[0]] == [f'a, {POWER} = 10', f'a, {POWER} = 30', 'b']


def test_window_loads_measurements_into_open_project(window, tmp_path, monkeypatch):
    two = measurement(tmp_path / 'two.h5', powers=(10, 30))
    one = measurement(tmp_path / 'one.h5')
    table = tmp_path / 't.csv'
    table.write_text('x,y\n1,2\n')
    def choose(dialog):
        dialog.import_data()
        return dialog.result()
    monkeypatch.setattr(ImportDialog, 'exec', choose)
    monkeypatch.setattr(W.QMessageBox, 'warning', lambda *a: pytest.fail(a[-1]))
    # Open… previews; only the table has columns to choose.
    window.open_files([str(two), str(one), str(table)])
    names = [d.name for d in window.datasets]
    # The previewed file comes first, as for other imports.
    assert names == ['t', 'one', f'two, {POWER} = 10', f'two, {POWER} = 30']
    window.import_paths([two], name_pattern='{stem}_{n}', start=5, grouping='root')
    assert [d.name for d in window.datasets][-2:] == [f'two_5, {POWER} = 10', f'two_6, {POWER} = 30']
