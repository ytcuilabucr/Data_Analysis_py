from copy import deepcopy
import json
import numpy as np
import pytest
from rogi.analysis import analyze
from rogi.analysis_ui import AnalysisDialog, BatchPipelineDialog
from rogi.core import Dataset
from rogi.presets import make_preset, save_presets, load_presets, apply_preset
from rogi.project import save_project, load_project
from rogi.ui import MainWindow


def source(name='input'):
    return Dataset(name, ['X (s)', 'Y (V)', 'Other (A)'], [[0,1,4], [1,3,8], [2,5,12]])


def recipe():
    return [dict(operation='mean_subtract', parameters={}),
            dict(operation='normalize', parameters={'method': 'max_abs'})]


@pytest.mark.parametrize('suffix', ['.json', '.h5'])
def test_project_and_portable_preset_roundtrip(tmp_path, suffix):
    operations = recipe()
    presets = {'Centered': make_preset(operations)}
    operations.clear()
    path = tmp_path / ('project' + suffix)
    save_project(path, [source()], {'pipeline_presets': presets})
    datasets, settings = load_project(path)
    assert settings['pipeline_presets'] == presets
    export = tmp_path / 'preset.json'
    save_presets(export, presets)
    assert load_presets(export) == presets
    r = apply_preset(datasets, load_presets(export)['Centered'], 'Centered')[0]
    np.testing.assert_allclose(r.values[:,1], [-1,0,1])
    assert r.analysis['operations'] == recipe()
    presets['Centered']['operations'].clear()
    assert r.analysis['operations'] == recipe()


def test_invalid_presets_leave_existing_file_intact(tmp_path):
    path = tmp_path / 'presets.json'
    save_presets(path, {'Valid': make_preset(recipe())})
    before = path.read_bytes()
    bad = make_preset(recipe())
    bad['version'] = 99
    with pytest.raises(ValueError):
        save_presets(path, {'Invalid': bad})
    assert path.read_bytes() == before
    for payload in [[], {'format': 'rogi-pipeline-presets', 'version': 1, 'presets': {'bad': bad}}]:
        path.write_text(json.dumps(payload))
        with pytest.raises(ValueError):
            load_presets(path)


def test_preset_editor_updates_are_explicit(app):
    presets = {}
    changes = []
    dialog = AnalysisDialog(source(), presets=presets, on_presets_changed=lambda: changes.append(True))
    try:
        dialog.load_operations(recipe())
        dialog.store_preset('Centered')
        assert changes == [True]
        dialog.preview()
        dialog.steps.setCurrentRow(1)
        dialog.method.setCurrentIndex(1)
        assert dialog.dataset is None
        assert presets['Centered']['operations'] == recipe()
        dialog.load_selected_preset()
        assert dialog.operations() == recipe()
        dialog.steps.setCurrentRow(1)
        dialog.method.setCurrentIndex(1)
        dialog.store_preset('Centered')
        assert presets['Centered']['operations'][1]['parameters']['method'] == 'min_max'
        dialog.reject()  # Explicit preset saving survives cancelling result creation.
        assert presets and len(changes) == 2
    finally:
        dialog.close()


def test_batch_mapping_preview_invalidation_and_atomic_history(app):
    sources = [source('one'), source('two')]
    before = [d.values.copy() for d in sources]
    presets = {'Center': make_preset([recipe()[0]])}
    dialog = BatchPipelineDialog(sources, presets)
    window = MainWindow()
    try:
        for d in sources:
            window.add_dataset(d)
        dialog.channels[1][1].setCurrentIndex(2)
        dialog.preview()
        assert len(dialog.datasets) == 2
        np.testing.assert_allclose(dialog.datasets[0].values[:,1], [-2,0,2])
        np.testing.assert_allclose(dialog.datasets[1].values[:,1], [-4,0,4])
        assert dialog.datasets[1].column_units == ['s', 'A']
        assert sources[1].ycol == 1
        window.add_analysis_batch(dialog.datasets)
        assert len(window.datasets) == 4
        window.history.undo()
        assert window.datasets == sources
        window.history.redo()
        assert len(window.datasets) == 4
        dialog.channels[1][0].setCurrentIndex(2)
        assert not dialog.save_button.isEnabled()
        dialog.preview()
        assert dialog.datasets == [] and 'two' in dialog.status.text()
        for d, values in zip(sources, before):
            np.testing.assert_array_equal(d.values, values)
            assert d.revision == 0
    finally:
        dialog.close()
        window.external_dirty = False
        window.history.setClean()
        window.update_dirty()
        window.close()


def test_reopen_recipe_current_revision_and_project_settings(app, monkeypatch, tmp_path):
    window = MainWindow()
    d = source().derived()
    result = analyze(d, recipe(), ycol=2)
    window.add_dataset(d)
    window.add_dataset(result)
    window.activate_dataset(result.id)
    d.edit(0, 2, '20')
    def inspect(dialog):
        assert dialog.source is d
        assert dialog.ychannel.currentIndex() == 2
        assert dialog.operations() == recipe()
        assert 'Source changed' in dialog.status.text()
        dialog.store_preset('Reopened')
        dialog.preview()
        assert dialog.dataset.analysis['source']['revision'] == 1
        return 0
    monkeypatch.setattr(AnalysisDialog, 'exec', inspect)
    try:
        window.reopen_analysis_recipe()
        assert window.dirty and 'Reopened' in window.pipeline_presets
        assert len(window.datasets) == 2
        path = tmp_path / 'project.json'
        save_project(path, window.datasets, window.settings())
        other = MainWindow()
        try:
            other.open_project(str(path), confirm=False)
            assert other.pipeline_presets == window.pipeline_presets
        finally:
            other.close()
    finally:
        window.external_dirty = False
        window.history.setClean()
        window.update_dirty()
        window.close()


def test_legacy_and_invalid_project_presets(tmp_path):
    path = tmp_path / 'project.json'
    save_project(path, [source()], {})
    assert load_project(path)[1].get('pipeline_presets', {}) == {}
    payload = json.loads(path.read_text())
    payload['settings']['pipeline_presets'] = {'bad': {'version': 1}}
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError):
        load_project(path)
