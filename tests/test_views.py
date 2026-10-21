"""Saved views survive both encodings and restore by identity, not row order."""
from copy import deepcopy
import json

import numpy as np
import pytest
from PySide6 import QtWidgets as W
from rogi.core import parse_text, Dataset
from rogi.project import save_project, load_project
from rogi.ui import MainWindow


@pytest.fixture
def window():
    app = W.QApplication.instance() or W.QApplication([])
    window = MainWindow()
    yield window
    window.dirty = False
    window.close()


@pytest.mark.parametrize('extension', ['json', 'h5'])
def test_view_roundtrip_and_identity(window, tmp_path, extension):
    a = parse_text('x,y,z\n1,2,3\n2,4,6', name='same')
    b = parse_text('x,y\n1,5\n2,10', name='same')
    window.add_dataset(a)
    window.add_dataset(b)
    a.visible, b.visible = True, False
    a.ycol = 2
    window.activate_dataset(a.id)
    window.title.setText('Saved plot')
    window.view['x'] = dict(scale='log', auto=False, limits=[1., 10.])
    window.redraw()
    window.create_view('Overview')
    original = deepcopy(window.saved_views)
    window.rename_view('Overview', 'Analysis')
    with pytest.raises(ValueError):
        window.create_view('Analysis')
    a.visible, b.visible = False, True
    a.ycol = 1
    window.datasets.reverse()
    window.refresh_history_view()
    window.path = tmp_path / f'views.{extension}'
    window.save()
    window.open_project(str(window.path))
    assert not window.dirty
    window.restore_view('Analysis')
    assert window.current().id == a.id
    assert window.current().ycol == 2
    assert window.current().visible
    assert not next(d for d in window.datasets if d.id == b.id).visible
    assert window.title.text() == 'Saved plot'
    assert window.ax.get_xscale() == 'log'
    np.testing.assert_allclose(window.ax.get_xlim(), [1, 10])
    assert window.saved_views['Analysis'] == original['Overview']
    window.datasets = [d for d in window.datasets if d.id != a.id]
    window.refresh_history_view()
    window.restore_view('Analysis')
    assert window.current().id == b.id
    assert 'missing dataset' in window.statusBar().currentMessage()
    window.delete_view('Analysis')
    window.save()
    assert load_project(window.path)[1]['saved_views'] == {}


@pytest.mark.parametrize('extension', ['json', 'h5'])
def test_image_view_roundtrip(window, tmp_path, extension):
    def image(name):
        return Dataset(name=name, columns=['Sample', 'X pixel', 'Y pixel', 'Height'],
                       values=np.array([[0, 0, 0, 1], [1, 1, 0, 2], [2, 0, 1, 3], [3, 1, 1, 4]]),
                       source=name + '.spm')
    a, b = image('a'), image('b')
    window.add_dataset(a)
    window.add_dataset(b)
    window.activate_dataset(a.id)
    window.plot_tabs.setCurrentIndex(1)
    viewer = window.image_viewer
    viewer.palette.setCurrentText('magma')
    viewer.mode.setCurrentText('Manual')
    viewer.low.setText('1.5')
    viewer.high.setText('3.5')
    viewer.compare.setCurrentIndex(viewer.compare.findData(b.id))
    viewer.render()
    for ax in viewer.panels:
        ax.set_xlim(.1, .8)
        ax.set_ylim(.2, .9)
    window.create_view('Maps')
    state = deepcopy(window.saved_views['Maps'])
    window.path = tmp_path / f'maps.{extension}'
    window.save()
    window.open_project(str(window.path))
    window.restore_view('Maps')
    assert window.plot_tabs.currentIndex() == 1
    assert viewer.snapshot() == state['image']
    assert len(viewer.panels) == 2
    window.datasets = [d for d in window.datasets if d.id != b.id]
    window.refresh_history_view()
    window.restore_view('Maps')
    assert viewer.compare.currentData() is None
    assert len(viewer.panels) == 1


@pytest.mark.parametrize('extension', ['json', 'h5'])
def test_old_projects_without_views(window, tmp_path, extension):
    window.create_view('Old session')
    path = tmp_path / f'legacy.{extension}'
    save_project(path, [parse_text('x,y\n1,2')], {})
    window.dirty = False
    window.open_project(str(path))
    assert window.saved_views == {}


def test_invalid_snapshot_rejected(window, tmp_path):
    window.create_view('Empty')
    path = tmp_path / 'invalid.json'
    window.path = path
    window.save()
    data = json.loads(path.read_text())
    data['settings']['saved_views']['Empty']['plot']['xscale'] = 'invalid'
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        load_project(path)


@pytest.mark.parametrize('extension', ['json', 'h5'])
def test_multichannel_selection(window, tmp_path, extension):
    from rogi.spm import parse_spm
    from rogi.scanfile import bundle_channels
    from test_spm import spm_bytes
    a = bundle_channels(parse_spm(spm_bytes(), source='a.spm'))
    b = bundle_channels(parse_spm(spm_bytes(), source='b.spm'))
    window.add_dataset(a)
    window.add_dataset(b)
    window.activate_dataset(a.id)
    window.plot_tabs.setCurrentIndex(1)
    viewer = window.image_viewer
    viewer.channel.setCurrentIndex(1)
    viewer.compare.setCurrentIndex(1)
    window.create_view('Second channel')
    expected = deepcopy(window.saved_views['Second channel']['image'])
    viewer.channel.setCurrentIndex(0)
    window.path = tmp_path / f'channels.{extension}'
    window.save()
    window.open_project(str(window.path))
    window.restore_view('Second channel')
    assert viewer.channel.currentIndex() == 1
    assert viewer.snapshot() == expected


@pytest.mark.parametrize('extension', ['json', 'h5'])
def test_invalid_view_save_preserves_file(window, tmp_path, extension):
    window.create_view('Empty')
    path = tmp_path / f'atomic.{extension}'
    save_project(path, [], window.settings())
    before = path.read_bytes()
    settings = window.settings()
    settings['saved_views']['Empty']['image']['zoom'] = {'missing': {'xlim': [0, 1]}}
    with pytest.raises(ValueError, match='both axis'):
        save_project(path, [], settings)
    assert path.read_bytes() == before
