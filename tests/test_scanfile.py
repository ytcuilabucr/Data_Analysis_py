from copy import deepcopy
from pathlib import Path
import numpy as np
import pytest
from rogi.spm import parse_spm, load_spm
from rogi.scanfile import bundle_channels, channel_views, consolidate_legacy
from rogi.images import ImageViewer, raster
from rogi.spatial import scan_dimensions
from rogi.project import save_project, load_project
from rogi.metadata import validate_metadata
from rogi.ui import MainWindow
from test_spm import spm_bytes
from test_nanonis import scan_bytes


@pytest.mark.parametrize('data', [spm_bytes(), scan_bytes()])
@pytest.mark.parametrize('suffix', ['.h5', '.json'])
def test_file_roundtrip_preserves_every_channel(tmp_path, data, suffix):
    originals = parse_spm(data, name='scan', source='/input/scan.spm')
    dataset = bundle_channels(originals)
    assert dataset.name == 'scan'
    assert dataset.values.shape[1] == 3 + len(originals)
    output = tmp_path / ('file' + suffix)
    save_project(output, [dataset], {})
    restored, _ = load_project(output)
    assert len(restored) == 1
    for original, actual in zip(originals, channel_views(restored[0]), strict=True):
        np.testing.assert_array_equal(original.values, actual.values)
        np.testing.assert_array_equal(raster(original), raster(actual))
        assert original.columns == actual.columns
        assert scan_dimensions(original) == scan_dimensions(actual)


def test_different_grids_and_duplicate_labels():
    originals = parse_spm(spm_bytes())
    originals[1].values = originals[1].values[:2]
    originals[1].columns[3] = originals[0].columns[3]
    dataset = bundle_channels(originals)
    validate_metadata(dataset)
    assert len(set(dataset.columns)) == len(dataset.columns)
    views = channel_views(dataset)
    assert [raster(v).shape for v in views] == [(2,2), (1,2)]
    for original, view in zip(originals, views):
        np.testing.assert_array_equal(original.values, view.values)
    assert views[0].name != views[1].name


def test_file_map_channel_switch_and_comparison(app):
    originals = parse_spm(spm_bytes(), source='/scans/a.spm')
    dataset = bundle_channels(originals, name='File')
    other = bundle_channels(parse_spm(spm_bytes(), source='/scans/b.SPM'), name='Other file')
    viewer = ImageViewer()
    try:
        viewer.set_context([dataset, other], dataset)
        assert viewer.channel.count() == 2
        assert viewer.compare.count() == 2
        first = viewer.current.id
        viewer.channel.setCurrentIndex(1)
        assert viewer.current.id != first
        np.testing.assert_array_equal(next(iter(viewer.panels.values()))[1], raster(originals[1]))
        viewer.compare.setCurrentIndex(1)
        assert len(viewer.panels) == 2
        assert {p[0].columns[-1] for p in viewer.panels.values()} == {originals[1].columns[-1]}
        assert len({p[0].source for p in viewer.panels.values()}) == 2
        viewer.set_context([], None)
        viewer.set_context([dataset, other], dataset)
        assert viewer.channel.currentIndex() == 1
    finally:
        viewer.close()


def test_editable_copy_channel_changes_and_undo(app):
    dataset = bundle_channels(parse_spm(spm_bytes())).derived()
    window = MainWindow()
    try:
        window.add_dataset(dataset)
        window.plot_tabs.setCurrentIndex(1)
        window.image_viewer.channel.setCurrentIndex(1)
        window.edit_cell(dataset, 0, 4, '123')
        assert window.image_viewer.current.values[0,3] == 123
        window.history.undo()
        assert window.image_viewer.current.values[0,3] == 12
    finally:
        window.dirty = False
        window.close()


def test_legacy_open_preserves_original_file(app, tmp_path):
    originals = parse_spm(spm_bytes(), name='scan', source='/input/scan.spm')
    path = tmp_path / 'old.h5'
    save_project(path, originals, {'selected_dataset_id': originals[1].id})
    before = path.read_bytes()
    window = MainWindow()
    try:
        window.open_project(path)
        assert window.browser.count() == 1
        assert window.current().name == 'scan'
        assert window.image_viewer.channel.currentIndex() == 1
        assert path.read_bytes() == before
    finally:
        window.dirty = False
        window.close()


def test_legacy_dependent_or_duplicate_import_not_merged():
    originals = parse_spm(spm_bytes(), name='scan', source='/input/scan.spm')
    derived = originals[0].derived()
    result, _ = consolidate_legacy(originals + [derived])
    assert result == originals + [derived]
    duplicates = parse_spm(spm_bytes(), name='scan', source='/input/scan.spm')
    result, _ = consolidate_legacy(originals + duplicates)
    assert len(result) == 4


@pytest.mark.parametrize('field,value', [('signal_column', 99), ('rows', -1), ('coordinate_columns', [0,1,99])])
def test_invalid_layout_rejected(field,value):
    dataset = bundle_channels(parse_spm(spm_bytes()))
    dataset.instrument_metadata['channels'][0][field] = value
    with pytest.raises(ValueError, match='channel layout'):
        validate_metadata(dataset)
