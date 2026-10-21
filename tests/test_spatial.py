from types import SimpleNamespace
from pathlib import Path
import numpy as np
import pytest
from rogi.spatial import image_geometry, scan_dimensions
from rogi.images import ImageViewer, raster
from rogi.spm import load_spm
from rogi.project import save_project, load_project
from test_images import channel


def metadata(format, sections, **extra):
    return dict(format=format, version=1, source_dataset_id='test', unparsed=[],
                sections=[dict(name=name, occurrence=i+1, source_line=i+1,
                               entries=[dict(key=k, raw_value=v, value=v, unit=None, source_line=i+1)
                                        for k, v in fields.items()])
                          for i, (name, fields) in enumerate(sections)], **extra)


def bruker(size='20 20 ~m'):
    d = channel()
    d.instrument_metadata = metadata('nanoscope', [('Ciao image list',
        {'Scan Size': size, '@2:Image Data': 'S [Height] "Height"', 'Aspect Ratio': '1:1'})], image_channel_index=0)
    return d


@pytest.mark.parametrize('unit', ['~m', 'um', 'µm', 'μm'])
def test_physical_square_with_unequal_samples(unit):
    d = bruker(f'20 20 {unit}')
    extent, x, y = image_geometry(d, (2, 3))
    np.testing.assert_allclose(extent, (0,20,0,20))
    assert x == 'X (µm)' and y == 'Y (µm)'
    del d.instrument_metadata['image_channel_index']
    np.testing.assert_allclose(image_geometry(d, (2,3))[0], extent)


def test_channel_specific_size_and_derived_copy():
    d = bruker()
    second = metadata('nanoscope', [('Ciao image list', {'Scan Size': '5 10 nm'})])['sections'][0]
    d.instrument_metadata['sections'].append(second)
    d.instrument_metadata['image_channel_index'] = 1
    np.testing.assert_allclose(image_geometry(d.derived(), (2,3))[0], [0,5,0,10])


@pytest.mark.parametrize('size', ['20 0 nm', '-2 5 nm', '20 20 unknown', 'bad'])
def test_invalid_size_falls_back_to_pixels(size):
    assert image_geometry(bruker(size), (2,3)) == ((-.5,2.5,-.5,1.5), 'X pixel', 'Y pixel')


def test_single_dimension_aspect_ratio():
    d = bruker('20000 nm')
    d.instrument_metadata['sections'][0]['entries'][-1]['raw_value'] = '2:1'
    np.testing.assert_allclose(image_geometry(d, (2,3))[0], [0,20,0,10])


def test_nanonis_range_in_metres():
    d = channel()
    d.instrument_metadata = metadata('nanonis_sxm', [('SCAN_RANGE', {'Value': '3e-7 2e-7'})])
    extent, x, y = image_geometry(d, (2,3))
    np.testing.assert_allclose(extent, [0,300,0,200])
    assert x == 'X (nm)'


def test_cursor_physical_to_pixel_and_contrast_keeps_zoom(app):
    d = bruker()
    before = d.values.copy()
    viewer = ImageViewer()
    try:
        viewer.set_context([d], d)
        ax = next(iter(viewer.panels))
        viewer.motion(SimpleNamespace(inaxes=ax, xdata=10., ydata=15.))
        assert 'X pixel 1, Y pixel 1' in viewer.readout.text()
        assert 'X (µm) 10' in viewer.readout.text()
        assert 'missing' in viewer.readout.text()
        ax.set_xlim(2,12)
        viewer.palette.setCurrentText('inferno')
        assert ax.get_xlim() == (2,12)
        np.testing.assert_array_equal(d.values, before)
    finally:
        viewer.close()


@pytest.mark.parametrize('suffix', ['.json', '.h5'])
def test_real_scan_saved_project_extents(tmp_path, suffix):
    path = Path(__file__).resolve().parents[1] / 'example-data/260813/spm/08142325.0_00001.spm'
    d = load_spm(path)[0]
    assert raster(d).shape == (64,256)
    np.testing.assert_allclose(scan_dimensions(d), (20e-6,20e-6))
    # Simulate a project saved before channel association was explicit.
    del d.instrument_metadata['image_channel_index']
    output = tmp_path / ('scan' + suffix)
    save_project(output, [d], {})
    restored, _ = load_project(output)
    np.testing.assert_allclose(image_geometry(restored[0], (64,256))[0], (0,20,0,20))
