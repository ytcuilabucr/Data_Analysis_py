import json
import numpy as np
import pytest
from PySide6 import QtWidgets as W
from rogi.core import Dataset, parse_text
from rogi.analysis import analyze, analyze_many
from rogi.project import save_project, load_project
from rogi.units import (infer_unit, base_name, axis_label, normalize_unit, conversion_factor,
                        custom_label, converted_copy, display_unit)


@pytest.mark.parametrize('name,unit,base', [
    ('Current (A)', 'A', 'Current'), ('Z (forward) (m)', 'm', 'Z (forward)'),
    ('Z (forward)', '', 'Z (forward)'), ('Height (Retrace)', '', 'Height (Retrace)'),
    ('Result ((V)/(s))', '(V)/(s)', 'Result'), ('Bias (um)', 'µm', 'Bias'), ('Time', '', 'Time')])
def test_infer_unit_and_base_name(name, unit, base):
    assert infer_unit(name) == unit
    assert base_name(name) == base


def test_label_format():
    assert axis_label('Current (A)', 'A') == 'Current (A)'
    assert axis_label('Current (A)', 'nA') == 'Current (nA)'
    assert axis_label('Time', '') == 'Time'
    assert axis_label('Time', '', 'unknown unit') == 'Time (unknown unit)'
    assert axis_label('Result (1)', '1') == 'Result (dimensionless)'
    assert display_unit('(V)/(s)') == 'V/s'


@pytest.mark.parametrize('text,unit', [('um', 'µm'), (' uA ', 'µA'), ('μm', 'µm'), ('kOhm', 'kΩ'),
                                       ('ohm', 'Ω'), ('counts', 'counts'), ('used', 'used')])
def test_normalize(text, unit):
    assert normalize_unit(text) == unit


def test_conversion_factors_are_exact_powers_of_ten():
    assert conversion_factor('nA', 'pA') == 1000
    assert conversion_factor('um', 'nm') == 1000
    assert conversion_factor('A/V', 'nA/V') == 1e9
    assert conversion_factor('(V)/(s)', '(mV)/(ms)') == 1
    assert conversion_factor('mm', 'm') == 1e-3
    for source, target in [('V', 'A'), ('', 'V'), ('raw counts', 'counts'), ('1', 'm')]:
        with pytest.raises(ValueError, match='SI prefix'):
            conversion_factor(source, target)


def test_custom_label_keeps_single_unit():
    assert custom_label('Tunnel current', ['nA', 'nA']) == 'Tunnel current (nA)'
    assert custom_label('Potential (V)', ['V']) == 'Potential (V)'
    assert custom_label('Mixed', ['A', 'nA']) == 'Mixed'
    assert custom_label('Unknown', ['', '']) == 'Unknown'


def test_dataset_stores_units_once():
    d = parse_text('Time (s),Signal (mV),Count\n0,1,2\n1,2,3')
    assert d.column_units == ['s', 'mV', '']
    assert Dataset('x', ['a', 'b'], [[1, 2]], column_units=['um', ' V']).column_units == ['µm', 'V']


def test_legacy_project_gains_units(tmp_path):
    path = tmp_path / 'old.json'
    save_project(path, [parse_text('Time (s),Signal (V)\n0,1\n1,2')], {})
    content = json.loads(path.read_text())
    del content['datasets'][0]['column_units']
    path.write_text(json.dumps(content))
    assert load_project(path)[0][0].column_units == ['s', 'V']


def test_nanonis_direction_is_not_a_unit():
    from tests.test_nanonis import scan_bytes
    from rogi.spm import parse_spm
    from rogi.scanfile import bundle_channels, channel_views
    ds = parse_spm(scan_bytes())
    assert [d.column_units[3] for d in ds] == ['m', 'm', 'A']
    bundle = bundle_channels(ds)
    assert [v.column_units[3] for v in channel_views(bundle)] == ['m', 'm', 'A']


def test_converted_copy_rescales_and_renames():
    d = Dataset('b', ['Time (s)', 'Signal (mV)'], [[0, 1000.], [1, 2000.]])
    copy = converted_copy(d, ['s', 'V'])
    np.testing.assert_allclose(copy.values[:, 1], [1, 2])
    assert copy.columns == ['Time (s)', 'Signal (V)'] and copy.column_units == ['s', 'V']
    assert copy.parent == d.id and not copy.raw and d.column_units == ['s', 'mV']
    np.testing.assert_array_equal(d.values[:, 1], [1000, 2000])
    a = Dataset('a', ['Time (s)', 'Signal (V)'], [[0, 3.], [1, 4.]])
    mean, = analyze_many([a, copy])
    np.testing.assert_allclose(mean.values[:, 1], [2, 3])
    with pytest.raises(ValueError, match='Edit units'):
        analyze_many([a, d])
    with pytest.raises(ValueError, match='SI prefix'):
        converted_copy(d, ['s', 'A'])
    with pytest.raises(ValueError, match='at least one'):
        converted_copy(d, ['s', 'mV'])


def test_derivative_label():
    d = Dataset('s', ['Time (s)', 'Signal (V)'], [[0, 1.], [1, 3.], [2, 5.]])
    r = analyze(d, [dict(operation='differentiate', parameters={})])
    assert axis_label(r.columns[1], r.column_units[1]) == 'Result (V/s)'


@pytest.fixture
def window():
    from rogi.ui import MainWindow
    window = MainWindow()
    yield window
    window.dirty = False
    window.close()


def test_plot_labels_follow_stored_units(window):
    d = parse_text('Time (s),Current (A)\n0,1\n1,2')
    window.add_dataset(d)
    assert window.ax.get_ylabel() == 'Current (A)'
    d.column_units = ['s', 'nA']
    window.redraw()
    assert window.ax.get_ylabel() == 'Current (nA)' and window.resax.get_xlabel() == 'Time (s)'
    window.ylabel.setText('Tunnel current')
    window.labels_changed()
    assert window.ax.get_ylabel() == 'Tunnel current (nA)'
    other = parse_text('Time (s),Current (A)\n0,3\n1,4')
    window.add_dataset(other)
    window.ylabel.setText('')
    window.labels_changed()
    assert window.ax.get_ylabel() == 'Current (nA), Current (A)'
    assert 'Mixed units' in window.log_notice.text() and 'Y: nA, A' in window.log_notice.text()


def test_unit_editor_relabels_with_undo_and_converts(window, monkeypatch):
    from rogi import dialogs
    d = parse_text('Time (s),Current (A)\n0,1\n1,2')
    window.add_dataset(d)
    monkeypatch.setattr(window, 'selected_datasets', lambda: [d])
    choice = {}

    def run(dialog):
        dialog.table.item(1, 2).setText(choice['unit'])
        dialog.convert.setChecked(choice['convert'])
        return W.QDialog.DialogCode.Accepted if dialog.buttons.button(
            W.QDialogButtonBox.StandardButton.Ok).isEnabled() else W.QDialog.DialogCode.Rejected
    monkeypatch.setattr(dialogs.UnitsDialog, 'exec', run)
    choice.update(unit='nA', convert=False)
    window.edit_units()
    assert d.column_units == ['s', 'nA'] and d.values[0, 1] == 1 and d.raw
    window.history.undo()
    assert d.column_units == ['s', 'A']
    choice.update(unit='mA', convert=True)
    window.edit_units()
    copy = window.datasets[-1]
    assert copy.parent == d.id and copy.column_units == ['s', 'mA'] and copy.columns[1] == 'Current (mA)'
    np.testing.assert_allclose(copy.values[:, 1], [1000, 2000])
    count = len(window.datasets)
    choice.update(unit='V', convert=True)
    window.edit_units()
    assert len(window.datasets) == count
