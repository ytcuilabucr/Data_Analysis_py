from copy import deepcopy
import numpy as np
import pytest
from rogi.core import Dataset
from rogi.analysis import analyze, POLICIES
from rogi.project import save_project, load_project


def step(op, **params):
    return dict(operation=op, parameters=params)


def source(y=(1., 3., 5., 7., 9.), x=None):
    return Dataset('signal', ['Time (s)', 'Signal (V)'],
                   np.column_stack((np.arange(len(y)) if x is None else x, y)))


def test_mean_normalization_order_and_independence():
    d = source()
    before = d.values.copy()
    recipe = [step('mean_subtract'), step('normalize', method='max_abs')]
    result = analyze(d, recipe)
    np.testing.assert_allclose(result.values[:, 1], [-1, -.5, 0, .5, 1])
    reverse = analyze(d, recipe[::-1])
    np.testing.assert_allclose(reverse.values[:, 1], np.array([-4,-2,0,2,4])/9)
    assert result.column_units == ['s', '1']
    assert result.parent == d.id and result.id != d.id and not result.raw
    recipe[0]['operation'] = 'differentiate'
    assert result.analysis['operations'][0]['operation'] == 'mean_subtract'
    result.edit(0, 1, '42')
    np.testing.assert_array_equal(d.values, before)
    assert not d.values.flags.writeable and d.revision == 0


def test_minmax():
    result = analyze(source([-3, 0, 9]), [step('normalize', method='min_max')])
    np.testing.assert_allclose(result.values[:, 1], [0, .25, 1])


def test_smoothing_boundaries_and_missing_no_gap_bridging():
    d = source([1, 3, 9, np.nan, 20, 40, 60], [0, 1, 4, 6, 8, 9, 20])
    r = analyze(d, [step('moving_average', window=3)])
    np.testing.assert_allclose(r.values[:, 1], [2, 13/3, 6, np.nan, 30, 40, 50], equal_nan=True)
    np.testing.assert_allclose(analyze(d, [step('moving_average', window=99)]).values[:, 1],
                               [13/3]*3 + [np.nan] + [40]*3, equal_nan=True)
    np.testing.assert_equal(analyze(d, [step('moving_average', window=1)]).values, d.values)


@pytest.mark.parametrize('x', [[0., 1., 3., 6.], [6., 3., 1., 0.]])
def test_irregular_derivative(x):
    x = np.array(x)
    r = analyze(source(x*x, x), [step('differentiate')])
    expected = 2*x
    expected[0], expected[-1] = x[0]+x[1], x[-2]+x[-1]
    np.testing.assert_allclose(r.values[:, 1], expected)
    assert r.column_units == ['s', '(V)/(s)']


def test_derivative_gaps_and_singletons():
    r = analyze(source([0, 2, np.nan, 20, 25, 30, 50], [0, 1, 2, 3, 4, np.nan, 6]),
                [step('differentiate')])
    np.testing.assert_allclose(r.values[:, 1], [2,2,np.nan,5,5,np.nan,np.nan], equal_nan=True)
    assert np.isnan(analyze(source([3]), [step('differentiate')]).values[0,1])


@pytest.mark.parametrize('x', [[0,1,1], [0,2,1]])
def test_reject_ambiguous_spacing(x):
    with pytest.raises(ValueError, match='monotonic'):
        analyze(source([1,2,3], x), [step('differentiate')])


@pytest.mark.parametrize('recipe,y', [([step('normalize', method='max_abs')], [0,0]),
    ([step('normalize', method='min_max')], [3,3]), ([step('mean_subtract')], [np.nan,np.nan]),
    ([step('moving_average', window=2)], [1,2]), ([step('differentiate', order=2)], [1,2]),
    ([step('unknown')], [1,2]), ([], [1,2])])
def test_invalid_inputs(recipe, y):
    with pytest.raises(ValueError):
        analyze(source(y), recipe)


def test_missing_x_excluded_and_unknown_units():
    d = source([1,999,3], [0,np.nan,2])
    r = analyze(d, [step('mean_subtract')], xunit='', yunit='')
    np.testing.assert_allclose(r.values[:, 1], [-1,np.nan,1], equal_nan=True)
    assert analyze(d, [step('differentiate')], xunit='').column_units[1] == ''


@pytest.mark.parametrize('suffix', ['.json', '.h5'])
def test_persistence_and_chained_provenance(tmp_path, suffix):
    d = source().derived()
    d.edit(0, 1, '2')
    r = analyze(d, [step('mean_subtract'), step('differentiate')])
    second = analyze(r, [step('normalize', method='max_abs')])
    path = tmp_path / ('analysis' + suffix)
    save_project(path, [d, r, second], {})
    restored, _ = load_project(path)
    for before, after in zip([d,r,second], restored):
        np.testing.assert_equal(after.values, before.values)
        assert after.analysis == before.analysis
        assert after.column_units == before.column_units
        assert after.parent == before.parent
    record = restored[1].analysis
    assert record['source'] == dict(dataset_id=d.id, revision=1)
    assert record['input_channels'] == dict(x=dict(index=0, name='Time (s)', unit='s'),
                                          y=dict(index=1, name='Signal (V)', unit='V'))
    assert record['policies'] == POLICIES
    restored[0].edit(0, 1, '100')
    np.testing.assert_equal(restored[1].values, r.values)
    assert restored[1].analysis['source']['revision'] == 1
    assert restored[2].analysis['source']['dataset_id'] == r.id
    copied = restored[1].derived()
    assert copied.analysis == record and copied.analysis is not record


def test_legacy_and_malformed_provenance(tmp_path):
    import json
    path = tmp_path / 'old.json'
    save_project(path, [source()], {})
    content = json.loads(path.read_text())
    del content['datasets'][0]['analysis']
    del content['datasets'][0]['column_units']
    path.write_text(json.dumps(content))
    assert load_project(path)[0][0].analysis is None
    content['datasets'][0]['analysis'] = {'version': 1}
    path.write_text(json.dumps(content))
    with pytest.raises(ValueError, match='provenance'):
        load_project(path)


def test_dialog_preview_reorder_invalidation_and_undo(app):
    from rogi.analysis_ui import AnalysisDialog
    from rogi.ui import MainWindow
    window = MainWindow()
    d = source()
    window.add_dataset(d)
    dialog = AnalysisDialog(d, window)
    try:
        dialog.add_step()
        dialog.operation.setCurrentIndex(1)
        dialog.add_step()
        dialog.preview()
        assert dialog.save_button.isEnabled()
        np.testing.assert_allclose(dialog.dataset.values[:,1], [-1,-.5,0,.5,1])
        dialog.move_step(-1)
        assert dialog.dataset is None and not dialog.save_button.isEnabled()
        dialog.preview()
        result = dialog.dataset
        window.add_dataset(result)
        assert len(window.datasets) == 2
        window.history.undo()
        assert window.datasets == [d]
        window.history.redo()
        assert window.datasets[-1] is result
        dialog.method.setCurrentIndex(1)
        assert dialog.dataset is None
        dialog.preview()
        dialog.xchannel.setCurrentIndex(1)
        dialog.preview()
        assert not dialog.save_button.isEnabled()
        assert 'distinct' in dialog.status.text()
    finally:
        dialog.close()
        window.dirty = False
        window.close()
