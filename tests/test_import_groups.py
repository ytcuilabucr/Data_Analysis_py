from copy import deepcopy

import numpy as np
from PySide6 import QtWidgets as W

from rogi.core import parse_dat
from rogi.grouping import import_destinations, path_label
from rogi.project import save_project, load_project
from rogi.ui import ImportDialog, ImportGroupDialog, MainWindow

SIZE = 'Scan[1].Size[1]'
RATE = 'Scan[1].Rate[1]'


def scan(size='5 nm', rate='1 Hz'):
    return parse_dat(f'[Scan]\nSize: {size}\nRate: {rate}\n[Data]\nx\ty\n1\t2\n')


def grouped(size='5 nm', rate='1 Hz'):
    d = scan(size, rate)
    d.group_path = [{'field': SIZE, 'value': size}, {'field': RATE, 'value': rate}]
    d.group = path_label(d.group_path)
    return d


def test_suggests_deepest_match_and_preserves_paths(app):
    existing = [grouped(), grouped('10 nm')]
    dialog = ImportGroupDialog(scan(), existing)
    assert dialog.selected_path() == existing[0].group_path
    assert 'Matching metadata' in dialog.suggestion.text()
    dialog.child_name.setText('new/child')
    selected = dialog.selected_path()
    assert selected[-1] == {'field': None, 'value': 'new/child'}
    assert len(existing[0].group_path) == 2
    dialog.close()
    # Unknown rate still matches the parent, but never a conflicting child.
    dialog = ImportGroupDialog(scan(rate='3 Hz'), existing)
    assert dialog.selected_path() == existing[0].group_path[:1]
    dialog.close()


def test_manual_groups_metadata_ties_and_missing(app):
    a, b = scan(), scan('10 nm')
    a.group, b.group = 'folder/one', 'folder/two'
    dialog = ImportGroupDialog(scan(), [a, b])
    assert dialog.selected_path() == [{'field': None, 'value': 'folder/one'}]
    dialog.close()
    a, b = grouped(), grouped()
    a.group_path.insert(0, {'field': None, 'value': 'A'})
    b.group_path.insert(0, {'field': None, 'value': 'B'})
    dialog = ImportGroupDialog(scan(), [a, b])
    assert dialog.selected_path() == []
    assert 'multiple subgroups' in dialog.suggestion.text()
    dialog.close()
    dialog = ImportGroupDialog(scan('', ''), [a, b])
    assert dialog.selected_path() == []
    assert 'No confident' in dialog.suggestion.text()
    dialog.close()


def test_conflicting_metadata_not_suggested():
    a, b = scan(), scan('10 nm', '2 Hz')
    a.group, b.group = 'A', 'B'
    assert all(not evidence for _, evidence in import_destinations(scan('5 nm', '2 Hz'), [a, b]))


def test_import_existing_hdf5_override_cancel_undo_save(tmp_path, monkeypatch, app):
    target = tmp_path / 'existing.h5'
    original = grouped()
    save_project(target, [original], {'title': 'Keep title'})
    source = tmp_path / 'additional.dat'
    source.write_text('[Scan]\nSize: 5 nm\nRate: 1 Hz\n[Data]\nx\ty\n3\t4\n')
    monkeypatch.setattr(W.QFileDialog, 'getOpenFileName', lambda *a: (str(source), ''))
    def preview(dialog):
        dialog.import_data()
        return dialog.result()
    monkeypatch.setattr(ImportDialog, 'exec', preview)
    window = MainWindow()
    try:
        window.open_project(target)
        before = target.read_bytes()
        monkeypatch.setattr(ImportGroupDialog, 'exec', lambda dialog: 0)
        window.import_file()
        assert len(window.datasets) == 1 and not window.dirty
        assert target.read_bytes() == before
        chosen = deepcopy(original.group_path[:1])
        def choose(dialog):
            assert dialog.selected_path() == original.group_path
            dialog.destination.setCurrentIndex(dialog.destination.findData(chosen))
            return 1
        monkeypatch.setattr(ImportGroupDialog, 'exec', choose)
        window.search.setText('invisible')
        window.import_file()
        assert len(window.datasets) == 2 and window.dirty
        assert window.datasets[-1].group_path == chosen
        assert window.current().id == window.datasets[-1].id
        assert target.read_bytes() == before
        window.history.undo()
        assert len(window.datasets) == 1
        window.history.redo()
        assert len(window.datasets) == 2
        window.save()
        loaded, settings = load_project(target)
        assert len(loaded) == 2 and loaded[0].id == original.id
        np.testing.assert_array_equal(loaded[0].values, original.values)
        assert loaded[0].group_path == original.group_path
        assert loaded[1].group_path == chosen
        assert loaded[1].instrument_metadata == window.datasets[1].instrument_metadata
        assert settings['title'] == 'Keep title'
    finally:
        window.dirty = False
        window.close()
