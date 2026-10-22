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
    window.browser_panel.choose_tag('★', True)
    assert window.tag_button.text() == 'Tags (1)'
    window.search.setText('Bias tag:kee tag:favorite')
    assert [window.dataset_for_item(window.browser.item(i)) for i in range(3)
            if not window.browser.item(i).isHidden()] == [a, b]
    assert [(d.group, d.group_path) for d in window.datasets] == groups
    assert [d.visible for d in window.datasets] == visibility
    assert window.history.isClean()
    window.activate_dataset(a.id)
    window.annotate_selected('comments', 'sorted target')
    assert a.comments == 'sorted target' and b.comments == ''
    window.history.undo()
    assert a.comments == ''


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


def test_short_names_drop_shared_words_only_when_rows_stay_distinct():
    from rogi.browser_panel import short_names, shared_text
    names = ['4MHz, YSL AOTF 50 µW', '5MHz, YSL AOTF 50 µW', '10MHz, YSL AOTF 50 µW']
    assert short_names(names) == ['4MHz', '5MHz', '10MHz']
    assert shared_text(names) == 'YSL AOTF 50 µW'
    assert short_names(['YSLAOTF_power100_4MHz', 'YSLAOTF_power100_5MHz']) == ['4MHz', '5MHz']
    assert short_names(['2026-01-02 scan', '2026-01-03 scan']) == ['2026-01-02', '2026-01-03']
    assert short_names(['Scan 1', 'Scan 1 copy']) == ['Scan 1', 'copy']  # never blank
    assert short_names(['Only one']) == ['Only one']


def test_tree_view_groups_rows_and_flat_view_keeps_selection(window):
    from rogi.browser_panel import is_group
    names = ['4MHz, YSL AOTF', '5MHz, YSL AOTF', 'loose']
    datasets = [parse_text('x,y\n0,1', name=name) for name in names]
    for d in datasets[:2]:
        d.group_path = [{'field': None, 'value': 'run'}]
        d.group = 'run'
    for d in datasets:
        window.add_dataset(d)
    group = window.browser.topLevelItem(0)
    assert is_group(group) and group.text(0) == 'run (2)' and group.childCount() == 2
    assert [window.browser.item(i).text() for i in range(3)] == ['4MHz', '5MHz', 'loose']
    assert window.browser.isColumnHidden(1) and window.browser.isColumnHidden(2)  # no dates known
    window.browser.setCurrentRow(1)
    assert window.current() is datasets[1]
    window.browser_panel.tree_toggle.setChecked(False)
    assert window.browser.topLevelItemCount() == 3 and window.current() is datasets[1]
    assert window.browser.item(0).text() == '4MHz, YSL AOTF — run'
    window.browser_panel.tree_toggle.setChecked(True)
    assert window.current() is datasets[1]
    window.search.setText('loose')
    group = window.browser.topLevelItem(0)  # rebuilt by the view switch
    assert group.isHidden() and window.browser.currentRow() == -1
    window.search.clear()
    group = window.browser.topLevelItem(0)
    assert not group.isHidden() and group.text(0) == 'run (2)'
    group.setExpanded(False)
    window.refresh_history_view()
    assert not window.browser.topLevelItem(0).isExpanded()


def test_tree_checkbox_click_toggles_plot_visibility(window):
    from PySide6.QtTest import QTest
    d = parse_text('x,y\n0,1', name='nested')
    d.group_path = [{'field': None, 'value': 'run'}]
    window.add_dataset(d)
    window.browser.resize(400, 300)
    window.browser.show()
    item = window.browser.item(0)
    assert item.parent() is not None
    option = W.QStyleOptionViewItem()
    option.initFrom(window.browser)
    option.rect = window.browser.visualItemRect(item)
    option.features |= W.QStyleOptionViewItem.ViewItemFeature.HasCheckIndicator
    box = window.browser.style().subElementRect(W.QStyle.SubElement.SE_ItemViewItemCheckIndicator, option,
                                                window.browser)
    before = d.visible
    QTest.mouseClick(window.browser.viewport(), C.Qt.MouseButton.LeftButton, pos=box.center())
    assert d.visible != before


def test_favorite_is_edited_and_filtered_as_a_tag(window, monkeypatch):
    a, b = parse_text('x,y\n0,1', name='A'), parse_text('x,y\n0,1', name='B')
    for d in (a, b):
        window.add_dataset(d)
    window.activate_dataset(a.id)
    monkeypatch.setattr(W.QInputDialog, 'getText', lambda *args, **kwargs: ('★, calib', True))
    window.history.setClean()
    window.edit_tags()
    assert a.favorite and a.tags == ['calib']
    assert window.browser.item(0).text(4) == '★, calib'
    window.history.undo()
    assert not a.favorite and a.tags == []  # one undo step
    window.history.redo()
    window.search.setText('tag:favorite')
    assert window.browser_panel.hidden_ids() == {b.id}
    window.search.clear()
    window.browser_panel.choose_tag('calib', True)
    assert window.browser_panel.hidden_ids() == {b.id}
    window.browser_panel.tag_menu.aboutToShow.emit()
    labels = [action.text() for action in window.browser_panel.tag_menu.actions()]
    assert labels[:2] == ['★ Favorites (1)', 'calib (1)']
    window.history.undo()  # the tag disappears, so its filter must not keep hiding rows
    assert window.browser_panel.tag_choices == set() and window.browser_panel.hidden_ids() == set()
