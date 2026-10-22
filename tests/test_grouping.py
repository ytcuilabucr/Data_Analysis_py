from copy import deepcopy
import pytest
from PySide6 import QtWidgets as W
from rogi.core import parse_dat
from rogi.grouping import partitions, varying_fields, path_key
from rogi.project import save_project, load_project
from rogi.ui import MainWindow, MetadataGroupingDialog

SIZE = 'Scan[1].Size[1]'
RATE = 'Scan[1].Rate[1]'


def scan(size, rate):
    return parse_dat(f'[Scan]\nSize: {size}\nRate: {rate}\nConstant: same\n[Data]\nx\ty\n1\t2\n')


def test_partitions_sort_each_level_and_missing():
    ds = [scan('10000 nm', '2 Hz'), scan('5000 nm', '1 Hz'),
          scan('10000 nm', '10 Hz'), scan('10000 nm', '')]
    result = partitions(ds, [(SIZE, False), (RATE, True)])
    assert [d.id for d, _ in result] == [ds[i].id for i in (1, 2, 0, 3)]
    assert result[-1][1][-1] == {'field': RATE, 'value': None}
    assert varying_fields(ds, [(SIZE, False)]) == [RATE]
    # A field differing only between parents is not a useful subgroup.
    assert varying_fields([scan('5 nm', '1 Hz'), scan('10 nm', '2 Hz')], [(SIZE, False)]) == []


@pytest.mark.parametrize('extension', ['json', 'h5'])
def test_nested_undo_filters_save_copy_and_manual_group(tmp_path, extension):
    app = W.QApplication.instance() or W.QApplication([])
    window = MainWindow()
    ds = [scan('10 nm', '1 Hz'), scan('5 nm', '2 Hz'), scan('10 nm', '3 Hz')]
    try:
        for d in ds:
            window.add_dataset(d)
        window.group_by_levels(ds, [(SIZE, False), (RATE, True)])
        assert [d.id for d in window.datasets] == [ds[i].id for i in (1, 2, 0)]
        path = deepcopy(ds[0].group_path)
        assert len(path) == 2
        parent = path[:1]
        index = window.group_filter.findData(parent)
        assert index >= 0
        window.group_filter.setCurrentIndex(index)
        shown = [window.dataset_for_item(window.browser.item(i)).id for i in range(3)
                 if not window.browser.item(i).isHidden()]
        assert set(shown) == {ds[0].id, ds[2].id}
        tree_parent = window.group_tree.topLevelItem(1)
        assert tree_parent.text(1) == '2'
        assert tree_parent.childCount() == 2
        copied = ds[0].derived()
        copied.group_path[0]['value'] = 'changed'
        assert ds[0].group_path == path
        target = tmp_path / f'grouped.{extension}'
        save_project(target, window.datasets, {})
        loaded, _ = load_project(target)
        assert [d.group_path for d in loaded] == [d.group_path for d in window.datasets]
        window.history.undo()
        assert all(not d.group_path and not d.group for d in ds)
        assert [d.id for d in window.datasets] == [d.id for d in ds]
        window.history.redo()
        window.group_filter.setCurrentIndex(0)
        window.browser.selectAll()
        window.set_selected_group('manual')
        assert all(d.group == 'manual' and not d.group_path for d in ds)
        window.history.undo()
        assert ds[0].group_path == path
    finally:
        window.dirty = False
        window.close()


def test_append_preserves_legacy_names_with_slashes_and_preview():
    app = W.QApplication.instance() or W.QApplication([])
    ds = [scan('5 nm', '1 Hz'), scan('5 nm', '2 Hz'), scan('10 nm', '3 Hz')]
    for d in ds:
        d.group = 'folder/with slash'
    dialog = MetadataGroupingDialog(ds)
    try:
        dialog.mode.setCurrentIndex(1)
        dialog.field.setCurrentText(SIZE)
        assert dialog.add_level.isEnabled()
        dialog.add_row()
        assert dialog.level_rows[1][1].currentText() == RATE
        pairs = partitions(ds, dialog.levels, True)
        assert all(p[0] == {'field': None, 'value': 'folder/with slash'} for _, p in pairs)
        assert len({path_key(p) for _, p in pairs}) == 3
        root = dialog.preview.topLevelItem(0)
        assert root.text(0) == 'folder/with slash' and root.text(1) == '3'
        assert root.childCount() == 2
        assert root.child(0).childCount() == 2
        dialog.remove_row(dialog.level_rows[1][0])
        assert len(dialog.levels) == 1
    finally:
        dialog.close()


def test_default_metadata_grouping_keeps_spm_parent_and_siblings(monkeypatch, tmp_path):
    app = W.QApplication.instance() or W.QApplication([])
    window = MainWindow()
    scans = [scan('5000 nm', '1 Hz'), scan('10000 nm', '2 Hz')]
    siblings = [scan('1 nm', '1 Hz'), scan('2 nm', '2 Hz')]
    for d in scans:
        d.group = 'spm'
    for d, name in zip(siblings, ('Spectrum', 'sxm')):
        d.group = name

    def accept_preview(dialog):
        assert dialog.mode.currentText() == 'Add subgroup within existing groups'
        dialog.field.setCurrentText(SIZE)
        assert dialog.preview.topLevelItemCount() == 1
        parent = dialog.preview.topLevelItem(0)
        assert parent.text(0) == 'spm'
        assert parent.text(1) == '2'
        assert parent.childCount() == 2
        return W.QDialog.DialogCode.Accepted

    monkeypatch.setattr(MetadataGroupingDialog, 'exec', accept_preview)
    try:
        for d in scans + siblings:
            window.add_dataset(d)
        window.browser.clearSelection()
        for row in (0, 1):
            window.browser.item(row).setSelected(True)
        window.group_by_metadata()
        assert all(d.group_path[0] == {'field': None, 'value': 'spm'} for d in scans)
        assert all(len(d.group_path) == 2 for d in scans)
        assert [(d.group, d.group_path) for d in siblings] == [('Spectrum', []), ('sxm', [])]
        assert {window.group_tree.topLevelItem(i).text(0)
                for i in range(window.group_tree.topLevelItemCount())} == {'spm', 'Spectrum', 'sxm'}
        target = tmp_path / 'nested.h5'
        save_project(target, window.datasets, {})
        loaded, _ = load_project(target)
        assert loaded[0].group_path == scans[0].group_path
        window.history.undo()
        assert all(d.group == 'spm' and d.group_path == [] for d in scans)
        window.history.redo()
        assert all(len(d.group_path) == 2 for d in scans)
    finally:
        window.dirty = False
        window.close()


def test_legacy_project_and_invalid_path(tmp_path):
    import json
    d = scan('5 nm', '1 Hz')
    d.group = 'old/group'
    target = tmp_path / 'old.json'
    save_project(target, [d], {})
    data = json.loads(target.read_text())
    data['datasets'][0].pop('group_path')
    target.write_text(json.dumps(data))
    loaded, _ = load_project(target)
    assert loaded[0].group == 'old/group' and loaded[0].group_path == []
    data['datasets'][0]['group_path'] = [{'field': 5, 'value': []}]
    target.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        load_project(target)


def test_simplified_field_names_are_unique_even_with_literal_suffixes():
    from rogi.grouping import field_labels
    fields = ['Ciao scan list[1].Scan Size[1]', 'Ciao image list[1].Scan Size[1]',
              'Ciao image list[2].Scan Size[1]', 'Other[1].Scan Size [1][1]',
              'Lockin[1].@2:Gain[1]', 'Lockin[1].Gain[2]', 'Other[1].gain[1]']
    labels = field_labels(fields)
    assert len({s.casefold() for s in labels.values()}) == len(fields)
    assert all('Ciao' not in label for label in labels.values())
    assert labels == field_labels(reversed(fields))
    assert field_labels([SIZE]) == {SIZE: 'Size'}


def test_group_labels_simplify_and_disambiguate_across_project():
    app = W.QApplication.instance() or W.QApplication([])
    window = MainWindow()
    first, second = scan('5 nm', '1 Hz'), scan('10 nm', '2 Hz')
    other = 'Other[1].Size[1]'
    first.group_path = [{'field': SIZE, 'value': '5 nm'}]
    second.group_path = [{'field': other, 'value': '10 nm'}]
    try:
        for d in (first, second):
            window.add_dataset(d)
        window.refresh_history_view()
        labels = [window.group_tree.topLevelItem(i).text(0) for i in range(2)]
        assert all('Scan[1]' not in label and 'Other[1]' not in label for label in labels)
        assert labels[0].split(' = ')[0] != labels[1].split(' = ')[0]
        for i, d in enumerate((first, second)):
            assert labels[i] in window.browser.item(i).text()
            assert d.group_path[0]['field'] in window.group_tree.topLevelItem(i).toolTip(0)
        window.group_filter.setCurrentIndex(window.group_filter.findData(first.group_path))
        assert not window.browser.item(0).isHidden() and window.browser.item(1).isHidden()
    finally:
        window.dirty = False
        window.close()


def test_title_fields_parse_pairs_and_tokens_for_grouping_only():
    from rogi.grouping import title_fields
    from rogi.metadata import metadata_fields
    d = scan('5 nm', '1 Hz')
    d.name = 'YSLAOTF_laserpower100_4MHz_2107Gain1_'
    assert title_fields(d) == {'Title: laserpower': '100', 'Title: MHz': '4 MHz'}
    d.name = 'YSL AOTF - 1.power = 10; run2_run3'
    assert title_fields(d) == {'Title: YSL AOTF - 1.power': '10', 'Title: run': '2', 'Title: run [2]': '3'}
    assert not any(key.startswith('Title: ') for key in metadata_fields(d))


def test_partitions_group_by_title_power_numerically():
    ds = []
    for name in ('AOTF power = 100', 'AOTF power = 10', 'AOTF power = 30', 'AOTF power = 10'):
        d = scan('5 nm', '1 Hz')
        d.name = name
        ds.append(d)
    key = 'Title: AOTF power'
    assert key in varying_fields(ds)
    result = partitions(ds, [(key, False)])
    assert [path[-1]['value'] for _, path in result] == ['10', '10', '30', '100']
