import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('MPLCONFIGDIR', '/tmp/rogi-matplotlib-tests')
from copy import deepcopy
import csv
import io
import numpy as np
import pytest
from PySide6 import QtCore as C, QtGui as G, QtWidgets as W, QtTest
from rogi.clipboard import MIME, copy_table, parse_paste
from rogi.core import parse_text, fit_dataset
from rogi.project import load_project
from rogi.ui import MainWindow


@pytest.fixture
def window():
    app = W.QApplication.instance() or W.QApplication([])
    w = MainWindow()
    w.add_dataset(parse_text('x,y,z\n0,1,10\n1,3,20\n2,5,30\n3,7,40\n4,9,50'))
    w.make_copy()
    yield w
    W.QApplication.clipboard().clear()
    w.dirty = False
    w.close()


def paste(window, text, row=0, column=0):
    window.select_table_block(row, column, 1, 1)
    W.QApplication.clipboard().setText(text)
    window.paste_selection()


def test_copy_with_headers_and_missing(window):
    d = window.current()
    d.edit(1, 1, '')
    window.select_table_block(0, 0, 2, 2)
    window.copy_selection()
    mime = W.QApplication.clipboard().mimeData()
    assert mime.hasFormat(MIME)
    assert list(csv.reader(io.StringIO(mime.text()), delimiter='\t')) == [
        ['x', 'y'], ['0.0', '1.0'], ['1.0', '']]
    window.select_table_block(2, 1, 1, 1)
    window.paste_selection()  # own headers can target differently named channels
    np.testing.assert_equal(d.values[2:4, 1:], [[0, 1], [1, np.nan]])


@pytest.mark.parametrize('text', ['2\t4\n3\t6\n', '2,4\r\n3,6\r\n', 'x,y\n2,4\n3,6'])
def test_atomic_paste_fit_revision_and_undo(window, text):
    d = window.current()
    old = d.values.copy()
    d.fit = fit_dataset(d, 'Linear', 0, 4)
    old_fit = deepcopy(d.fit)
    index = window.history.index()
    paste(window, text)
    assert window.history.index() == index + 1
    assert 'Paste 2 × 2' in window.undo_action.text()
    assert d.revision == 4 and len(d.edits) == 4 and d.fit is None
    np.testing.assert_equal(d.values[:2, :2], [[2, 4], [3, 6]])
    window.history.undo()
    np.testing.assert_equal(d.values, old)
    assert d.revision == 0 and d.edits == [] and d.fit == old_fit
    assert window.copy_action.isEnabled()  # selection survives history refresh
    window.history.redo()
    assert d.revision == 4 and d.fit is None


@pytest.mark.parametrize('text,message', [
    ('1\tbad\n2\tinf', '2 invalid cell'),
    ('1,2\n3', 'Paste row 2'),
    ('1,2,3,4', 'does not fit'),
    ('1\n2\n3\n4\n5\n6', 'does not fit'),
    ('1,1e309', 'invalid cell'),
    ('wrong,headers\n1,2', 'invalid cell'),
    ('"unterminated', 'Invalid clipboard'),
    ('', 'no table data'),
])
def test_invalid_paste_is_all_or_nothing(window, text, message):
    d = window.current()
    original = d.values.copy()
    d.fit = fit_dataset(d, 'Linear', 0, 4)
    fit = deepcopy(d.fit)
    count = window.history.count()
    with pytest.raises(ValueError, match=message):
        paste(window, text)
    np.testing.assert_equal(d.values, original)
    assert d.revision == 0 and d.edits == [] and d.fit == fit
    assert window.history.count() == count


def test_error_locations_and_missing_tokens(window):
    with pytest.raises(ValueError, match='dataset row 3, column 3') as error:
        paste(window, '1\tnope', 2, 1)
    assert 'Paste row 1, column 2' in str(error.value)
    paste(window, '\tNA\nNaN\tN/A', 1, 1)
    assert np.isnan(window.current().values[1:3, 1:3]).all()


def test_copy_raw_and_reject_paste(window):
    window.browser.setCurrentRow(0, C.QItemSelectionModel.SelectionFlag.ClearAndSelect)
    raw = window.current()
    original = raw.values.copy()
    window.select_table_block(0, 0, 1, 2)
    assert window.copy_action.isEnabled()
    assert not window.paste_action.isEnabled()
    window.copy_selection()
    with pytest.raises(ValueError, match='read-only'):
        window.paste_selection()
    np.testing.assert_equal(raw.values, original)
    assert not raw.values.flags.writeable


def test_non_rectangular_selection_and_noop(window):
    model = window.table.model()
    window.table.selectionModel().select(model.index(0, 0), C.QItemSelectionModel.SelectionFlag.ClearAndSelect)
    window.table.selectionModel().select(model.index(1, 1), C.QItemSelectionModel.SelectionFlag.Select)
    W.QApplication.clipboard().setText('keep')
    with pytest.raises(ValueError, match='rectangular'):
        window.copy_selection()
    assert W.QApplication.clipboard().text() == 'keep'
    with pytest.raises(ValueError, match='rectangular'):
        window.paste_selection()
    count = window.history.count()
    paste(window, '0\t1\n1\t3')
    assert window.history.count() == count
    assert window.current().revision == 0


def test_single_column_header_with_comma(window):
    d = window.current()
    d.columns[1] = 'Signal, volts'
    window.select_table_block(0, 1, 2, 1)
    window.copy_selection()
    window.select_table_block(2, 1, 1, 1)
    window.paste_selection()
    np.testing.assert_equal(d.values[2:4, 1], [1, 3])


def test_shortcut_dispatch_and_clipboard(window, monkeypatch, tmp_path):
    window.show()
    window.show_table_button.click()  # table shortcuts act on the visible table
    W.QApplication.processEvents()
    window.select_table_block(0, 0, 2, 2)
    window.table.setFocus()
    QtTest.QTest.keySequence(window.table, G.QKeySequence(G.QKeySequence.StandardKey.Copy))
    assert W.QApplication.clipboard().mimeData().hasFormat(MIME)
    window.select_table_block(2, 0, 1, 1)
    QtTest.QTest.keySequence(window.table, G.QKeySequence(G.QKeySequence.StandardKey.Paste))
    np.testing.assert_equal(window.current().values[2:4, :2], [[0, 1], [1, 3]])
    QtTest.QTest.keySequence(window.table, G.QKeySequence(G.QKeySequence.StandardKey.Undo))
    assert window.current().values[2, 0] == 2
    QtTest.QTest.keySequence(window.table, G.QKeySequence(G.QKeySequence.StandardKey.Redo))
    assert window.current().values[2, 0] == 0
    window.path = tmp_path / 'shortcuts.json'
    QtTest.QTest.keySequence(window.table, G.QKeySequence(G.QKeySequence.StandardKey.Save))
    assert window.path.exists() and not window.dirty
    destination = tmp_path / 'as.h5'
    monkeypatch.setattr(W.QFileDialog, 'getSaveFileName', lambda *a, **k: (str(destination), 'HDF5'))
    QtTest.QTest.keySequence(window.table, G.QKeySequence(G.QKeySequence.StandardKey.SaveAs))
    assert destination.exists()
    calls = []
    monkeypatch.setattr(W.QFileDialog, 'getOpenFileNames', lambda *a, **k: (calls.append(a[1]) or [], ''))
    QtTest.QTest.keySequence(window.table, G.QKeySequence(G.QKeySequence.StandardKey.Open))
    assert calls == ['Open']
    restored, _ = load_project(destination)
    assert restored[1].revision == window.current().revision


def test_paste_disabled_during_fit(window):
    window.select_table_block(0, 0, 1, 1)
    window.start_fit()
    assert not window.paste_action.isEnabled()
    assert not window.project_actions['Open…'].isEnabled()
    window.worker.wait(10000)
    W.QApplication.processEvents()
    assert window.paste_action.isEnabled()
    assert window.project_actions['Open…'].isEnabled()


def test_numeric_column_names_do_not_consume_data(window):
    d = window.current()
    d.columns[:2] = ['1', '2']
    paste(window, '1,2\n3,4')
    np.testing.assert_equal(d.values[:2, :2], [[1, 2], [3, 4]])
    window.select_table_block(0, 0, 2, 2)
    window.copy_selection()
    window.select_table_block(2, 0, 1, 1)
    window.paste_selection()
    np.testing.assert_equal(d.values[2:4, :2], [[1, 2], [3, 4]])


def test_failed_paste_preserves_redo_and_clean_state(window, tmp_path):
    window.path = tmp_path / 'clean.json'
    window.save()
    paste(window, '12')
    window.history.undo()
    assert not window.dirty and window.history.canRedo()
    with pytest.raises(ValueError):
        paste(window, 'invalid')
    assert not window.dirty and window.history.canRedo()
    window.history.redo()
    assert window.current().values[0, 0] == 12


def test_paste_redo_restores_fit_for_pasted_revision(window):
    paste(window, '1.1\n3.1', 0, 1)
    d = window.current()
    d.fit = fit_dataset(d, 'Linear', 0, 4)
    fit = deepcopy(d.fit)
    window.history.undo()
    assert d.fit is None
    window.history.redo()
    assert d.fit == fit
