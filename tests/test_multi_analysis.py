import numpy as np
import pytest
from rogi.analysis import analyze_many
from rogi.core import Dataset
from rogi.project import save_project, load_project


def spectrum(y, x=None, name='Signal'):
    return Dataset(name, ['Time', 'Signal'], np.column_stack((np.arange(len(y)) if x is None else x, y)), column_units=['s', 'V'])


def test_mean_sd_sem_counts_and_independence():
    a, b = spectrum([1, 2, np.nan, np.nan]), spectrum([3, np.nan, 4, np.nan])
    r, = analyze_many([a, b])
    np.testing.assert_allclose(r.values[:, 1], [2, 2, 4, np.nan], equal_nan=True)
    np.testing.assert_allclose(r.values[:, 2], [np.sqrt(2), np.nan, np.nan, np.nan], equal_nan=True)
    np.testing.assert_allclose(r.values[:, 3], [1, np.nan, np.nan, np.nan], equal_nan=True)
    np.testing.assert_array_equal(r.values[:, 4], [2, 1, 1, 0])
    r.edit(0, 1, '99')
    assert a.values[0, 1] == 1


def test_subtraction_direction_reference_and_explicit_pairs():
    a, b, c = spectrum([10, np.nan]), spectrum([3, 4]), spectrum([1, 2])
    results = analyze_many([a, b, c], 'reference_subtract', reference=c.id)
    np.testing.assert_allclose(results[0].values[:, 1], [9, np.nan], equal_nan=True)
    np.testing.assert_array_equal(results[0].values[:, 2], [2, 1])
    r, = analyze_many([a, b, c], 'paired_subtract', pairs=[(b.id, a.id)])
    assert r.values[0, 1] == -7
    assert r.analysis['pairs'] == [[b.id, a.id]]
    with pytest.raises(ValueError, match='explicit pairs'):
        analyze_many([a, b], 'paired_subtract')


@pytest.mark.parametrize('change', ['unit', 'channel', 'grid'])
def test_strict_compatibility(change):
    a, b = spectrum([1, 2]), spectrum([3, 4])
    if change == 'unit':
        b.column_units[1] = 'mV'
    elif change == 'channel':
        b.columns[1] = 'Other'
    else:
        b = spectrum([3, 4], [0, 1.000001])
    with pytest.raises(ValueError, match='Compatible|Matching'):
        analyze_many([a, b])


def test_interpolation_descending_gaps_and_no_extrapolation():
    a = spectrum([0]*9, [-1, 0, .5, 1, 1.5, 2, 2.5, 3, 4])
    b = spectrum([6, np.nan, 2, 0], [3, 2, 1, 0])
    r, = analyze_many([a, b], 'paired_subtract', pairs=[(b.id, a.id)], alignment='interpolate', grid=a.id)
    np.testing.assert_allclose(r.values[:, 1], [np.nan, 0, 1, 2, np.nan, np.nan, np.nan, 6, np.nan], equal_nan=True)
    with pytest.raises(ValueError, match='reference grid'):
        analyze_many([a, b], alignment='interpolate')
    b = spectrum([1, 2, 3], [0, 0, 1])
    with pytest.raises(ValueError, match='monotonic'):
        analyze_many([a, b], alignment='interpolate', grid=a.id)


@pytest.mark.parametrize('suffix', ['.json', '.h5'])
def test_multi_roundtrip(tmp_path, suffix):
    a, b = spectrum([1, 2]), spectrum([3, 4])
    r, = analyze_many([a, b])
    path = tmp_path / ('project' + suffix)
    save_project(path, [a, b, r], {})
    loaded, _ = load_project(path)
    assert loaded[-1].analysis == r.analysis
    np.testing.assert_equal(loaded[-1].values, r.values)
    assert {s['dataset_id'] for s in r.analysis['sources']} == {a.id, b.id}


def test_dialog_and_saved_band(app):
    from rogi.analysis_ui import MultiAnalysisDialog
    from rogi.ui import MainWindow
    a, b = spectrum([1, 2]), spectrum([3, 4])
    window = MainWindow()
    dialog = MultiAnalysisDialog([a, b], window)
    try:
        dialog.preview()
        assert dialog.save_button.isEnabled()
        assert len(dialog.figure.axes) == 2
        result = dialog.datasets[0]
        window.add_dataset(result)
        window.draw_plot()
        assert any('sample SD' in c.get_label() for c in window.ax.collections)
        dialog.alignment.setCurrentIndex(1)
        assert not dialog.datasets
        dialog.preview()
        assert 'reference grid' in dialog.status.text()
        dialog.grid.setCurrentIndex(0)
        dialog.preview()
        assert dialog.save_button.isEnabled()
        dialog.operation.setCurrentIndex(2)
        dialog.preview()
        assert not dialog.save_button.isEnabled()
        dialog.add_pair()
        dialog.preview()
        assert dialog.datasets[0].values[0, 1] == -2
    finally:
        dialog.close()
        window.dirty = False
        window.close()


def test_stale_preview_cannot_be_saved(app):
    from rogi.analysis_ui import MultiAnalysisDialog
    a, b = spectrum([1, 2]).derived(), spectrum([3, 4])
    dialog = MultiAnalysisDialog([a, b])
    try:
        dialog.preview()
        a.edit(0, 1, '7')
        dialog.save_result()
        assert not dialog.datasets
        assert 'Inputs changed' in dialog.status.text()
    finally:
        dialog.close()


def test_malformed_multi_provenance():
    from copy import deepcopy
    from rogi.analysis import validate_analysis
    r, = analyze_many([spectrum([1, 2]), spectrum([3, 4])])
    for key, value in [('sources', []), ('alignment', {'mode': 'interpolate'}), ('output_units', 'abcde'), ('pairs', [['bad', 'ids']])]:
        record = deepcopy(r.analysis)
        record[key] = value
        with pytest.raises(ValueError):
            validate_analysis(record)
