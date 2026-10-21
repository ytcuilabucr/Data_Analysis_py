import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('MPLCONFIGDIR', '/tmp/rogi-matplotlib-tests')
from copy import deepcopy
import numpy as np
import pytest
from PySide6 import QtCore as C, QtGui as G, QtWidgets as W, QtTest
from rogi.core import parse_text, fit_dataset
from rogi.project import load_project
from rogi.ui import MainWindow


@pytest.fixture
def window():
    app = W.QApplication.instance() or W.QApplication([])
    w = MainWindow()
    w.add_dataset(parse_text('x,y\n0,1\n1,3\n2,5\n3,7\n4,9', name='Raw', source='original.csv'))
    w.make_copy()
    yield w
    w.dirty = False
    w.close()


def edit(window, text):
    model = window.table_model
    assert model.setData(model.index(0, 1), text)


def test_edit_revision_provenance_and_fit_roundtrip(window):
    raw, d = window.datasets
    original = raw.values.copy()
    provenance = (d.id, d.parent, d.source, d.source_text)
    before = fit_dataset(d, 'Linear', 0, 4)
    d.fit = deepcopy(before)
    edit(window, '2')
    assert d.fit is None and d.revision == 1
    assert len(d.edits) == 1
    after = fit_dataset(d, 'Linear', 0, 4)
    d.fit = deepcopy(after)
    window.history.undo()
    assert d.values[0, 1] == 1 and d.revision == 0 and d.edits == []
    assert d.fit == before
    assert 'Redo Edit' in window.redo_action.text()
    window.history.redo()
    assert d.values[0, 1] == 2 and d.revision == 1
    assert d.fit == after
    window.history.undo()
    edit(window, '')  # branch: old redo and its fit must not survive
    assert not window.history.canRedo()
    assert np.isnan(d.values[0, 1]) and d.fit is None and d.revision == 1
    window.history.undo()
    assert d.fit == before
    assert (d.id, d.parent, d.source, d.source_text) == provenance
    np.testing.assert_equal(raw.values, original)
    assert not raw.values.flags.writeable


def test_stale_fit_is_not_restored_and_noop_not_recorded(window):
    d = window.current()
    d.fit = fit_dataset(d, 'Linear', 0, 4)
    d.fit['revision'] = 99
    count = window.history.count()
    edit(window, '1.0')
    assert window.history.count() == count
    edit(window, '3')
    window.history.undo()
    assert d.fit is None
    with pytest.raises(ValueError, match='read-only'):
        window.edit_cell(window.datasets[0], 0, 1, '8')
    count = window.history.count()
    with pytest.raises(ValueError):
        window.edit_cell(d, 0, 1, 'infinity')
    assert window.history.count() == count


def test_group_rename_and_bulk_visibility(window, monkeypatch):
    raw, d = window.datasets
    monkeypatch.setattr(W.QInputDialog, 'getText', lambda *a, **k: ('Renamed', True))
    window.rename_dataset()
    assert d.name == 'Renamed'
    assert 'Rename' in window.undo_action.text()
    window.history.undo()
    assert d.name == 'Raw (edited copy)'
    window.history.redo()
    window.browser.selectAll()
    count = window.history.count()
    window.set_selected_group('Runs')
    assert window.history.count() == count + 1
    assert raw.group == d.group == 'Runs'
    window.history.undo()
    assert raw.group == d.group == ''
    window.history.redo()
    window.set_selected_visibility(False)
    assert not raw.visible and not d.visible
    window.history.undo()
    assert raw.visible and d.visible
    window.browser.item(0).setCheckState(C.Qt.CheckState.Unchecked)
    assert not raw.visible
    window.history.undo()
    assert raw.visible


def test_remove_lineage_order_and_raw_restoration(window, monkeypatch):
    raw, d = window.datasets
    edit(window, '2')
    d.fit = fit_dataset(d, 'Linear', 0, 4)
    expected_fit = deepcopy(d.fit)
    window.make_copy()
    grandchild = window.current()
    window.browser.selectAll()
    monkeypatch.setattr(W.QMessageBox, 'question', lambda *a, **k: W.QMessageBox.StandardButton.Yes)
    window.remove_selected()
    assert not window.datasets
    window.history.undo()
    assert [x.id for x in window.datasets] == [raw.id, d.id, grandchild.id]
    assert d.fit == expected_fit and d.edits and d.revision == 1
    assert d.parent == raw.id and grandchild.parent == d.id
    assert not raw.values.flags.writeable
    window.history.redo()
    assert not window.datasets
    window.history.undo()
    window.history.undo()  # undo grandchild creation
    assert [x.id for x in window.datasets] == [raw.id, d.id]
    window.history.redo()
    assert window.datasets[-1] is grandchild


@pytest.mark.parametrize('extension', ['json', 'h5'])
def test_save_marker_roundtrip_and_open_clears_history(window, tmp_path, extension):
    window.path = tmp_path / f'history.{extension}'
    window.save()
    assert not window.dirty
    edit(window, '2')
    assert window.dirty
    window.history.undo()
    assert not window.dirty
    window.history.redo()
    window.save()
    assert not window.dirty
    window.history.undo()
    assert window.dirty
    window.history.redo()
    assert not window.dirty
    restored, _ = load_project(window.path)
    assert restored[1].revision == 1 and restored[1].edits
    window.open_project(str(window.path))
    assert not window.history.canUndo() and not window.history.canRedo()
    assert not window.dirty


def test_unrelated_changes_remain_dirty_after_undo(window, tmp_path):
    window.path = tmp_path / 'state.json'
    window.save()
    edit(window, '2')
    window.ax.set_xlim(1, 3)
    window.history.undo()
    assert window.dirty
    np.testing.assert_allclose(window.ax.get_xlim(), (1, 3))


def test_shortcuts_and_fit_lock(window):
    window.show()
    window.browser.setFocus()
    W.QApplication.processEvents()
    edit(window, '2')
    window.browser.setFocus()
    QtTest.QTest.keySequence(window.browser, G.QKeySequence(G.QKeySequence.StandardKey.Undo))
    assert window.current().values[0, 1] == 1
    QtTest.QTest.keySequence(window.browser, G.QKeySequence(G.QKeySequence.StandardKey.Redo))
    assert window.current().values[0, 1] == 2
    window.start_fit()
    assert not window.undo_action.isEnabled() and not window.redo_action.isEnabled()
    window.worker.wait(10000)
    W.QApplication.processEvents()
    assert window.undo_action.isEnabled()


def test_auto_visibility_and_filtered_group_undo(window):
    d = window.current()
    window.set_selected_visibility(False)
    window.x.setCurrentText('y')
    assert d.visible
    window.history.undo()
    assert not d.visible
    window.history.redo()
    assert d.visible
    window.set_selected_group('Runs')
    window.group_filter.setCurrentIndex(window.group_filter.findData('Runs'))
    window.set_selected_group('')
    window.history.undo()
    assert d.group == 'Runs'
    assert d.id == window.datasets[1].id


def test_failed_save_and_failed_open_preserve_history(window, tmp_path, monkeypatch):
    window.path = tmp_path / 'saved.json'
    window.save()
    edit(window, '2')
    count, index = window.history.count(), window.history.index()
    def fail(*args):
        raise OSError('disk failure')
    monkeypatch.setattr('rogi.ui.save_project', fail)
    with pytest.raises(OSError):
        window.save()
    assert window.dirty and not window.history.isClean()
    broken = tmp_path / 'bad.json'
    broken.write_text('{}')
    monkeypatch.setattr(window, 'confirm_discard', lambda: True)
    with pytest.raises(ValueError):
        window.open_project(str(broken))
    assert (window.history.count(), window.history.index()) == (count, index)
    window.history.undo()
    assert not window.dirty


def test_removed_parent_and_child_can_be_saved_after_undo(window, tmp_path, monkeypatch):
    window.browser.selectAll()
    monkeypatch.setattr(W.QMessageBox, 'question', lambda *a, **k: W.QMessageBox.StandardButton.Yes)
    window.remove_selected()
    window.history.undo()
    window.path = tmp_path / 'restored.h5'
    window.save()
    datasets, _ = load_project(window.path)
    assert datasets[1].parent == datasets[0].id
    assert not datasets[0].values.flags.writeable
    assert datasets[0].source_text == window.datasets[0].source_text
