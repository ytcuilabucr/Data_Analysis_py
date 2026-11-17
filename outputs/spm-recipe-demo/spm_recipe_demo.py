"""Build a display-styled recipe on one SPM file, save it in the project .h5, reopen, apply to another file."""
import sys
from pathlib import Path
from PySide6 import QtWidgets as W
import h5py
from rogi.ui import MainWindow
from rogi.spm import load_spm
from rogi.scanfile import bundle_channels
from rogi.analysis_ui import AnalysisDialog
from rogi.image_analysis import ImagePreviewDialog
from rogi.project import save_project

root, out = Path(sys.argv[1]), Path(sys.argv[2])
out.mkdir(exist_ok=True)
CHANNEL = 'Height Sensor (Retrace)'
NAME = 'Height: centre + smooth (afmhot)'
project = out / 'spm_recipe_demo.rogi.h5'
app = W.QApplication.instance() or W.QApplication([])


def show(window, name):
    browser = window.browser_panel.browser
    row = next(r for r in range(browser.count()) if window.dataset_for_item(browser.item(r)).name == name)
    browser.setCurrentRow(row)
    window.plot_tabs.setCurrentIndex(1)
    viewer = window.image_viewer
    app.processEvents()
    viewer.channel.setCurrentIndex(next(i for i in range(viewer.channel.count())
                                        if viewer.channel.itemText(i).startswith(CHANNEL)))
    app.processEvents()
    return viewer


# 1. Import both scans, tune colors on file A in 2D Map with the sliders.
window = MainWindow()
window.resize(1500, 1000)
for f in ('CaptureFile.0_00120.spm', 'CaptureFile.0_00121.spm'):
    window.add_dataset(bundle_channels(load_spm(root / f)))
viewer = show(window, 'CaptureFile.0_00120')
viewer.palette.setCurrentText('afmhot')
viewer.brightness.setValue(10)
viewer.contrast.setValue(30)
viewer.gamma.setValue(-20)
app.processEvents()
viewer.figure.savefig(out / 'A_2dmap_tuned.png', dpi=110)

# 2. Save the recipe in Analysis pipeline…, then save the project as HDF5.
editor = AnalysisDialog(viewer.current, window, window.pipeline_presets, window.pipeline_presets_changed,
                        viewer.display_settings())
editor.load_operations([dict(operation='mean_subtract', parameters={}),
                        dict(operation='moving_average', parameters={'window': 3})])
editor.display_box.setChecked(True)
editor.store_preset(NAME)
editor.close()
save_project(project, window.datasets, window.settings())
window.dirty = False
window.close()

# 3. Reopen the project in a fresh window and click the preset on file B (then A for comparison).
window = MainWindow()
window.resize(1500, 1000)
window.open_project(str(project), confirm=False)
print('presets after reopening:', list(window.pipeline_presets))
def capture(dialog):
    tag = 'A' if window.image_viewer.current.name.startswith('CaptureFile.0_00120 ') else 'B'
    dialog.figure.set_size_inches(11, 5)
    dialog.figure.savefig(out / f'{tag}_preset_preview.png', dpi=110)
    artists = [ax.images[0] for ax in dialog.figure.axes if ax.images]
    print(tag, 'color limits (1e9 counts):', [tuple(round(v / 1e9, 3) for v in a.get_clim()) for a in artists],
          artists[0].get_cmap().name, f'γ={artists[0].norm.gamma}', '|', dialog.status.text())
    return W.QDialog.DialogCode.Rejected
ImagePreviewDialog.exec = capture
for name in ('CaptureFile.0_00121', 'CaptureFile.0_00120'):
    viewer = show(window, name)
    next(b for b in viewer.findChildren(W.QPushButton) if b.text() == NAME).click()
    app.processEvents()
print('datasets:', len(window.datasets), '| modified by previews:', window.dirty)
window.dirty = False
window.close()

with h5py.File(project, 'r') as file:
    file['pipeline_presets'].visititems(lambda path, item: print(' /pipeline_presets/' + path, dict(item.attrs)))
