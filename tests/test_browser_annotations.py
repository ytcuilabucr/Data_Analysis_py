"""Annotations and browser views never change scientific grouping or plot state."""
import json
import pytest
from PySide6 import QtCore as C, QtWidgets as W
from rogi.core import parse_text, parse_dat
from rogi.metadata import acquisition_timestamp
from rogi.project import save_project, load_project
from rogi.ui import MainWindow


@pytest.fixture
def window():
    app = W.QApplication.instance() or W.QApplication([])
    w = MainWindow()
    yield w
    w.dirty = False
    w.close()


def dated(name, date):
    return parse_dat(f'[Instrument]\nBias: 3 V\n[Data]\nTime\tTime_Timestamp\tx\ty\n{date}_12:00:00\t12\t0\t1', name=name)


@pytest.mark.parametrize('extension', ['json', 'h5'])
def test_annotations_roundtrip(window, tmp_path, extension):
    a = dated('A', '2026/01/02')
    window.add_dataset(a)
    window.annotate_selected('favorite', True)
    window.annotate_selected('tags', ['α', 'trial'])
    window.annotate_selected('comments', 'First line\nSecond line')
    window.history.undo()
    assert a.comments == ''
    window.history.redo()
    assert a.comments == 'First line\nSecond line'
    assert a.raw and not a.values.flags.writeable and a.revision == 0
    child = a.derived()
    child.tags.append('child')
    assert a.tags == ['α', 'trial']
    path = tmp_path / f'project.{extension}'
    save_project(path, [a, child], {})
    loaded, _ = load_project(path)
    assert loaded[0].favorite and loaded[0].tags == a.tags and loaded[0].comments == a.comments
    assert loaded[1].parent == a.id


def test_combined_filters_sort_and_history(window):
    a, b = dated('A', '2026/01/02'), dated('B', '2026/02/03')
    c = parse_text('x,y\n0,1', name='C')
    for d in (a, b, c):
        d.group_path = [{'field': 'sample', 'value': 'one'}]
        d.group = 'sample: one'
        window.add_dataset(d)
    window.browser.selectAll()
    window.annotate_selected('favorite', True)
    window.annotate_selected('tags', ['keep'])
    groups = [(d.group, list(d.group_path)) for d in window.datasets]
    visibility = [d.visible for d in window.datasets]
    window.history.setClean()
    window.browser.sort_column(3)
    assert window.dataset_for_item(window.browser.item(0)) is c
    window.browser.sort_column(2)
    window.favorites_filter.setChecked(True)
    window.tag_filter.setText('keep')
    window.metadata_filter.setText('Bias')
    window.date_from.setText('2026-01-01')
    window.date_to.setText('2026-01-31')
    assert [window.dataset_for_item(window.browser.item(i)) for i in range(3)
            if not window.browser.item(i).isHidden()] == [a]
    assert [(d.group, d.group_path) for d in window.datasets] == groups
    assert [d.visible for d in window.datasets] == visibility
    assert window.history.isClean()
    window.activate_dataset(a.id)
    window.annotate_selected('comments', 'sorted target')
    assert a.comments == 'sorted target' and b.comments == ''
    window.history.undo()
    assert a.comments == ''
    window.date_from.setText('invalid')
    assert all(window.browser.item(i).isHidden() for i in range(3))


def test_unknown_dates_and_legacy_annotations(tmp_path):
    a = parse_text('x,y\n0,1', source=str(tmp_path))
    assert acquisition_timestamp(a) is None
    path = tmp_path / 'old.json'
    save_project(path, [a], {})
    payload = json.loads(path.read_text())
    for key in ('favorite', 'tags', 'comments'):
        del payload['datasets'][0][key]
    path.write_text(json.dumps(payload))
    loaded, _ = load_project(path)
    assert (loaded[0].favorite, loaded[0].tags, loaded[0].comments) == (False, [], '')
    payload['datasets'][0]['tags'] = 'invalid'
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match='annotations'):
        load_project(path)
