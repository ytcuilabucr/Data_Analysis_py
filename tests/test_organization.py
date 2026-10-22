"""Dataset organization keeps presentation independent of scientific data."""
import json
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('MPLCONFIGDIR', '/tmp/rogi-matplotlib-tests')

import h5py
import numpy as np
import pytest
from PySide6 import QtCore as C, QtWidgets as W

from rogi.core import parse_text, fit_dataset, remove_datasets
from rogi.project import load_project, save_project
from rogi.ui import MainWindow


@pytest.fixture
def window():
    app = W.QApplication.instance() or W.QApplication([])
    widget = MainWindow()
    yield widget
    widget.dirty = False
    widget.close()


@pytest.mark.parametrize('extension', ['json', 'h5'])
def test_organization_roundtrip_and_legacy_defaults(tmp_path, extension):
    raw = parse_text('x,y\n0,1\n1,3\n2,5\n3,7\n4,', source='original.csv')
    raw.group = 'Experiment α'
    child = raw.derived()
    child.edit(0, 1, '1.1')
    child.fit = fit_dataset(child, 'Linear', 0, 3, True)
    raw.name = 'Renamed raw'
    child.visible = False
    path = tmp_path / f'project.{extension}'
    save_project(path, [raw, child], {})
    restored, _ = load_project(path)
    for before, after in zip([raw, child], restored):
        assert (after.id, after.parent, after.source, after.source_text, after.edits, after.fit) == (
            before.id, before.parent, before.source, before.source_text, before.edits, before.fit)
        assert after.group == 'Experiment α'
        assert after.name == before.name
        assert after.visible == before.visible
        np.testing.assert_equal(after.values, before.values)
    assert not restored[0].values.flags.writeable

    # Existing version-1 files have no organization metadata.
    if extension == 'json':
        content = json.loads(path.read_text())
        for item in content['datasets']:
            del item['group']
        path.write_text(json.dumps(content))
    else:
        with h5py.File(path, 'r+') as file:
            for group in file['datasets'].values():
                metadata = json.loads(group['metadata'][:].tobytes())
                del metadata['group']
                del group['metadata']
                group.create_dataset('metadata', data=np.frombuffer(json.dumps(metadata).encode(), dtype='u1'))
    legacy, _ = load_project(path)
    assert all(d.group == '' for d in legacy)
    assert legacy[1].parent == legacy[0].id


def test_removal_checks_all_retained_descendants():
    raw = parse_text('x,y\n0,1')
    child = raw.derived()
    grandchild = child.derived()
    datasets = [raw, child, grandchild]
    for ids in ([raw.id], [raw.id, child.id], [child.id]):
        with pytest.raises(ValueError, match='remaining derived copies'):
            remove_datasets(datasets, ids)
    assert remove_datasets(datasets, [grandchild.id]) == [raw, child]
    assert remove_datasets(datasets, [d.id for d in datasets]) == []


def test_search_selection_visibility_and_groups(window, monkeypatch):
    a = parse_text('x,y\n0,1\n1,', name='Alpha', source='/data/run.csv')
    b = a.derived()
    b.name = 'Beta'
    window.add_dataset(a)
    window.add_dataset(b)
    window.browser.selectAll()
    window.set_selected_visibility(False)
    assert not a.visible and not b.visible
    assert len(window.selected_datasets()) == 2
    window.set_selected_group('Trials')
    assert a.group == b.group == 'Trials'
    assert a.id == b.parent
    assert a.revision == b.revision == 0
    assert not a.values.flags.writeable

    window.dirty = False
    window.search.setText('alpha')
    assert window.browser.item(1).isHidden()
    assert window.selected_datasets() == [a]
    assert not window.dirty
    window.set_selected_visibility(True)
    assert a.visible and not b.visible
    window.search.clear()
    assert window.selected_datasets() == [a]  # Hidden selections do not return.
    window.browser.setCurrentRow(0)
    monkeypatch.setattr(W.QInputDialog, 'getText', lambda *a, **k: ('Renamed', True))
    window.rename_dataset()
    assert a.name == 'Renamed'
    assert a.id == b.parent
    assert a.source_text == 'x,y\n0,1\n1,'
    window.group_filter.setCurrentIndex(window.group_filter.findData('Trials'))
    window.set_selected_group('')
    assert window.browser.item(0).isHidden()
    assert window.selected_datasets() == []
    assert window.table.model() is None
    assert a.visible  # Filtering does not hide plotted data.
    window.group_filter.setCurrentIndex(0)
    window.search.setText('RUN.CSV')
    assert not window.browser.item(0).isHidden()
    assert not window.browser.item(1).isHidden()


def test_remove_ui_cancellation_lineage_and_empty_state(window, monkeypatch):
    raw = parse_text('x,y\n0,1')
    child = raw.derived()
    window.add_dataset(raw)
    window.add_dataset(child)
    window.browser.setCurrentRow(0)
    with pytest.raises(ValueError, match='remaining derived copies'):
        window.remove_selected()
    assert len(window.datasets) == 2
    window.browser.selectAll()
    monkeypatch.setattr(W.QMessageBox, 'question', lambda *a, **k: W.QMessageBox.StandardButton.Cancel)
    window.remove_selected()
    assert len(window.datasets) == 2
    monkeypatch.setattr(W.QMessageBox, 'question', lambda *a, **k: W.QMessageBox.StandardButton.Yes)
    window.remove_selected()
    assert window.datasets == []
    assert window.browser.count() == 0
    assert window.current() is None
    assert window.table.model() is None
    assert window.dirty
    window.add_dataset(parse_text('x,y\n0,2'))
    assert window.current() is window.datasets[0]


def test_invalid_group_metadata(tmp_path):
    path = tmp_path / 'invalid.json'
    save_project(path, [parse_text('x,y\n0,1')], {})
    payload = json.loads(path.read_text())
    payload['datasets'][0]['group'] = ['invalid']
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match='group must be text'):
        load_project(path)


@pytest.mark.parametrize('extension', ['json', 'h5'])
def test_browser_reopen_and_surviving_id_mapping(window, tmp_path, monkeypatch, extension):
    for name in ('First', 'Second', 'Third'):
        window.add_dataset(parse_text('x,y\n0,1', name=name))
    window.browser.setCurrentRow(1, C.QItemSelectionModel.SelectionFlag.ClearAndSelect)
    removed_id = window.current().id
    monkeypatch.setattr(W.QMessageBox, 'question', lambda *a, **k: W.QMessageBox.StandardButton.Yes)
    window.remove_selected()
    assert removed_id not in {d.id for d in window.datasets}
    window.browser.setCurrentRow(1, C.QItemSelectionModel.SelectionFlag.ClearAndSelect)
    assert window.current().name == 'Third'
    window.set_selected_group('Group A')
    window.set_selected_visibility(False)
    window.path = tmp_path / f'organized.{extension}'
    window.save()
    window.search.setText('no match')
    window.open_project(str(window.path))
    assert window.search.text() == ''
    assert window.current().name == 'Third'
    assert window.current().group == 'Group A'
    assert not window.current().visible
    assert not window.dirty
    assert 'Group A' in window.browser.item(1).text()
    window.browser.item(1).setCheckState(C.Qt.CheckState.Checked)
    assert window.datasets[1].visible


def test_rename_cancel_and_blank_name(window, monkeypatch):
    window.add_dataset(parse_text('x,y\n0,1', name='Original'))
    window.dirty = False
    monkeypatch.setattr(W.QInputDialog, 'getText', lambda *a, **k: ('Changed', False))
    window.rename_dataset()
    assert window.current().name == 'Original'
    assert not window.dirty
    monkeypatch.setattr(W.QInputDialog, 'getText', lambda *a, **k: ('  ', True))
    with pytest.raises(ValueError, match='cannot be blank'):
        window.rename_dataset()
    assert window.current().name == 'Original'
    assert not window.dirty


def test_organize_menu_select_all_and_assign_group(window, monkeypatch):
    window.add_dataset(parse_text('x,y\n0,1', name='Alpha'))
    window.add_dataset(parse_text('x,y\n0,2', name='Beta'))
    window.search.setText('no match')
    window.search.clear()
    window.organization_actions['Select all shown'].trigger()
    assert len(window.selected_datasets()) == 2
    assert window.current() is not None
    assert not window.organization_actions['Rename…'].isEnabled()
    monkeypatch.setattr(W.QInputDialog, 'getItem', lambda *a, **k: (' Runs ', True))
    window.organization_actions['Assign group…'].trigger()
    assert all(d.group == 'Runs' for d in window.datasets)
    window.organization_actions['Clear selection'].trigger()
    assert window.current() is None
    assert not window.organization_actions['Remove selected…'].isEnabled()


def test_raw_derived_filter_survives_regrouping(app):
    from rogi.analysis import analyze
    from rogi.browser_panel import filter_dataset_ids
    raw = parse_text('x (s),y (V)\n0,1\n1,3\n2,5', name='raw')
    copy = raw.derived()
    result = analyze(raw, [dict(operation='mean_subtract', parameters={})])
    datasets = [raw, copy, result]
    assert filter_dataset_ids(datasets, None, '', False, '', '', '', '', kind='raw') == {copy.id, result.id}
    assert filter_dataset_ids(datasets, None, '', False, '', '', '', '', kind='derived') == {raw.id}
    assert filter_dataset_ids(datasets, None, '', False, '', '', '', '') == set()
    window = MainWindow()
    try:
        for d in datasets:
            window.add_dataset(d)
        window.browser.selectAll()
        window.set_selected_group('Mixed')
        shown = lambda: [window.dataset_for_item(window.browser.item(i)) for i in range(window.browser.count())
                         if not window.browser.item(i).isHidden()]
        window.kind_filter.setCurrentIndex(window.kind_filter.findData('raw'))
        window.group_filter.setCurrentIndex(window.group_filter.findData('Mixed'))
        assert shown() == [raw]
        window.kind_filter.setCurrentIndex(window.kind_filter.findData('derived'))
        assert shown() == [copy, result]
        assert all(d.group == 'Mixed' for d in datasets)
    finally:
        window.external_dirty = False
        window.history.setClean()
        window.update_dirty()
        window.close()
