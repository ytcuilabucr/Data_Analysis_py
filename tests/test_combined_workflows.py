"""Cross-feature workflows with independent numerical and persistence checks."""
import time

import numpy as np
import pytest
from PySide6 import QtWidgets as W

from rogi.analysis_ui import AnalysisDialog
from rogi.core import Dataset
from rogi.project import load_project
from rogi.ui import ImportDialog, MainWindow


@pytest.fixture
def window(app):
    w = MainWindow()
    yield w
    if w.worker and w.worker.isRunning():
        w.worker.wait(15000)
        app.processEvents()
    w.dirty = False
    w.close()


def accept_centering(dialog):
    """Exercise real dialog controls while replacing only the modal wait."""
    dialog.add_step()
    dialog.preview_button.click()
    assert dialog.save_button.isEnabled(), dialog.status.text()
    dialog.save_button.click()
    return dialog.result()


@pytest.mark.parametrize('suffix', ['h5', 'json'])
def test_import_paste_analysis_fit_views_and_exports(window, app, tmp_path, monkeypatch, suffix):
    w = window
    source = tmp_path / 'input.csv'
    source.write_text('x,y\n0,1\n1,3\n2,5\n3,7\n4,9\n')
    preview = ImportDialog(source)
    preview.import_data()
    raw = preview.dataset
    preview.close()
    original = raw.values.copy()
    w.add_dataset(raw)
    w.project_actions['Editable copy'].trigger()
    edited = w.current()
    w.select_table_block(0, 1, 1, 1)
    W.QApplication.clipboard().setText('2\n4\n6\n8\n10')
    w.paste_action.trigger()
    np.testing.assert_array_equal(edited.values[:, 1], [2, 4, 6, 8, 10])
    w.undo_action.trigger()
    np.testing.assert_array_equal(edited.values, original)
    w.redo_action.trigger()
    assert edited.revision == 5

    monkeypatch.setattr(AnalysisDialog, 'exec', accept_centering)
    w.project_actions['Analysis pipeline…'].trigger()
    result = w.current()
    assert len(w.datasets) == 3 and result.parent == edited.id
    np.testing.assert_array_equal(result.values[:, 1], [-4, -2, 0, 2, 4])
    assert result.analysis['source']['revision'] == edited.revision
    w.show_statistics.setChecked(True)
    w.statistics_selected(0, 4)
    assert 'Count: 5' in w.stats_result.toPlainText()
    assert 'Mean: 0' in w.stats_result.toPlainText()

    w.show_fitting.setChecked(True)
    w.lower.setText('0')
    w.upper.setText('4')
    w.fitbutton.click()
    deadline = time.monotonic() + 15
    while w.worker.isRunning() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.01)
    assert not w.worker.isRunning()
    app.processEvents()
    assert result.fit['parameters']['slope'] == pytest.approx(2)
    assert result.fit['parameters']['intercept'] == pytest.approx(-4)
    w.add_panel()
    w.sync_x_control.setChecked(True)
    w.create_view('Analyzed panels')
    w.remove_panel()
    w.restore_view('Analyzed panels')
    assert len(w.panels) == 2

    w.path = tmp_path / f'workflow.{suffix}'
    assert w.save()
    w.open_project(w.path, confirm=False)
    restored = next(d for d in w.datasets if d.id == result.id)
    assert restored.analysis == result.analysis and restored.fit == result.fit
    assert len(w.panels) == 2 and 'Analyzed panels' in w.saved_views
    assert not w.history.canUndo()
    w.activate_dataset(result.id)
    for action, filename, kind in [('Export data…', 'data.csv', 'CSV (*.csv)'),
                                    ('Export fit…', 'fit.csv', 'CSV (*.csv)'),
                                    ('Export plot…', 'plot.svg', 'SVG (*.svg)')]:
        output = tmp_path / filename
        monkeypatch.setattr(W.QFileDialog, 'getSaveFileName', lambda *a, p=output, k=kind: (str(p), k))
        w.project_actions[action].trigger()
        assert output.stat().st_size > 0
    np.testing.assert_allclose(np.loadtxt(tmp_path / 'data.csv', delimiter=',', skiprows=1), result.values)
    assert 'slope' in (tmp_path / 'fit.csv').read_text()
    assert '<svg' in (tmp_path / 'plot.svg').read_text()
    np.testing.assert_array_equal(w.datasets[0].values, original)
    assert not w.datasets[0].values.flags.writeable


@pytest.mark.parametrize('suffix', ['h5', 'json'])
def test_image_profile_pipeline_edit_undo_and_reopen(window, tmp_path, monkeypatch, suffix):
    w = window
    raw = Dataset('Scan', ['Sample', 'X pixel', 'Y pixel', 'Height'],
                  [[i, i % 5, i // 5, 2 * (i % 5) + 10 * (i // 5)] for i in range(10)])
    original = raw.values.copy()
    w.add_dataset(raw)
    w.plot_tabs.setCurrentIndex(1)
    viewer = w.image_viewer
    viewer.cursor_positions[raw.id] = [2, 1]
    viewer.transpose.setChecked(True)
    w.create_view('Transposed scan')
    viewer.create_profile_button.click()
    profile = w.current()
    assert profile.parent == raw.id
    np.testing.assert_array_equal(profile.values[:, 1], [10, 12, 14, 16, 18])
    w.plot_tabs.setCurrentIndex(0)
    monkeypatch.setattr(AnalysisDialog, 'exec', accept_centering)
    w.project_actions['Analysis pipeline…'].trigger()
    derived = w.current()
    expected = derived.values.copy()
    np.testing.assert_array_equal(expected[:, 1], [-4, -2, 0, 2, 4])
    w.edit_cell(derived, 0, 1, '99')
    w.undo_action.trigger()
    np.testing.assert_array_equal(derived.values, expected)
    w.redo_action.trigger()
    assert derived.values[0, 1] == 99
    w.undo_action.trigger()
    w.restore_view('Transposed scan')
    assert w.plot_tabs.currentIndex() == 1 and viewer.transpose.isChecked()
    assert w.current().id == raw.id
    w.path = tmp_path / f'image-workflow.{suffix}'
    assert w.save()
    datasets, _ = load_project(w.path)
    assert datasets[1].instrument_metadata == profile.instrument_metadata
    assert datasets[2].analysis == derived.analysis
    assert datasets[2].parent == profile.id
    np.testing.assert_array_equal(datasets[2].values, expected)
    np.testing.assert_array_equal(datasets[0].values, original)
    w.open_project(w.path, confirm=False)
    w.restore_view('Transposed scan')
    assert w.image_viewer.transpose.isChecked()
    assert w.image_viewer.cursor_positions[raw.id] == [2, 1]


def test_all_project_commands_show_on_toolbar(window):
    w = window
    toolbar_labels = [a.text() for a in w.project_toolbar.actions()]
    for label in w.project_actions:
        assert label in toolbar_labels
    # The compact window wraps the bar onto rows rather than hiding commands.
    w.resize(520, 700)
    bar = w.project_toolbar
    bar.resize(520, bar.height())
    for action, button in bar.buttons.items():
        if action.isVisible():
            assert bar.rect().contains(button.geometry()), action.text()
    assert [a.text() for a in w.analysis_menu.actions()] == [
        'Analysis pipeline…', 'Apply pipeline preset…', 'Reopen analysis recipe…']
    assert w.analysis_menu.menuAction() in w.menuBar().actions()
    assert not w.project_actions['Apply pipeline preset…'].isEnabled()
    assert not w.project_actions['Reopen analysis recipe…'].isEnabled()
    w.add_dataset(Dataset('d', ['x', 'y'], np.array([[0., 1.], [1., 2.], [2., 3.]])))
    w.pipeline_presets = {'p': {}}
    w.pipeline_presets_changed()
    assert w.project_actions['Apply pipeline preset…'].isEnabled()
    assert not w.project_actions['Reopen analysis recipe…'].isEnabled()
