import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('MPLCONFIGDIR', '/tmp/rogi-matplotlib-tests')
from types import SimpleNamespace
import numpy as np
import pytest
from PySide6 import QtWidgets as W
from rogi.core import Dataset
from rogi.images import raster, contrast_limits, ImageViewer
from rogi.ui import MainWindow
from rogi.project import save_project


def channel(name='Height', raw=True):
    return Dataset(name, ['Sample', 'X pixel', 'Y pixel', 'Height (raw counts)'],
                   [[0, 0, 0, -2], [1, 1, 0, 0], [2, 2, 0, 1],
                    [3, 0, 1, 5], [4, 1, 1, np.nan], [5, 2, 1, 100]], raw=raw)


def test_raster_coordinates_not_row_order():
    d = channel()
    d.values = d.values[[4, 0, 5, 3, 1, 2]]
    np.testing.assert_array_equal(raster(d), [[-2, 0, 1], [5, np.nan, 100]])


@pytest.mark.parametrize('xy', [[[0, 0]] * 6, [[0.5, 0]] * 6, [[-1, 0]] * 6,
                                [[np.nan, 0]] * 6, [[999999, 999999]] * 6])
def test_invalid_grids(xy):
    d = channel(raw=False)
    d.values[:, 1:3] = xy
    with pytest.raises(ValueError):
        raster(d)


def test_contrast_missing_constant_outliers():
    assert contrast_limits(np.array([1, np.nan, 100]), 'Full range') == (1, 100)
    np.testing.assert_allclose(contrast_limits(np.arange(101), 'Percentile', 2, 98), (2, 98))
    assert contrast_limits(np.array([np.nan]), 'Full range') == (0, 1)
    lo, hi = contrast_limits(np.array([7, 7]), 'Full range')
    assert lo < 7 < hi
    for mode, lo, hi in [('Manual', 2, 1), ('Manual', np.nan, 2), ('Percentile', -1, 98)]:
        with pytest.raises(ValueError):
            contrast_limits(np.array([1]), mode, lo, hi)


def test_viewer_comparison_zoom_cursor_and_validation(app):
    viewer = ImageViewer()
    a, b = channel(), channel('Other height scan')
    a.source, b.source = '/scans/a.spm', '/scans/b.spm'
    before = a.values.copy()
    try:
        viewer.set_context([a, b], a)
        ax = next(iter(viewer.panels))
        np.testing.assert_array_equal(viewer.panels[ax][1], raster(a))
        ax.set_xlim(.2, 1.8)
        viewer.palette.setCurrentText('gray')
        assert ax.get_xlim() == (.2, 1.8)
        viewer.mode.setCurrentText('Percentile')
        viewer.motion(SimpleNamespace(inaxes=ax, xdata=1., ydata=1.))
        assert 'missing' in viewer.readout.text()
        viewer.motion(SimpleNamespace(inaxes=ax, xdata=2., ydata=1.))
        assert '100' in viewer.readout.text() and 'X pixel 2' in viewer.readout.text()
        viewer.compare.setCurrentIndex(1)
        assert len(viewer.panels) == 2 and len(viewer.figure.axes) == 6
        viewer.mode.setCurrentText('Manual')
        viewer.low.setText('-1'); viewer.high.setText('10'); viewer.render()
        assert all(p[2].get_clim() == (-1, 10) for p in viewer.panels.values())
        viewer.low.setText('invalid'); viewer.render()
        assert not viewer.panels and viewer.message.text()
        viewer.low.setText('0'); viewer.render()
        assert len(viewer.panels) == 2
        np.testing.assert_array_equal(a.values, before)
        viewer.set_context([a], a)
        assert len(viewer.panels) == 1
        viewer.set_context([], None)
        assert not viewer.panels and not viewer.figure.axes
    finally:
        viewer.close()


def test_force_curve_not_shown_as_image(app):
    viewer = ImageViewer()
    d = Dataset('Force', ['Sample', 'Segment', 'Sample in segment', 'Signal'], [[0, 0, 0, 2]])
    viewer.set_context([d], d)
    assert not viewer.panels
    assert 'force curves' in viewer.message.text()
    viewer.close()


def test_edit_and_undo_refresh_image(app):
    window = MainWindow()
    d = channel(raw=False)
    try:
        window.add_dataset(d)
        window.plot_tabs.setCurrentIndex(1)
        window.edit_cell(d, 0, 3, '42')
        assert next(iter(window.image_viewer.panels.values()))[1][0, 0] == 42
        window.history.undo()
        assert next(iter(window.image_viewer.panels.values()))[1][0, 0] == -2
        window.edit_cell(d, 0, 1, '1')
        assert not window.image_viewer.panels
        window.history.undo()
        assert window.image_viewer.panels
    finally:
        window.dirty = False
        window.close()


def test_reopened_project_and_map_export(app, tmp_path, monkeypatch):
    path = tmp_path / 'project.h5'
    d = channel()
    save_project(path, [d], {})
    window = MainWindow()
    try:
        window.open_project(path)
        window.plot_tabs.setCurrentIndex(1)
        assert len(window.image_viewer.panels) == 1
        output = tmp_path / 'map.png'
        monkeypatch.setattr(W.QFileDialog, 'getSaveFileName', lambda *args: (str(output), 'PNG (*.png)'))
        window.export_plot()
        assert output.read_bytes().startswith(b'\x89PNG')
    finally:
        window.dirty = False
        window.close()


def test_comparison_filters_channel_direction_units_and_file_type(app):
    viewer = ImageViewer()
    active = channel('Active')
    active.columns[3] = 'Height (Trace) (raw counts)'
    active.source = '/scans/a.spm'
    candidates = []
    for name, suffix, signal in [
        ('Matching', '.SPM', 'Height (Trace) (raw counts)'),
        ('Other signal', '.spm', 'Current (Trace) (raw counts)'),
        ('Other direction', '.spm', 'Height (Retrace) (raw counts)'),
        ('Other unit', '.spm', 'Height (Trace) (nm)'),
        ('Other file type', '.sxm', 'Height (Trace) (raw counts)'),
        ('Unknown file type', '', 'Height (Trace) (raw counts)'),
    ]:
        d = channel(name)
        d.source = '/scans/' + name + suffix
        d.columns[3] = signal
        candidates.append(d)
    # Content format must also agree, even when the extension is the same.
    different_format = channel('Different format')
    different_format.source = '/scans/different.spm'
    different_format.columns[3] = active.columns[3]
    different_format.instrument_metadata['format'] = 'nanonis_sxm'
    all_data = [active, *candidates, different_format]
    try:
        viewer.set_context(all_data, active)
        assert viewer.compare.count() == 2
        assert viewer.compare.itemData(1) == candidates[0].id
        viewer.compare.setCurrentIndex(1)
        assert len(viewer.panels) == 2
        viewer.set_context(all_data, candidates[1])
        assert viewer.compare.count() == 1
        assert viewer.compare.currentData() is None
        assert not viewer.compare.isEnabled()
        assert len(viewer.panels) == 1
    finally:
        viewer.close()


def test_profiles_values_coordinates_and_missing():
    from rogi.images import extract_profile
    from test_spatial import bruker
    for d, expected_x, expected_y in [(channel(), [0, 1, 2], [0, 1]),
                                      (bruker('6 8 nm'), [1, 3, 5], [2, 6])]:
        before = d.values.copy()
        horizontal = extract_profile(d, 'X', 1)
        vertical = extract_profile(d, 'Y', 1)
        np.testing.assert_allclose(horizontal.values[:, 0], expected_x)
        np.testing.assert_allclose(vertical.values[:, 0], expected_y)
        np.testing.assert_equal(horizontal.values[:, 1], [5, np.nan, 100])
        np.testing.assert_equal(vertical.values[:, 1], [0, np.nan])
        assert horizontal.parent == d.id and not horizontal.raw
        info = horizontal.instrument_metadata['profile_extraction']
        assert info['source_channel'] == d.columns[3]
        assert info['position'] == pytest.approx(expected_y[1])
        assert info['pixel_index'] == 1 and info['position_axis'] == 'Y'
        np.testing.assert_equal(d.values, before)
        for axis, index in [('X', -1), ('X', 2), ('Y', 3), ('Z', 0), ('X', .5)]:
            with pytest.raises(ValueError):
                extract_profile(d, axis, index)


@pytest.mark.parametrize('transposed', [False, True])
def test_profile_drag_transpose_and_snapshot(app, transposed):
    from test_spatial import bruker
    viewer = ImageViewer()
    d = bruker('6 8 nm')
    before = d.values.copy()
    try:
        viewer.set_context([d], d)
        original = viewer.selected_profile().values.copy()
        viewer.transpose.setChecked(transposed)
        ax = next(iter(viewer.panels))
        np.testing.assert_equal(viewer.panels[ax][1], raster(d).T if transposed else raster(d))
        assert ax.get_xlabel() == ('Y (nm)' if transposed else 'X (nm)')
        assert ax.get_ylabel() == ('X (nm)' if transposed else 'Y (nm)')
        np.testing.assert_equal(viewer.selected_profile().values, original)
        viewer.canvas.draw()
        # Drag the displayed vertical cursor to the first displayed column.
        vx = viewer.cursor_lines[0].get_xdata()[0]
        py = 1.
        sx, sy = ax.transData.transform((vx, py))
        viewer.press(SimpleNamespace(inaxes=ax, xdata=vx, ydata=py, x=sx, y=sy, button=1))
        assert viewer.drag_axis == 0
        viewer.motion(SimpleNamespace(inaxes=ax, xdata=1., ydata=py))
        viewer.release(None)
        assert viewer.drag_axis is None
        assert viewer.cursor_positions[d.id] == ([1, 0] if transposed else [0, 1])
        # Horizontal cursor updates the other original axis.
        hy = viewer.cursor_lines[1].get_ydata()[0]
        sx, sy = ax.transData.transform((.1, hy))
        viewer.press(SimpleNamespace(inaxes=ax, xdata=.1, ydata=hy, x=sx, y=sy, button=1))
        assert viewer.drag_axis == 1
        viewer.motion(SimpleNamespace(inaxes=ax, xdata=.1, ydata=.1))
        viewer.release(None)
        assert viewer.cursor_positions[d.id] == [0, 0]
        state = viewer.snapshot()
        viewer.restore_snapshot(state, [d], d)
        assert viewer.transpose.isChecked() == transposed
        assert viewer.cursor_positions[d.id] == [0, 0]
        ax = next(iter(viewer.panels))
        viewer.motion(SimpleNamespace(inaxes=ax, xdata=6. if transposed else 5.,
                                     ydata=5. if transposed else 6.))
        assert 'X pixel 2, Y pixel 1' in viewer.readout.text()
        assert '100' in viewer.readout.text()
        np.testing.assert_equal(d.values, before)
        viewer.set_context([], None)
        assert viewer.cut_axes is None
        assert not viewer.create_profile_button.isEnabled()
    finally:
        viewer.close()


def test_profile_export_creation_and_project_provenance(app, tmp_path, monkeypatch):
    import csv
    from rogi.scanfile import bundle_channels
    from rogi.project import load_project
    from test_spatial import metadata
    first = channel()
    first.instrument_metadata = metadata('nanoscope', [])
    d = bundle_channels([first, channel('Second')])
    window = MainWindow()
    try:
        window.add_dataset(d)
        viewer = window.image_viewer
        viewer.channel.setCurrentIndex(1)
        selected_id = viewer.current.id
        output = tmp_path / 'profile.csv'
        monkeypatch.setattr(W.QFileDialog, 'getSaveFileName', lambda *args: (str(output), 'CSV (*.csv)'))
        viewer.export_profile_button.click()
        with output.open() as stream:
            rows = list(csv.reader(stream))
        assert rows[0] == ['X pixel', 'Height (raw counts)']
        assert rows[2] == ['1.0', '']
        viewer.create_profile_button.click()
        result = window.datasets[-1]
        assert result.parent == d.id
        info = result.instrument_metadata['profile_extraction']
        assert info['source_channel_id'] == selected_id
        path = tmp_path / 'profiles.h5'
        save_project(path, window.datasets, {})
        reopened, _ = load_project(path)
        assert reopened[-1].instrument_metadata['profile_extraction'] == info
        np.testing.assert_equal(reopened[-1].values, result.values)
        window.history.undo()
        assert len(window.datasets) == 1
        window.history.redo()
        assert len(window.datasets) == 2
    finally:
        window.dirty = False
        window.close()


@pytest.mark.parametrize('transposed', [False, True])
def test_two_cursor_free_drag_alignment_region(app, transposed):
    from test_spatial import bruker
    viewer = ImageViewer()
    d = bruker('6 8 nm')
    try:
        viewer.resize(1100, 850)
        viewer.set_context([d], d)
        viewer.transpose.setChecked(transposed)
        viewer.canvas.draw()
        ax = next(iter(viewer.panels))
        below, right = viewer.cut_axes
        for width, height in [(1100, 850), (850, 650)]:
            viewer.resize(width, height)
            viewer.canvas.draw()
            image_box, bottom_box, right_box = [a.get_position() for a in (ax, below, right)]
            assert bottom_box.x0 == pytest.approx(image_box.x0)
            assert bottom_box.x1 == pytest.approx(image_box.x1)
            assert right_box.y0 == pytest.approx(image_box.y0)
            assert right_box.y1 == pytest.approx(image_box.y1)
        assert [m.get_marker() for m in viewer.cursor_markers] == ['s', 'o']
        for i, target in [(0, (0, 0)), (1, (2, 1))]:
            marker = viewer.cursor_markers[i]
            mx, my = marker.get_xdata()[0], marker.get_ydata()[0]
            sx, sy = ax.transData.transform((mx, my))
            viewer.cursor_choice.setCurrentIndex(i)
            viewer.press(SimpleNamespace(inaxes=ax, xdata=mx, ydata=my, x=sx, y=sy, button=1))
            assert viewer.drag_axis == 2
            dx, dy = (1+2*target[0], 2+4*target[1])
            if transposed:
                dx, dy = dy, dx
            viewer.motion(SimpleNamespace(inaxes=ax, xdata=dx, ydata=dy))
            viewer.release(None)
        assert viewer.cursor_positions[d.id] == [0, 0]
        assert viewer.second_positions[d.id] == [2, 1]
        np.testing.assert_equal(viewer.selected_profile().values[:, 1], [5, np.nan, 100])
        ax.set_xlim(1, 4)
        ax.set_ylim(2, 5)
        assert below.get_xlim() == (1, 4)
        assert right.get_ylim() == (2, 5)
        viewer.select_region.setChecked(True)
        region = viewer.selected_region()
        np.testing.assert_equal(region.values[:, 3], [-2, 0, 1, 5, np.nan, 100])
        np.testing.assert_allclose(region.values[:, 1], [1, 3, 5, 1, 3, 5])
        assert region.instrument_metadata['region_extraction']['pixel_bounds'] == [0, 2, 0, 1]
        assert region.parent == d.id
        assert '6 pixels' in viewer.region_summary.text() and '1 missing' in viewer.region_summary.text()
        assert viewer.region_patch.get_width() == pytest.approx(8 if transposed else 6)
        state = viewer.snapshot()
        viewer.restore_snapshot(state, [d], d)
        assert viewer.second_positions[d.id] == [2, 1]
        assert viewer.select_region.isChecked()
        # Reversed corners and a one-pixel missing region remain well-defined.
        viewer.cursor_positions[d.id], viewer.second_positions[d.id] = [2, 1], [0, 0]
        np.testing.assert_equal(viewer.selected_region().values, region.values)
        viewer.cursor_positions[d.id] = viewer.second_positions[d.id] = [1, 1]
        viewer.update_profiles()
        assert '1 pixels' in viewer.region_summary.text() and 'mean missing' in viewer.region_summary.text()
    finally:
        viewer.close()


def test_region_creation_undo_and_persistence(app, tmp_path):
    from rogi.project import load_project
    window = MainWindow()
    d = channel()
    try:
        window.add_dataset(d)
        viewer = window.image_viewer
        viewer.cursor_positions[d.id] = [0, 0]
        viewer.second_positions[d.id] = [2, 1]
        viewer.select_region.setChecked(True)
        viewer.create_region_button.click()
        region = window.datasets[-1]
        assert region.parent == d.id and not region.raw
        assert len(region.values) == 6
        path = tmp_path / 'region.h5'
        save_project(path, window.datasets, {})
        datasets, _ = load_project(path)
        assert datasets[-1].instrument_metadata == region.instrument_metadata
        np.testing.assert_equal(datasets[-1].values, region.values)
        window.history.undo()
        assert len(window.datasets) == 1
        window.history.redo()
        assert len(window.datasets) == 2
    finally:
        window.dirty = False
        window.close()
