from copy import deepcopy
import numpy as np
import pytest
from PySide6 import QtWidgets as W
from rogi.core import Dataset
from rogi.analysis_ui import AnalysisDialog
from rogi.image_analysis import process_image, ImagePreviewDialog
from rogi.presets import make_preset
from rogi.project import save_project, load_project
from rogi.scanfile import bundle_channels, channel_views
from rogi.ui import MainWindow


def step(name, **params):
    return dict(operation=name, parameters=params)


def image(values=None, name='Image'):
    values = np.array([[0, 2, 4], [6, 8, 10]] if values is None else values, dtype=float)
    y, x = np.indices(values.shape)
    return Dataset(name, ['Sample', 'X pixel', 'Y pixel', 'Height (V)'],
                   np.column_stack((np.arange(values.size), x.ravel(), y.ravel(), values.ravel())))


def test_global_operations_and_order():
    values = np.array([[0., 2., np.nan], [6., 8., 10.]])
    before = values.copy()
    centered, unit = process_image(values, [step('mean_subtract')], signal_unit='V')
    np.testing.assert_allclose(centered, values - 5.2, equal_nan=True)
    assert unit == 'V'
    result, unit = process_image(values, [step('mean_subtract'), step('normalize', method='max_abs')])
    np.testing.assert_allclose(result, (values-5.2)/5.2, equal_nan=True)
    assert unit == '1'
    reverse, _ = process_image(values, [step('normalize', method='max_abs'), step('mean_subtract')])
    assert not np.allclose(result, reverse, equal_nan=True)
    np.testing.assert_equal(values, before)


def test_smoothing_never_crosses_rows_or_missing_gaps():
    values = [[1., 3., np.nan, 9.], [100., 200., 300., 400.]]
    result, _ = process_image(values, [step('moving_average', window=3)])
    np.testing.assert_allclose(result, [[2,2,np.nan,9], [150,200,300,350]], equal_nan=True)
    vertical, _ = process_image(values, [step('moving_average', window=3)], axis='Y')
    np.testing.assert_allclose(vertical, [[50.5,101.5,np.nan,204.5], [50.5,101.5,300,204.5]], equal_nan=True)


def test_derivative_axes_calibration_missing_and_units():
    result, unit = process_image([[0,4,8], [10,14,18]], [step('differentiate')], spacing=2,
                                 signal_unit='V', coordinate_unit='nm')
    np.testing.assert_allclose(result, 2)
    assert unit == '(V)/(nm)'
    result, unit = process_image([[0,4,8], [10,14,18]], [step('differentiate')], axis='Y', spacing=5,
                                 signal_unit='V', coordinate_unit='nm')
    np.testing.assert_allclose(result, 2)
    missing, _ = process_image([[0,np.nan,8], [np.nan,np.nan,np.nan]], [step('differentiate')])
    assert np.isnan(missing).all()
    singleton, _ = process_image([[1,2,3]], [step('differentiate')], axis='Y')
    assert np.isnan(singleton).all()


@pytest.mark.parametrize('values,operations', [([[0,0]], [step('normalize', method='max_abs')]),
    ([[np.nan]], [step('mean_subtract')]), ([[np.inf]], [step('mean_subtract')]),
    ([[1,2]], [step('moving_average', window=2)])])
def test_preview_errors(values, operations):
    with pytest.raises(ValueError):
        process_image(values, operations)


def test_dialog_auto_preview_axis_and_snapshot(app):
    d = image()
    preset = make_preset([step('differentiate')])
    dialog = ImagePreviewDialog(d, preset, 'Derivative', transpose=True)
    try:
        np.testing.assert_allclose(dialog.result, 2)
        assert dialog.output_unit == '(V)/(pixel)'
        assert dialog.figure.axes[0].images[0].get_array().shape == (3,2)
        preset['operations'].clear()
        dialog.axis.setCurrentIndex(1)
        np.testing.assert_allclose(dialog.result, 6)
        assert 'Close to discard' in dialog.status.text()
    finally:
        dialog.close()


@pytest.mark.parametrize('suffix', ['.json', '.h5'])
def test_one_click_no_dataset_dirty_history_or_persisted_result(app, monkeypatch, tmp_path, suffix):
    window = MainWindow()
    d = image()
    calls = []
    try:
        window.add_dataset(d)
        window.plot_tabs.setCurrentIndex(1)
        window.pipeline_presets['Centered'] = make_preset([step('mean_subtract')])
        window.pipeline_presets_changed()
        window.external_dirty = False
        window.history.setClean()
        window.update_dirty()
        settings = deepcopy(window.settings())
        snapshot = deepcopy(window.image_viewer.snapshot())
        before = d.values.copy()
        history_index = window.history.index()
        def inspect(dialog):
            calls.append(True)
            np.testing.assert_allclose(dialog.result, [[-5,-3,-1], [1,3,5]])
            return W.QDialog.DialogCode.Rejected
        monkeypatch.setattr(ImagePreviewDialog, 'exec', inspect)
        button = next(b for b in window.image_viewer.findChildren(W.QPushButton) if b.text() == 'Centered')
        button.click()
        assert calls == [True]
        assert window.datasets == [d] and not window.dirty
        assert window.history.index() == history_index
        assert window.settings() == settings
        assert window.image_viewer.snapshot() == snapshot
        np.testing.assert_array_equal(d.values, before)
        path = tmp_path / ('preview' + suffix)
        save_project(path, window.datasets, window.settings())
        restored, stored = load_project(path)
        assert len(restored) == 1 and restored[0].analysis is None
        np.testing.assert_array_equal(restored[0].values, before)
        assert stored['pipeline_presets'] == window.pipeline_presets
    finally:
        window.dirty = False
        window.close()


def test_channel_view_units_match_selected_signal():
    first, second = image(), image(name='second')
    first.instrument_metadata = dict(format='nanoscope', version=1, source_dataset_id=first.id, sections=[], unparsed=[])
    d = bundle_channels([first, second])
    d.column_units = ['1', 'pixel', 'pixel', 'V', 'A']
    assert channel_views(d)[1].column_units == ['1', 'pixel', 'pixel', 'A']


def test_buttons_follow_saved_presets(app):
    window = MainWindow()
    dialog = AnalysisDialog(image(), presets=window.pipeline_presets, on_presets_changed=window.pipeline_presets_changed)
    try:
        dialog.load_operations([step('mean_subtract')])
        dialog.store_preset('Subtract background')
        assert any(b.text() == 'Subtract background' for b in window.image_viewer.findChildren(W.QPushButton))
    finally:
        dialog.close()
        window.dirty = False
        window.close()


def test_calibrated_preview_units(app):
    d = image()
    d.instrument_metadata = dict(format='nanonis_sxm', version=1, source_dataset_id=d.id,
        unparsed=[], sections=[dict(name='SCAN_RANGE', occurrence=1, source_line=1,
            entries=[dict(key='Value', raw_value='6e-9 4e-9', value='6e-9 4e-9', unit=None, source_line=2)])])
    dialog = ImagePreviewDialog(d, make_preset([step('differentiate')]), 'Derivative')
    try:
        np.testing.assert_allclose(dialog.result, 1)
        assert dialog.output_unit == '(V)/(nm)'
        dialog.axis.setCurrentIndex(1)
        np.testing.assert_allclose(dialog.result, 3)
    finally:
        dialog.close()
