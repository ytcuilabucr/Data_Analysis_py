import h5py
import numpy as np
import pytest

from rogi.core import parse_text, fit_dataset
from rogi.project import save_project, load_project


def test_edit_fit_and_migrate(tmp_path):
    raw = parse_text('x,y\n0,1\n1,3\n2,5\n3,7\n4,NA', name='測定')
    edited = raw.derived()
    edited.edit(0, 1, '1.1')
    edited.fit = fit_dataset(edited, 'Linear', 0, 3, True)
    settings = dict(title='Δ measurement', xlim=[0, 4])
    legacy = tmp_path / 'legacy.json'
    save_project(legacy, [raw, edited], settings)
    datasets, restored_settings = load_project(legacy)
    path = tmp_path / 'project.h5'
    save_project(path, datasets, restored_settings)
    with h5py.File(path, 'r') as file:
        assert file['datasets/00000000/values'].compression == 'gzip'
        assert file['datasets/00000001/fit/rows'].dtype.kind == 'i'
    restored, result_settings = load_project(path)
    assert result_settings == settings
    assert restored[1].fit == edited.fit
    assert restored[1].edits == edited.edits
    assert restored[1].parent == raw.id
    assert restored[0].source_text == raw.source_text
    assert restored[0].name == raw.name
    assert not restored[0].values.flags.writeable
    np.testing.assert_equal(restored[1].values, edited.values)
    restored[1].edit(1, 1, '')
    assert restored[1].fit is None
    save_project(path, restored, result_settings)
    reopened, _ = load_project(path)
    assert np.isnan(reopened[1].values[1, 1])
    assert reopened[1].revision == 2
    assert reopened[0].values[1, 1] == 3
    save_project(legacy, reopened, result_settings)
    np.testing.assert_equal(load_project(legacy)[0][1].values, reopened[1].values)


def test_hdf5_failed_save_preserves_original(tmp_path, monkeypatch):
    path = tmp_path / 'project.h5'
    save_project(path, [], {})
    original = path.read_bytes()
    with pytest.raises(ValueError):
        save_project(path, [], {'bad': float('nan')})
    assert path.read_bytes() == original
    def fail_replace(*args):
        raise OSError('simulated disk failure')
    monkeypatch.setattr('rogi.hdf5.os.replace', fail_replace)
    with pytest.raises(OSError):
        save_project(path, [], {'title': 'new'})
    assert path.read_bytes() == original
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize('corruption', ['version', 'missing', 'values'])
def test_invalid_hdf5(tmp_path, corruption):
    path = tmp_path / 'project.h5'
    save_project(path, [parse_text('x,y\n0,1\n1,2')], {})
    with h5py.File(path, 'r+') as file:
        if corruption == 'version':
            file.attrs['version'] = 99
        elif corruption == 'missing':
            del file['datasets/00000000/metadata']
        else:
            file['datasets/00000000/values'][0, 0] = np.inf
    with pytest.raises(ValueError):
        load_project(path)
