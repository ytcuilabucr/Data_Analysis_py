import json
import numpy as np
import pytest
from rogi.core import parse_dat
from rogi.maps import assemble_map
from rogi.maps_ui import MapDialog
from rogi.project import save_project, load_project


def spectrum(temp='2 K', field='1 T', x=(0, 1, 2), z=(2, 3, 4)):
    return parse_dat('[Sweep]\nTemperature: '+temp+'\nField: '+field+
                     '\n[Data]\nX (V)\tSignal (A)\n'+
                     '\n'.join(f'{a}\t{b}' for a, b in zip(x, z)))


def recipe(ds, **kw):
    return dict(ids=[d.id for d in ds], x='X (V)', signal='Signal (A)',
                sweep='Sweep[1].Temperature[1]', alignment='exact', missing='reject',
                filters={}, **kw)


def test_coordinates_and_cross_sections():
    ds = [spectrum('7 K', x=(2, 1, 0), z=(9, 8, 7)), spectrum()]
    original = [d.values.copy() for d in ds]
    result = assemble_map(ds, recipe(ds))
    np.testing.assert_array_equal(result.sweep, [2, 7])
    np.testing.assert_array_equal(result.signal, [[2, 3, 4], [7, 8, 9]])
    np.testing.assert_array_equal(result.section('x', 1)[1], [3, 8])
    np.testing.assert_array_equal(result.measured[1]['x'], [2, 1, 0])
    for d, values in zip(ds, original):
        np.testing.assert_array_equal(d.values, values)


@pytest.mark.parametrize('ds, message', [
    ([spectrum(), spectrum()], 'Duplicate sweep'),
    ([spectrum('2 K'), spectrum('3 mK')], 'Inconsistent'),
    ([spectrum('2'), spectrum('3')], 'Unknown units'),
    ([spectrum('')], 'Missing or nonnumeric'),
    ([spectrum(x=(0, 0, 2))], 'finite and unique'),
    ([spectrum(x=(0, np.nan, 2))], 'finite and unique'),
    ([spectrum(z=(1, np.nan, 3))], 'Missing signal'),
])
def test_reject_ambiguous(ds, message):
    with pytest.raises(ValueError, match=message):
        assemble_map(ds, recipe(ds))


def test_alignment_and_gaps():
    ds = [spectrum(x=(0, 1, 2)), spectrum('3 K', x=(0, .5, 3))]
    spec = recipe(ds)
    with pytest.raises(ValueError, match='Differing X'):
        assemble_map(ds, spec)
    spec.update(alignment='union', missing='gaps')
    result = assemble_map(ds, spec)
    np.testing.assert_array_equal(result.x, [0, .5, 1, 2, 3])
    assert np.isnan(result.signal[0, 1])
    spec.update(alignment='reference', reference=ds[0].id)
    result = assemble_map(ds, spec)
    np.testing.assert_allclose(result.signal[1], [2, 3.2, 3.6])


def test_interpolation_never_bridges_missing_or_extrapolates():
    ds = [spectrum(x=(-1, 1, 3)), spectrum('3 K', z=(2, np.nan, 4))]
    spec = recipe(ds)
    spec.update(alignment='reference', reference=ds[0].id, missing='gaps')
    assert np.isnan(assemble_map(ds, spec).signal[1]).all()


def test_dimensions_missing_slice_and_reference():
    ds = [spectrum(), spectrum(field='2 T'), spectrum('3 K', field='2 T')]
    spec = recipe(ds)
    spec['filters'] = {'Sweep[1].Field[1]': '2 T'}
    assert len(assemble_map(ds, spec).sweep) == 2
    spec.update(alignment='reference', reference=ds[0].id)
    with pytest.raises(ValueError, match='outside'):
        assemble_map(ds, spec)
    spec['filters']['Sweep[1].Field[1]'] = '3 T'
    with pytest.raises(ValueError, match='No measurements'):
        assemble_map(ds, spec)


def test_exports(tmp_path):
    ds = [spectrum(), spectrum('3 K')]
    result = assemble_map(ds, recipe(ds))
    path = tmp_path / 'map.npz'
    result.export(path)
    with np.load(path, allow_pickle=False) as data:
        np.testing.assert_array_equal(data['measured_x_0'], ds[0].values[:, 0])
        assert json.loads(str(data['recipe'])) == recipe(ds)
    result.export(tmp_path / 'map.csv')
    assert len((tmp_path / 'map.csv').read_text().splitlines()) == 7


@pytest.mark.parametrize('extension', ['json', 'h5'])
def test_named_map_roundtrip(tmp_path, extension):
    ds = [spectrum(), spectrum('3 K')]
    views = {'Temperature map': dict(kind='spectrum_map', recipe=recipe(ds))}
    path = tmp_path / ('map.' + extension)
    save_project(path, ds, {'saved_views': views})
    loaded, settings = load_project(path)
    assert settings['saved_views'] == views
    assert assemble_map(loaded, views['Temperature map']['recipe']).signal.shape == (2, 3)


def test_dialog_requires_explicit_choices_and_invalidates(app):
    ds = [spectrum(), spectrum('3 K')]
    dialog = MapDialog(ds)
    dialog.build()
    assert dialog.result is None
    dialog.close()
    dialog = MapDialog(ds, recipe=recipe(ds))
    assert dialog.result.signal.shape == (2, 3)
    dialog.section_axis.setCurrentIndex(1)
    assert dialog.section_value.count() == 3
    dialog.alignment.setCurrentIndex(0)
    assert dialog.result is None
    assert all(not b.isEnabled() for b in dialog.result_buttons)
    dialog.close()


def test_saved_section_and_missing_source(app):
    ds = [spectrum(), spectrum('3 K')]
    spec = recipe(ds)
    spec['section'] = dict(axis='x', index=2)
    dialog = MapDialog(ds, recipe=spec)
    assert dialog.section_axis.currentData() == 'x'
    assert dialog.section_value.currentIndex() == 2
    dialog.close()
    with pytest.raises(ValueError, match='source spectrum is missing'):
        assemble_map(ds[:1], spec)


def test_channel_units_and_absent_channel():
    ds = [spectrum(), spectrum('3 K')]
    ds[1].column_units = ['mV', 'A']
    with pytest.raises(ValueError, match='Inconsistent'):
        assemble_map(ds, recipe(ds))
    ds[1].columns[1] = 'Other (A)'
    with pytest.raises(ValueError, match='channel is missing'):
        assemble_map(ds, recipe(ds))
