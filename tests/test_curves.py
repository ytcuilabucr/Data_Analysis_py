"""Additional curves are chosen from the plot controls, per panel, and undo like browser checkboxes."""
import pytest
from PySide6 import QtCore as C, QtWidgets as W
from rogi.core import parse_text
from rogi.ui import MainWindow


@pytest.fixture
def window(app):
    window = MainWindow()
    a = parse_text('x,y,z\n1,2,3\n2,4,6', name='alpha')
    b = parse_text('t,v\n1,5\n2,10', name='beta')
    for d in (a, b):
        window.add_dataset(d)
    a.visible, b.visible = True, False
    window.activate_dataset(a.id)
    window.redraw()
    yield window
    window.dirty = False
    window.close()


def curve_ids(window):
    return [window.plot_controls.curves.item(i).data(C.Qt.ItemDataRole.UserRole) for i in range(window.plot_controls.curves.count())]


def choices(window):
    combo = window.plot_controls.curve_choice
    return [combo.itemText(i) for i in range(combo.count())]


def test_add_curve_from_controls_and_undo(window):
    alpha, beta = window.datasets
    assert curve_ids(window) == [alpha.id]
    assert choices(window) == ['beta — v']
    window.plot_controls.add_curve.click()
    assert beta.visible and curve_ids(window) == [alpha.id, beta.id]
    assert window.current() is beta
    assert not window.plot_controls.add_curve.isEnabled()
    labels = [line.get_label() for line in window.ax.get_lines()]
    assert 'alpha' in labels and 'beta' in labels
    window.undo_action.trigger()
    assert not beta.visible and curve_ids(window) == [alpha.id]


def test_remove_curve_hides_it(window):
    alpha, beta = window.datasets
    window.add_curve(beta.id)
    window.plot_controls.curves.setCurrentRow(0)
    next(b for b in window.analysis_panel.findChildren(W.QPushButton)
         if b.text() == 'Remove selected curve').click()
    assert not alpha.visible and curve_ids(window) == [beta.id]
    window.undo_action.trigger()
    assert alpha.visible


def test_curves_belong_to_the_active_panel(window):
    alpha, beta = window.datasets
    window.add_panel()
    assert curve_ids(window) == [alpha.id]
    window.add_curve(beta.id)
    assert window.panels[1]['channels'][beta.id] == [beta.xcol, beta.ycol]
    assert beta.id not in window.panels[0]['channels']
    window.remove_curve(beta.id)
    # In a panel with its own channels, removing drops it there but keeps it visible elsewhere.
    assert beta.visible and beta.id not in window.panels[1]['channels']
    window.undo_action.trigger()
    assert window.panels[1]['channels'][beta.id] == [beta.xcol, beta.ycol]
    window.undo_action.trigger()
    assert beta.id not in window.panels[1]['channels'] and not beta.visible
    assert window.panels[0]['channels'][beta.id] == [0, 1]


@pytest.fixture
def three(window):
    gamma = parse_text('s,w\n1,7\n2,8', name='gamma')
    window.add_dataset(gamma)
    gamma.visible = False
    window.redraw()
    return window


def test_candidates_follow_the_browser_filter(three):
    window = three
    assert choices(window) == ['beta — v', 'gamma — w']
    window.search.setText('gamma')
    assert choices(window) == ['gamma — w']
    assert window.plot_controls.match_browser_filter.text() == 'Match file browser filter (1 hidden)'
    # Plotted curves stay listed even when the filter hides them.
    alpha = window.datasets[0]
    assert curve_ids(window) == [alpha.id]
    window.search.setText('')
    assert choices(window) == ['beta — v', 'gamma — w']
    assert window.plot_controls.match_browser_filter.text() == 'Match file browser filter'


def test_filter_toggle_offers_every_dataset(three):
    window = three
    window.search.setText('gamma')
    window.plot_controls.match_browser_filter.setChecked(False)
    assert choices(window) == ['beta — v', 'gamma — w']
    window.plot_controls.match_browser_filter.setChecked(True)
    assert choices(window) == ['gamma — w']


def test_type_to_search_adds_the_matching_curve(three):
    window = three
    combo = window.plot_controls.curve_choice
    assert combo.isEditable() and combo.insertPolicy() == W.QComboBox.InsertPolicy.NoInsert
    completer = combo.completer()
    completer.setCompletionPrefix('amm')
    assert completer.currentCompletion() == 'gamma — w'
    combo.setEditText('gam')
    assert window.plot_controls.chosen_curve() is None
    window.plot_controls.add_curve.click()  # a partial search adds nothing
    assert choices(window) == ['beta — v', 'gamma — w']
    combo.setEditText('GAMMA — w')
    window.plot_controls.add_curve.click()
    gamma = window.datasets[2]
    assert gamma.visible and gamma.id in curve_ids(window)
    assert choices(window) == ['beta — v']
