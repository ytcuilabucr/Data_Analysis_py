from pathlib import Path
import numpy as np
import pytest
from PySide6 import QtCore as C, QtWidgets as W
from rogi.files import (natural_key, scan_folder, format_name, sort_by_x, read_data_file,
                        read_with_template, loaded_sources, folder_group, file_preview)
from rogi.files_panel import FilesPanel, PATH_ROLE
from rogi.dialogs import ImportDialog
from rogi.project import save_project
from rogi.ui import MainWindow


def sweep(path, rows='1\t2\n3\t4\n'):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('x\ty\tz\n' + ''.join(line + '\t0\n' for line in rows.splitlines()))
    return path


@pytest.fixture
def window():
    window = MainWindow()
    yield window
    window.dirty = False
    window.close()


def test_natural_order_and_kind_filters(tmp_path):
    for name in ('run_10.dat', 'run_2.dat', 'run_1.dat', 'notes.csv', '.hidden.dat', 'image.png'):
        (tmp_path / name).write_text('x')
    (tmp_path / 'sub').mkdir()
    (tmp_path / 'sub' / 'run_3.dat').write_text('x')
    names = [p.name for p in scan_folder(tmp_path)]
    assert names == ['notes.csv', 'run_1.dat', 'run_2.dat', 'run_10.dat']
    assert [p.name for p in scan_folder(tmp_path, ['table'])] == ['notes.csv']
    assert [p.name for p in scan_folder(tmp_path, ['dat'], recursive=True)][-1] == 'run_3.dat'
    assert sorted(['a10', 'a2', 'A1'], key=natural_key) == ['A1', 'a2', 'a10']


def test_name_patterns():
    path = Path('/data/day1/D181_BGsweep_00015.dat')
    assert format_name('', path, 0) == 'D181_BGsweep_00015'
    assert format_name('Scan_{n}', path, 3) == 'Scan_3'
    assert format_name('BG_{num}', path, 0) == 'BG_00015'
    assert format_name('{folder}/{stem}', path, 0) == 'day1/D181_BGsweep_00015'
    with pytest.raises(ValueError, match='Unknown name pattern'):
        format_name('{bogus}', path, 0)


def test_sort_by_x_records_the_change(tmp_path):
    dataset = read_data_file(sweep(tmp_path / 'down.dat', '3\t30\n1\t10\n2\t20\n'))
    assert sort_by_x(dataset)
    np.testing.assert_array_equal(dataset.values[:, 1], [10, 20, 30])
    assert not dataset.values.flags.writeable
    assert 'sorted by x' in dataset.comments
    assert not sort_by_x(dataset)


def test_template_applies_chosen_columns(tmp_path):
    template = dict(delimiter='\t', header=True, columns=['x', 'z'])
    dataset = read_with_template(sweep(tmp_path / 'a.dat'), template)
    assert dataset.columns == ['x', 'z']
    assert dataset.source == str((tmp_path / 'a.dat').resolve())
    (tmp_path / 'b.dat').write_text('x\ty\n1\t2\n')
    with pytest.raises(ValueError, match='Missing column'):
        read_with_template(tmp_path / 'b.dat', template)


def test_helpers_for_loaded_marks_groups_and_preview(tmp_path):
    path = sweep(tmp_path / 'sub' / 'a.dat')
    dataset = read_data_file(path)
    assert loaded_sources([dataset]) == {str(path.resolve())}
    assert folder_group(path, tmp_path) == 'sub'
    assert folder_group(tmp_path / 'b.dat', tmp_path) == ''
    summary, image = file_preview(path)
    assert 'a.dat' in summary and 'x\ty\tz' in summary and image is None
    assert 'Tab-separated table · 2 rows' in summary and 'Channels: x, y, z' in summary
    bad = tmp_path / 'bad.csv'
    bad.write_text('')
    assert 'Cannot be loaded' in file_preview(bad)[0]


def test_panel_lists_marks_and_detects_new_files(tmp_path, app):
    sweep(tmp_path / 'run_1.dat')
    panel = FilesPanel()
    requests = []
    panel.load_requested.connect(lambda paths, options: requests.append((paths, options)))
    panel.set_folder(str(tmp_path))
    assert len(panel.file_items()) == 1
    loaded = str((tmp_path / 'run_1.dat').resolve())
    panel.set_loaded({loaded})
    panel.hide_loaded.setChecked(True)
    assert panel.file_items()[0].isHidden()
    panel.hide_loaded.setChecked(False)
    panel.watch.setChecked(True)
    new = sweep(tmp_path / 'run_2.dat')
    panel.refresh()
    assert str(new.resolve()) in panel.new and not requests  # waits until the size settles
    panel.refresh()
    assert requests and requests[0][0] == [str(new.resolve())]
    assert requests[0][1]['grouping'] == 'last' and not requests[0][1]['preview']
    panel.deleteLater()



def test_panel_layout_types_subfolders_sorting_and_options(tmp_path, app):
    from test_nanonis import scan_bytes
    sweep(tmp_path / 'run_10.dat')
    sweep(tmp_path / 'run_2.dat', '1\t2\n3\t4\n5\t6\n')
    sweep(tmp_path / 'day2' / 'run_1.dat')
    (tmp_path / 'scan.sxm').write_bytes(scan_bytes())
    panel = FilesPanel()
    panel.set_folder(str(tmp_path))
    names = lambda: [item.text(0) for item in panel.file_items() if not item.isHidden()]
    assert names() == ['run_2.dat', 'run_10.dat', 'scan.sxm']
    panel.recursive.setChecked(True)
    folder = panel.list.topLevelItem(0)
    assert folder.text(0) == 'day2' and folder.data(0, PATH_ROLE) is None and folder.child(0).text(0) == 'run_1.dat'
    assert str(tmp_path / 'day2') in panel.watcher.directories()
    panel.search.setText('day2')
    assert names() == ['run_1.dat'] and not folder.isHidden()
    panel.search.clear()
    panel.list.sortByColumn(2, C.Qt.SortOrder.DescendingOrder)
    assert names()[0] == 'scan.sxm'
    panel.kind_actions['sxm'].setChecked(False)
    assert 'scan.sxm' not in names() and panel.types_button.text() != 'All types'
    panel.kind_actions['sxm'].setChecked(True)
    assert panel.types_button.text() == 'All types'

    assert not panel.preview_box.isVisibleTo(panel)
    item = next(item for item in panel.file_items() if item.text(0) == 'scan.sxm')
    panel.list.setCurrentItem(item)
    assert panel.preview_box.isVisibleTo(panel) and panel.thumbnail.isVisibleTo(panel)
    assert 'Nanonis SXM' in panel.preview.toPlainText()
    item = next(item for item in panel.file_items() if item.text(0) == 'run_2.dat')
    panel.list.setCurrentItem(item)
    assert not panel.thumbnail.isVisibleTo(panel) and '3 rows' in panel.preview.toPlainText()

    assert not panel.options_box.isVisibleTo(panel)
    assert panel.options_summary.text() == 'Names from files · Group: choose once · all columns'
    panel.name_pattern.setText('Scan_{n}')
    panel.grouping.setCurrentIndex(1)
    panel.sort_x.setChecked(True)
    assert panel.options_summary.text() == 'Names Scan_{n} from 0 · Group: subfolder names · all columns · sort by X'
    panel.options_toggle.setChecked(True)
    assert panel.options_box.isVisibleTo(panel)
    panel.deleteLater()

def test_load_several_files_is_one_step(window, tmp_path):
    paths = [sweep(tmp_path / f'BGsweep_{i:05}.dat') for i in (10, 9)]
    window.files_panel.set_folder(str(tmp_path))
    window.files_panel.name_pattern.setText('Scan_{n}')
    window.import_paths(paths, **window.files_panel.options())
    assert [d.name for d in window.datasets] == ['Scan_0', 'Scan_1']
    assert window.datasets[0].source.endswith('BGsweep_00009.dat')
    assert window.files_panel.start_number.value() == 2
    marked = window.files_panel.file_items()
    assert all(item.data(0, PATH_ROLE) in window.files_panel.loaded for item in marked)
    window.history.undo()
    assert window.datasets == []
    assert not window.files_panel.loaded


def test_preview_first_file_applies_to_the_rest(window, tmp_path, monkeypatch):
    paths = [sweep(tmp_path / f'run_{i}.dat') for i in (1, 2)]
    def choose(dialog):
        dialog.columns.item(1).setCheckState(C.Qt.CheckState.Unchecked)
        dialog.import_data()
        return dialog.result()
    monkeypatch.setattr(ImportDialog, 'exec', choose)
    window.import_paths(paths, preview=True)
    assert [d.columns for d in window.datasets] == [['x', 'z'], ['x', 'z']]


def test_bad_files_are_skipped_and_reported(window, tmp_path, monkeypatch):
    good = sweep(tmp_path / 'good.dat')
    bad = tmp_path / 'bad.csv'
    bad.write_text('x,y\n1,oops\n')
    warnings = []
    monkeypatch.setattr(W.QMessageBox, 'warning', lambda *a: warnings.append(a[-1]))
    window.import_paths([good, bad])
    assert [d.name for d in window.datasets] == ['good']
    assert 'bad.csv' in warnings[0]


def test_folder_grouping_and_open_routes_projects(window, tmp_path, monkeypatch):
    sweep(tmp_path / 'day2' / 'a.dat')
    window.import_paths([tmp_path / 'day2' / 'a.dat'], grouping='folders', folder=str(tmp_path))
    assert window.datasets[0].group == 'day2'
    project = tmp_path / 'saved.h5'
    save_project(project, [read_data_file(tmp_path / 'day2' / 'a.dat')], {'title': 'Saved'})
    window.dirty = False
    with pytest.raises(ValueError, match='one project'):
        window.open_files([str(project), str(tmp_path / 'day2' / 'a.dat')])
    window.open_files([str(project)])
    assert window.path == project and window.title.text() == 'Saved'


def test_folder_is_remembered_per_project(window, tmp_path):
    data = tmp_path / 'data'
    data.mkdir()
    window.path = tmp_path / 'p.h5'
    window.files_panel.set_folder(str(data))
    other = MainWindow()
    try:
        other.path = window.path
        from rogi.project_actions import restore_files_folder
        restore_files_folder(other)
        assert other.files_panel.folder == str(data)
    finally:
        other.close()
