from pathlib import Path
import numpy as np
import pytest
from rogi.core import Dataset
from rogi.analysis import analyze
from rogi.calibration import responsivity, DETECTORS
from rogi.presets import make_preset, apply_preset, save_presets, load_presets
from rogi.project import save_project, load_project

AOTF = Path(__file__).parents[1] / 'example-data' / 'AOTF.h5'


def step(**params):
    return dict(operation='photodiode_power',
                parameters=dict(dict(detector='newport_2107', gain_setting=1.0, dark_v=0.0), **params))


def scan(wavelength=(300., 425., 900., 1050., 1100., np.nan), volts=(.1, .2, .5, .3, .4, .1)):
    return Dataset('scan', ['YSL AOTF - 1.wavelength', 'Agilent 34410A - 2'],
                   np.column_stack((wavelength, volts)), column_units=['nm', 'V'])


def test_responsivity_interpolates_and_never_extrapolates():
    curve = DETECTORS['newport_2107']
    np.testing.assert_allclose(responsivity('newport_2107', curve['wavelength_nm']), curve['responsivity_a_per_w'])
    np.testing.assert_allclose(responsivity('newport_2107', [425.]), [(0.240 + 0.279) / 2])
    assert np.isnan(responsivity('newport_2107', [299., 1051., np.nan])).all()
    with pytest.raises(ValueError):
        responsivity('missing', [500.])


def test_power_formula_units_and_provenance():
    d = scan()
    result = analyze(d, [step()])
    # Setting 1 is 626 V/A (2107/2117 manual Rev A).
    expected = 1e3 / 626 * np.array([.1/.1, .2/.2595, .5/.524, .3/.119, np.nan, np.nan])
    np.testing.assert_allclose(result.values[:, 1], expected, rtol=1e-12)
    assert result.column_units == ['nm', 'mW'] and result.columns[1] == 'Result (mW)'
    calibration = result.analysis['calibrations']['newport_2107']
    assert calibration['responsivity_a_per_w'][0] == 0.100
    assert calibration['transimpedance_v_per_a_per_setting'] == 626.
    scaled = analyze(d, [step(gain_setting=1e4, dark_v=.05)])
    np.testing.assert_allclose(scaled.values[:4, 1], 1e3 * (np.array(d.values[:4, 1]) - .05)
                               / (626e4 * responsivity('newport_2107', d.values[:4, 0])))


def test_legacy_transimpedance_records_keep_their_values():
    legacy = dict(operation='photodiode_power', parameters=dict(detector='newport_2107', gain_v_per_a=1e3, dark_v=0.))
    np.testing.assert_allclose(analyze(scan(), [legacy]).values[:4, 1],
                               1e3 * np.array([.1, .2, .5, .3]) / (1e3 * responsivity('newport_2107', [300., 425., 900., 1050.])))


def test_manual_worked_example():
    # Manual p. 11: 10 uW at 900 nm on setting 1e3 gives about 3.5 V with its rounded R/1.5 rule;
    # the exact 626 V/A factor gives 3.28 V, so 3.28 V must read back as 10 uW.
    v = 1e-5 * 626e3 * responsivity('newport_2107', [900.])[0]
    result = analyze(scan(wavelength=(900.,), volts=(v,)), [step(gain_setting=1e3)])
    np.testing.assert_allclose(result.values[0, 1], 0.01)


@pytest.mark.parametrize('params', [dict(gain_setting=0.), dict(gain_setting=2.), dict(gain_setting=True),
                                    dict(gain_setting=626.), dict(gain_v_per_a=0.),
                                    dict(dark_v=float('nan')), dict(detector='other'), dict(extra=1)])
def test_invalid_parameters(params):
    with pytest.raises(ValueError):
        analyze(scan(), [step(**params)])


def test_requires_nm_and_volts():
    with pytest.raises(ValueError, match='nm'):
        analyze(scan(), [step()], xunit='um')
    with pytest.raises(ValueError, match='voltage'):
        analyze(scan(), [step()], yunit='mV')
    with pytest.raises(ValueError, match='voltage'):
        analyze(scan(), [dict(operation='normalize', parameters=dict(method='max_abs')), step()])
    with pytest.raises(ValueError, match='calibration range'):
        analyze(scan(wavelength=(1200., 1300.), volts=(.1, .2)), [step()])


@pytest.mark.parametrize('suffix', ['.json', '.h5'])
def test_preset_and_project_round_trip(tmp_path, suffix):
    preset = make_preset([step(gain_setting=3e4)])
    save_presets(tmp_path / 'presets.json', {'2107 power': preset})
    assert load_presets(tmp_path / 'presets.json')['2107 power'] == preset
    d = scan()
    [result] = apply_preset([d], preset, '2107 power')
    save_project(tmp_path / f'p{suffix}', [d, result], {'pipeline_presets': {'2107 power': preset}})
    loaded, settings = load_project(tmp_path / f'p{suffix}')
    restored = next(x for x in loaded if x.id == result.id)
    np.testing.assert_array_equal(restored.values, result.values)
    assert restored.analysis == result.analysis
    assert settings['pipeline_presets']['2107 power'] == preset


@pytest.mark.skipif(not AOTF.exists(), reason='local AOTF example data not present')
def test_aotf_example_converts_all_datasets():
    # The local file may also hold saved mW results; only the voltage scans are inputs.
    datasets = [d for d in load_project(AOTF)[0] if d.raw]
    results = apply_preset(datasets, make_preset([step()]), 'power')
    assert len(results) == len(datasets) == 30
    for source, result in zip(datasets, results):
        assert result.column_units == ['nm', 'mW']
        np.testing.assert_allclose(result.values[:, 1], 1e3 / 626 * source.values[:, 1]
                                   / responsivity('newport_2107', source.values[:, 0]))


def test_dialog_photodiode_step_defaults_and_edits(app):
    from rogi.analysis_ui import AnalysisDialog
    d = scan()
    dialog = AnalysisDialog(d)
    try:
        dialog.operation.setCurrentIndex(dialog.operation.findData('photodiode_power'))
        dialog.add_step()
        assert dialog.operations() == [step()]
        assert dialog.gain.isEnabled() and not dialog.window.isEnabled()
        assert (dialog.gain.currentData(), dialog.gain.currentText(), dialog.dark.value()) == (1.0, '1×1', 0.0)
        assert dialog.gain.count() == 10 and dialog.gain.itemText(5) == '3×10²'
        dialog.preview()
        assert dialog.save_button.isEnabled() and dialog.dataset.column_units == ['nm', 'mW']
        dialog.gain.setCurrentIndex(dialog.gain.findData(3.))
        assert dialog.dataset is None and dialog.operations() == [step(gain_setting=3.0)]
        dialog.preview()
        np.testing.assert_allclose(dialog.dataset.values[0, 1], 1e3 * .1 / (3 * 626 * .1))
    finally:
        dialog.close()
