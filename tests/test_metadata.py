import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('MPLCONFIGDIR', '/tmp/rogi-matplotlib-tests')
from copy import deepcopy
from pathlib import Path
import json
import numpy as np
import pytest
from PySide6 import QtWidgets as W, QtCore as C
from rogi.core import parse_dat, parse_text
from rogi.metadata import metadata_fields, metadata_search_text
from rogi.project import save_project, load_project
from rogi.ui import MainWindow, ImportDialog, MetadataDialog, MetadataGroupingDialog

EXAMPLES = Path(__file__).resolve().parents[1] / 'example-data/260813/Spectrum'
TEXT = ('\ufeff[Time]\r\n\r\n[Lockin1]\r\nModel: SR830\r\n'
        'TimeConstant: 100 ms\r\nOscAmp: 1.000E-2\r\nEmpty: \r\n'
        'Other: a:b\r\nOther: duplicate\r\nUnparsed header line\r\n'
        '[Lockin1]\r\nTimeConstant: 300 ms\r\n[Data]\r\n'
        'Time\tTime_Timestamp\tSignal\tOther\t\r\n'
        '2026/08/14_15:20:24\t3.869591E+9\t1\t10\r\n'
        '\t\t2\t20\r\n'
        'bad date\t3.869592E+9\t3\t30\r\n')


def test_schema_duplicates_units_and_timestamps():
    d = parse_dat(TEXT)
    assert d.source_text == TEXT
    metadata = d.instrument_metadata
    assert metadata['source_dataset_id'] == d.id
    assert [s['name'] for s in metadata['sections']] == ['Time', 'Lockin1', 'Lockin1']
    assert [s['occurrence'] for s in metadata['sections']] == [1, 1, 2]
    entries = metadata['sections'][1]['entries']
    assert entries[1]['value'] == 100 and entries[1]['unit'] == 'ms'
    assert entries[1]['raw_value'] == ' 100 ms'
    assert entries[2]['value'] == .01 and entries[2]['unit'] is None
    assert entries[3]['value'] is None and entries[3]['unit'] is None
    assert entries[4]['value'] == 'a:b'
    assert metadata['unparsed'][0]['text'] == 'Unparsed header line'
    assert entries[0]['source_line'] == 4
    fields = metadata_fields(d)
    assert fields['Lockin1[1].Other[1]'] == 'a:b'
    assert fields['Lockin1[1].Other[2]'] == 'duplicate'
    assert fields['Lockin1[2].TimeConstant[1]'] == '300 ms'
    assert 'Lockin1[1].Empty[1]' not in fields
    time, numeric = d.timestamps
    assert time['values'] == ['2026-08-14T15:20:24', None, None]
    assert time['raw'][2] == 'bad date' and time['invalid_rows'] == [3]
    assert numeric['values'] == [3869591000., None, 3869592000.]
    assert 'epoch' not in numeric and 'timezone' not in time
    assert not d.values.flags.writeable
    assert np.isnan(d.values[1, 0])


def test_all_supplied_examples():
    for path in sorted(EXAMPLES.glob('*.dat')):
        text = path.read_bytes().decode('utf-8')
        d = parse_dat(text)
        assert d.source_text.encode('utf-8') == path.read_bytes()
        expected_sections = [line[1:-1] for line in text.split('[Data]')[0].splitlines()
                             if line.startswith('[') and line.endswith(']')]
        assert [s['name'] for s in d.instrument_metadata['sections']] == expected_sections
        assert len(d.timestamps) == 2
        for stream in d.timestamps:
            assert len(stream['raw']) == len(d.values)
            assert len(stream['values']) == len(d.values)
            assert not stream['invalid_rows']
        assert d.timestamps[0]['values'][0].startswith('2026-08-')
        assert all(entry['unit'] is None for section in d.instrument_metadata['sections']
                   for entry in section['entries'] if entry['key'] == 'OscFreq')


@pytest.mark.parametrize('extension', ['json', 'h5'])
def test_metadata_project_and_derived_roundtrip(tmp_path, extension):
    raw = parse_dat(TEXT, source='measurement.dat')
    child = raw.derived()
    metadata, times = deepcopy(raw.instrument_metadata), deepcopy(raw.timestamps)
    child.edit(0, 0, '123')
    child.name, child.group = 'Renamed', 'Runs'
    assert child.timestamps == times  # acquisition snapshot, not edited channel values
    assert child.instrument_metadata is not raw.instrument_metadata
    path = tmp_path / f'metadata.{extension}'
    save_project(path, [raw, child], {})
    loaded, _ = load_project(path)
    assert loaded[0].source_text == TEXT
    for d in loaded:
        assert d.instrument_metadata == metadata and d.timestamps == times
    assert loaded[1].parent == loaded[0].id
    assert loaded[1].values[0, 0] == 123
    assert not loaded[0].values.flags.writeable


def test_import_selected_columns_and_viewer(tmp_path):
    app = W.QApplication.instance() or W.QApplication([])
    path = tmp_path / 'input.dat'
    path.write_bytes(TEXT.encode('utf-8'))
    dialog = ImportDialog(path)
    try:
        dialog.columns.item(0).setCheckState(C.Qt.CheckState.Unchecked)
        dialog.import_data()
        d = dialog.dataset
        assert d.columns == ['Signal', 'Other']
        assert d.source_text == TEXT
        assert len(d.timestamps) == 2 and len(d.timestamps[0]['raw']) == 3
        viewer = MetadataDialog(d)
        tree = viewer.findChild(W.QTreeWidget)
        assert tree.topLevelItemCount() == 4  # includes unparsed line
        tables = viewer.findChildren(W.QTableWidget)
        assert len(tables) == 2
        assert any(table.item(2, 2).text() == 'Unrecognized' for table in tables)
        viewer.close()
    finally:
        dialog.close()


def test_metadata_search_grouping_undo_and_missing(tmp_path):
    app = W.QApplication.instance() or W.QApplication([])
    window = MainWindow()
    try:
        first = parse_dat(TEXT, name='first')
        second = parse_dat(TEXT.replace('100 ms', '30 ms'), name='second')
        plain = parse_text('x,y\n1,2', name='plain')
        plain.group = 'Keep'
        for d in (first, second, plain):
            window.add_dataset(d)
        ids = [d.id for d in window.datasets]
        window.search.setText('TimeConstant[1]=30 ms')
        assert window.browser.item(0).isHidden()
        assert not window.browser.item(1).isHidden()
        assert window.browser.item(2).isHidden()
        window.search.setText('2026-08-14T15:20:24')
        assert not window.browser.item(0).isHidden()
        window.search.clear()
        window.browser.selectAll()
        window.group_selected_by_metadata('Lockin1[1].TimeConstant[1]')
        assert first.group.endswith('100 ms') and second.group.endswith('30 ms')
        assert plain.group.endswith('Missing value')
        assert [d.id for d in window.datasets] == [ids[1], ids[0], ids[2]]
        window.history.undo()
        assert first.group == second.group == '' and plain.group == 'Keep'
        assert [d.id for d in window.datasets] == ids
        window.history.redo()
        window.path = tmp_path / 'grouped.h5'
        window.save()
        loaded, _ = load_project(window.path)
        assert loaded[0].group == second.group
        assert loaded[0].instrument_metadata == second.instrument_metadata
    finally:
        window.dirty = False
        window.close()


def test_grouping_preview_variation_counts_and_order():
    app = W.QApplication.instance() or W.QApplication([])
    datasets = [parse_dat(TEXT.replace('100 ms', value))
                for value in ('5000 ms', '10000 ms', '5000 ms')]
    datasets.append(parse_text('x,y\n1,2'))
    dialog = MetadataGroupingDialog(datasets)
    try:
        assert dialog.field.findText('Lockin1[1].Model[1]') == -1
        dialog.field.setCurrentText('Lockin1[1].TimeConstant[1]')
        assert dialog.preview.topLevelItemCount() == 3
        assert dialog.preview.topLevelItem(0).text(0).endswith('5000 ms')
        assert dialog.preview.topLevelItem(0).text(1) == '2'
        assert dialog.preview.topLevelItem(1).text(1) == '1'
        assert '3 groups · 4 files · 1 files with missing values' in dialog.summary.text()
        dialog.order.setCurrentIndex(1)
        assert dialog.preview.topLevelItem(0).text(0).endswith('10000 ms')
        assert dialog.preview.topLevelItem(0).text(1) == '1'
    finally:
        dialog.close()
    empty = MetadataGroupingDialog(datasets[:1])
    try:
        assert empty.field.count() == 0
        assert not empty.buttons.button(W.QDialogButtonBox.StandardButton.Ok).isEnabled()
    finally:
        empty.close()


def test_grouping_descending_keeps_unselected_positions_and_missing_last():
    app = W.QApplication.instance() or W.QApplication([])
    window = MainWindow()
    try:
        low = parse_dat(TEXT.replace('100 ms', '5000 ms'))
        high = parse_dat(TEXT.replace('100 ms', '10000 ms'))
        missing = parse_text('x,y\n1,2')
        untouched = parse_dat(TEXT)
        for d in (low, missing, untouched, high):
            window.add_dataset(d)
        window.browser.clearSelection()
        for row in (0, 1, 3):
            window.browser.item(row).setSelected(True)
        key = 'Lockin1[1].TimeConstant[1]'
        window.group_selected_by_metadata(key, descending=True)
        assert [d.id for d in window.datasets] == [high.id, low.id, untouched.id, missing.id]
        assert untouched.group == ''
        assert missing.group.endswith('Missing value')
        window.history.undo()
        assert [d.id for d in window.datasets] == [low.id, missing.id, untouched.id, high.id]
        window.history.redo()
        # Ordering alone remains undoable when group labels already match.
        window.group_selected_by_metadata(key)
        assert window.datasets[0].id == low.id
        window.history.undo()
        assert window.datasets[0].id == high.id
    finally:
        window.dirty = False
        window.close()


def test_grouping_scope_recovers_single_selection_and_applies_preview():
    app = W.QApplication.instance() or W.QApplication([])
    window = MainWindow()
    low = parse_dat(TEXT.replace('100 ms', '30 ms'))
    high = parse_dat(TEXT)
    dialog = MetadataGroupingDialog([high], all_datasets=[high, low])
    try:
        assert '1 file(s) in scope' in dialog.summary.text()
        assert dialog.field.count() == 0
        dialog.scope.setCurrentIndex(1)
        dialog.field.setCurrentText('Lockin1[1].TimeConstant[1]')
        assert dialog.preview.topLevelItemCount() == 2
        assert '2 groups · 2 files' in dialog.summary.text()
        for d in (high, low):
            window.add_dataset(d)
        window.browser.clearSelection()
        window.browser.item(0).setSelected(True)
        window.group_selected_by_metadata(dialog.field.currentText(), datasets=dialog.datasets)
        assert high.group.endswith('100 ms') and low.group.endswith('30 ms')
        assert window.datasets[0].id == low.id
        window.history.undo()
        assert high.group == low.group == ''
        dialog.scope.setCurrentIndex(0)
        assert dialog.field.count() == 0
    finally:
        dialog.close()
        window.dirty = False
        window.close()


def test_legacy_and_invalid_metadata(tmp_path):
    path = tmp_path / 'legacy.json'
    save_project(path, [parse_dat(TEXT)], {})
    payload = json.loads(path.read_text())
    item = payload['datasets'][0]
    metadata, times = item.pop('instrument_metadata'), item.pop('timestamps')
    path.write_text(json.dumps(payload))
    legacy, _ = load_project(path)
    assert legacy[0].instrument_metadata == {} and legacy[0].timestamps == []
    assert legacy[0].source_text == TEXT
    item.update(instrument_metadata=metadata, timestamps=times)
    item['timestamps'][0]['values'].pop()
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match='row alignment'):
        load_project(path)
    item['timestamps'] = []
    item['instrument_metadata']['sections'][1]['entries'][0]['unit'] = 123
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match='metadata field'):
        load_project(path)


def test_plain_dat_and_numeric_time_remain_compatible():
    d = parse_dat('x\ty\n1\t2')
    assert d.instrument_metadata == {} and d.timestamps == []
    d = parse_dat('[Data]\nTime\tTime_Timestamp\tSignal\n2\t10\t1')
    assert d.columns == ['Time', 'Time_Timestamp', 'Signal']
    assert d.timestamps[0]['kind'] == 'numeric'
    assert d.timestamps[0]['values'] == [2.]
