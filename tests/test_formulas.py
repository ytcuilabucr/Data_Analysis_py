import numpy as np
import pytest
from PySide6 import QtWidgets as W
from rogi.core import Dataset, parse_text, fit_dataset
from rogi.formulas import evaluate, formula_column, add_column, remove_last_column
from rogi.project import save_project, load_project


@pytest.fixture
def data():
    return Dataset('d', ['Time (s)', 'Current (A)', 'V'], [[0, 1, 2], [1, np.nan, 0], [2, 3, -1]], raw=False)


@pytest.mark.parametrize('formula,expected', [
    ('[Current (A)] * V', [2, np.nan, -3]),
    ('c2 * 1e9', [1e9, np.nan, 3e9]),
    ('V^2 + V**2', [8, 0, 2]),
    ('c2 / max(c2)', [1 / 3, np.nan, 1]),
    ('min(c1, V)', [0, 0, -1]),
    ('mean(V) - V', [-2 + 1 / 3, 1 / 3, 4 / 3]),
    ('row', [1, 2, 3]),
    ('5', [5, 5, 5]),
    ('sqrt(abs(V)) * cos(0) + 0 * pi', [np.sqrt(2), 0, 1]),
    ('[Time (s)] % 2', [0, 1, 0]),
])
def test_formulas_compute_row_by_row(data, formula, expected):
    values, invalid = evaluate(data, formula)
    np.testing.assert_allclose(values, expected)
    assert invalid == 0


def test_undefined_results_are_missing_and_counted(data):
    values, invalid = evaluate(data, 'log(V) + c2')
    assert np.isnan(values[1:]).all() and invalid == 1  # Row 2 was already missing.
    values, invalid = evaluate(data, '1 / 0 + 10 ** 1000')
    assert np.isnan(values).all() and invalid == 3


@pytest.mark.parametrize('formula,message', [
    ('__import__("os").system("true")', 'Unknown function'), ('V.real', 'Only arithmetic'),
    ('(lambda: 1)()', 'Unknown function'), ('V > 1', 'Only arithmetic'), ('"text"', 'Only arithmetic'),
    ('[Nope]', 'No column named'), ('c4', 'has 3 columns'), ('Current', 'Unknown name'),
    ('sqrt', 'is a function'), ('(1', 'not valid'), ('', 'Enter a formula'),
    ('max(c1, c2, V)', 'min and max'), ('-' * 5000 + '1', 'too deeply'), ('1' + '0' * 400, 'too large'),
])
def test_unsafe_or_wrong_formulas_are_refused(data, formula, message):
    with pytest.raises(ValueError, match=message):
        evaluate(data, formula)


def test_column_name_unit_and_round_trip(data, tmp_path):
    with pytest.raises(ValueError, match='already exists'):
        formula_column(data, 'V', 'c1')
    with pytest.raises(ValueError, match='Enter a name'):
        formula_column(data, ' ', 'c1')
    power = formula_column(data, 'Power (W)', '[Current (A)] * V')
    assert power['unit'] == 'W'
    assert formula_column(data, 'P', 'c2 * V', 'mW')['unit'] == 'mW'
    add_column(data, power)
    assert data.columns[-1] == 'Power (W)' and data.column_units[-1] == 'W'
    assert data.formulas == [dict(column='Power (W)', formula='[Current (A)] * V', unit='W', revision=0)]
    for name in ('p.json', 'p.h5'):
        save_project(tmp_path / name, [data], {})
        loaded = load_project(tmp_path / name)[0][0]
        assert loaded.formulas == data.formulas
        np.testing.assert_equal(loaded.values, data.values)
    assert data.derived().formulas == data.formulas
    data.xcol = data.ycol = 3
    remove_last_column(data, power)
    assert data.columns == ['Time (s)', 'Current (A)', 'V'] and data.formulas == [] and data.ycol == 2


def test_raw_data_is_never_changed():
    raw = parse_text('a,b\n1,2')
    with pytest.raises(ValueError, match='read-only'):
        add_column(raw, formula_column(raw, 'c', 'a + b'))


def test_invalid_records_are_rejected():
    with pytest.raises(ValueError, match='formula column records'):
        Dataset('d', ['a', 'b'], [[1, 2]], formulas=[dict(column='c')])


@pytest.fixture
def window():
    from rogi.ui import MainWindow
    w = MainWindow()
    w.add_dataset(parse_text('x,y\n0,1\n1,3\n2,5\n3,7\n4,9', name='Raw'))
    yield w
    w.dirty = False
    w.close()


def accept_with(monkeypatch, formula, name):
    from rogi.dialogs import FormulaDialog
    def exec_(dialog):
        dialog.formula.setText(formula)
        dialog.name.setText(name)
        assert dialog.column is not None, dialog.status.text()
        return W.QDialog.DialogCode.Accepted
    monkeypatch.setattr(FormulaDialog, 'exec', exec_)


def test_formula_on_raw_data_makes_a_copy(window, monkeypatch):
    accept_with(monkeypatch, 'x * y', 'Product')
    window.formula_column()
    raw, copy = window.datasets
    assert raw.columns == ['x', 'y'] and not copy.raw and copy.parent == raw.id
    np.testing.assert_equal(copy.values[:, 2], [0, 3, 10, 21, 36])
    window.history.undo()
    assert window.datasets == [raw]


def test_formula_on_editable_data_is_added_in_place_and_undoable(window, monkeypatch):
    window.make_copy()
    d = window.current()
    d.fit = fit_dataset(d, 'Linear', 0, 4)
    fit = d.fit
    accept_with(monkeypatch, 'y - 2 * x', 'Offset')
    window.formula_column()
    assert d.columns == ['x', 'y', 'Offset'] and d.fit == fit
    np.testing.assert_equal(d.values[:, 2], 1)
    assert window.table_model.columnCount() == 3 and window.y.count() == 3
    window.history.undo()
    assert d.columns == ['x', 'y'] and d.formulas == [] and window.table_model.columnCount() == 2
    window.history.redo()
    assert d.columns[-1] == 'Offset' and window.y.count() == 3


def test_dialog_reports_problems_and_preview(window):
    from rogi.dialogs import FormulaDialog
    dialog = FormulaDialog(window.datasets[0], window)
    ok = dialog.buttons.button(W.QDialogButtonBox.StandardButton.Ok)
    assert not ok.isEnabled()
    dialog.formula.setText('y / (x - 1)')
    assert 'Enter a name' in dialog.status.text() and not ok.isEnabled()
    dialog.name.setText('Ratio')
    assert ok.isEnabled() and '1 of 5 rows missing' in dialog.status.text()
    dialog.insert_column(dialog.columns.item(0))
    assert dialog.formula.text().endswith('[x]')
    dialog.deleteLater()
