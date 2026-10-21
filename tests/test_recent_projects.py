import pytest
from PySide6 import QtWidgets as W
from rogi.core import parse_text
from rogi.project import save_project
from rogi.ui import MainWindow


@pytest.fixture
def window(app):
    window = MainWindow()
    yield window
    window.dirty = False
    window.close()


def project(path):
    save_project(path, [parse_text('x,y\n1,2')], {})
    return path


def test_recent_order_persistence_and_missing(window, tmp_path):
    paths = [project(tmp_path / f'{i}.json') for i in range(12)]
    for path in paths:
        window.open_project(path)
    assert window.recent_projects() == [str(p) for p in reversed(paths[2:])]
    window.open_project(paths[4])
    window.path = tmp_path / 'saved.h5'
    window.save()
    assert window.recent_projects()[:2] == [str(window.path), str(paths[4])]
    other = MainWindow()
    try:
        assert other.recent_projects() == window.recent_projects()
        paths[4].unlink()
        assert str(paths[4]) not in other.recent_projects()
        other.refresh_recent_projects()
        assert len(other.recent_menu.actions()) == 9
    finally:
        other.close()


def test_startup_suggestion_and_cancel(window, tmp_path, monkeypatch):
    path = project(tmp_path / 'recent.h5')
    window.remember_project(path)
    calls = []
    def choose(*args):
        calls.append(args)
        return str(path), False
    monkeypatch.setattr(W.QInputDialog, 'getItem', choose)
    window.suggest_recent_project()
    assert calls[0][3] == [str(path)]
    assert window.path is None
    monkeypatch.setattr(W.QInputDialog, 'getItem', lambda *a: (str(path), True))
    window.suggest_recent_project()
    assert window.path == path
    assert not window.dirty


def test_failed_open_not_remembered(window, tmp_path):
    path = tmp_path / 'bad.json'
    path.write_text('{}')
    with pytest.raises(ValueError):
        window.open_project(path)
    assert window.recent_projects() == []


def test_conversion_cancel_preserves_workspace(window, tmp_path, monkeypatch):
    source = tmp_path / 'input'
    source.mkdir()
    (source / 'data.csv').write_text('x,y\n1,2')
    target = tmp_path / 'converted.h5'
    window.add_dataset(parse_text('x,y\n3,4'))
    original = window.current()
    monkeypatch.setattr(W.QFileDialog, 'getExistingDirectory', lambda *a: str(source))
    monkeypatch.setattr(W.QFileDialog, 'getSaveFileName', lambda *a: (str(target), ''))
    monkeypatch.setattr(W.QMessageBox, 'question', lambda *a: W.QMessageBox.StandardButton.Cancel)
    window.convert_folder()
    assert not target.exists()
    assert window.current() is original
    assert window.path is None
