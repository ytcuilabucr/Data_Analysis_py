import json
import numpy as np
import pytest
from rogi.core import Dataset, parse_text, fit_dataset, gaussian, export_data, export_fit
from rogi.project import save_project, load_project


def dataset(x, y):
    return Dataset('synthetic', ['x', 'y'], np.column_stack((x, y)))


def test_linear_known_and_uncertainty():
    x = np.linspace(-4, 5, 100)
    y = 2.5*x - 1.2 + np.random.default_rng(42).normal(0, .05, x.size)
    d = dataset(x, y)
    f = fit_dataset(d, 'Linear', -4, 5)
    assert f['parameters']['slope'] == pytest.approx(2.5, abs=.01)
    assert f['parameters']['intercept'] == pytest.approx(-1.2, abs=.02)
    reference = np.polyfit(x, y, 1, cov=True)
    np.testing.assert_allclose(list(f['parameters'].values()), reference[0])
    np.testing.assert_allclose(f['covariance'], reference[1])
    np.testing.assert_allclose(np.array(f['observed'])-f['predicted'], f['residuals'])


@pytest.mark.parametrize('amplitude', [4., -4.])
def test_gaussian(amplitude):
    x = np.linspace(-5, 7, 241)
    y = gaussian(x, 1.5, amplitude, .8, 1.2)
    f = fit_dataset(dataset(x, y), 'Gaussian', -5, 7)
    np.testing.assert_allclose(list(f['parameters'].values()), [1.5, amplitude, .8, 1.2], atol=1e-6)
    assert f['rmse'] < 1e-8


def test_range_missing_and_raw():
    d = parse_text('x,y\n0,1\n1,3\n2,5\n3,7\n4,100\n5,NA\n')
    with pytest.raises(ValueError, match='missing'):
        fit_dataset(d, 'Linear', 0, 3)
    f = fit_dataset(d, 'Linear', 0, 3, True)
    assert f['rows'] == [0, 1, 2, 3]
    assert f['parameters']['slope'] == pytest.approx(2)
    assert f['excluded_missing'] == 1
    with pytest.raises(ValueError):
        d.values[0, 0] = 1
    derived = d.derived()
    derived.fit = f
    derived.edit(0, 1, '2')
    assert derived.fit is None and derived.revision == 1
    assert d.values[0, 1] == 1
    assert derived.edits[0]['old'] == 1


@pytest.mark.parametrize('text,match', [('', 'empty'), ('x,y\n', 'no data'), ('x,y\n1\n', 'Row 2'), ('x,y\n1,nope\n', 'column 2'), ('x,x\n1,2', 'unique'), ('x,y\n1,inf', 'finite')])
def test_import_failures(text, match):
    with pytest.raises(ValueError, match=match):
        parse_text(text)


def test_tab_selection_no_header():
    d = parse_text('1\tignore\t3\n2\ttext\t4', '\t', False, [0, 2])
    np.testing.assert_array_equal(d.values, [[1,3], [2,4]])
    assert 'ignore' in d.source_text


@pytest.mark.parametrize('model,lo,hi', [('Linear', 2, 1), ('Linear', 0, 0.1), ('Gaussian', 0, 5)])
def test_invalid_fit(model, lo, hi):
    with pytest.raises(ValueError):
        fit_dataset(dataset(np.arange(6.), np.ones(6)), model, lo, hi)


def test_roundtrip_exports(tmp_path):
    raw = parse_text('x,y\n0,1\n1,3\n2,5\n3,7\n4,NA')
    d = raw.derived()
    d.edit(0, 1, '1.1')
    d.fit = fit_dataset(d, 'Linear', 0, 3, True)
    path = tmp_path/'project.json'
    save_project(path, [raw, d], {'title': 'Test', 'xlim': [0, 4]})
    restored, settings = load_project(path)
    assert restored[1].fit == d.fit
    assert restored[1].edits == d.edits
    assert restored[0].source_text == raw.source_text
    assert not restored[0].values.flags.writeable
    np.testing.assert_equal(restored[1].values, d.values)
    assert settings['title'] == 'Test'
    export_data(d, tmp_path/'data.csv')
    again = parse_text((tmp_path/'data.csv').read_text())
    np.testing.assert_equal(again.values, d.values)
    export_fit(d, tmp_path/'fit.csv')
    assert 'standard_error' in (tmp_path/'fit.csv').read_text()
    payload = json.loads(path.read_text())
    payload['version'] = 99
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match='version'):
        load_project(path)


def test_failed_save_preserves_previous(tmp_path):
    path = tmp_path/'p.json'
    save_project(path, [], {})
    before = path.read_text()
    with pytest.raises(ValueError):
        save_project(path, [], {'bad': float('nan')})
    assert path.read_text() == before


@pytest.mark.parametrize('corruption', ['axis', 'parameter', 'rows', 'columns'])
def test_malformed_projects(tmp_path, corruption):
    d = dataset(np.arange(6.), 2*np.arange(6.)+1)
    d.fit = fit_dataset(d, 'Linear', 0, 5)
    path = tmp_path/'bad.json'
    save_project(path, [d], {})
    payload = json.loads(path.read_text())
    if corruption == 'axis':
        payload['settings']['xlim'] = [0]
    elif corruption == 'parameter':
        payload['datasets'][0]['fit']['parameters']['slope'] = None
    elif corruption == 'rows':
        payload['datasets'][0]['fit']['rows'] = [999]
    else:
        payload['datasets'][0]['xcol'] = 99
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError):
        load_project(path)


def test_noisy_gaussian_uncertainties():
    x = np.linspace(-6, 6, 241)
    y = gaussian(x, 1, 3, .5, 1.1)+np.random.default_rng(101).normal(0,.03,x.size)
    f = fit_dataset(dataset(x, y), 'Gaussian', -6, 6)
    for name, expected in zip(['baseline', 'amplitude', 'center', 'sigma'], [1, 3, .5, 1.1]):
        assert f['errors'][name] > 0
        assert f['parameters'][name] == pytest.approx(expected, abs=.03)
