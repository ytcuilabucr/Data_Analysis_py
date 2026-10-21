"""Convert instrument examples to an editable Rogi project and verify the UI.

Run: .venv/bin/python scripts/prepare_spectrum.py
Open result: .venv/bin/python scripts/prepare_spectrum.py --open
--open only opens the existing project; it never regenerates it.
"""
import argparse
import os
from pathlib import Path
import tempfile

import numpy as np
from rogi.core import parse_dat
from rogi.project import save_project, load_project

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'artifacts/spectrum.rogi.h5'


def convert():
    if OUTPUT.exists():
        raise FileExistsError(f'Refusing to overwrite possible user edits: {OUTPUT}')
    datasets = []
    paths = sorted((ROOT / 'example-data/Spectrum').glob('*.dat'))
    if not paths:
        raise ValueError('No Spectrum .dat files found')
    for path in paths:
        # Share the app's parser: preserve every numeric channel, including
        # numeric Time, duplicate signals, and missing measurements.
        raw = parse_dat(path.read_bytes().decode('utf-8'),
                        name=path.stem + ' (raw)',
                        source=path.relative_to(ROOT / 'example-data').as_posix())
        columns = raw.columns
        x = next((i for i, c in enumerate(columns) if 'Voltage' in c), 0) if path.stem.startswith('IV') else columns.index('Rotator_Theta')
        y = columns.index('Lockin1_X') if 'Lockin1_X' in columns else columns.index('K2401_source_Current')
        raw.xcol, raw.ycol, raw.visible = x, y, False
        editable = raw.derived()
        editable.name = path.stem + ' (editable)'
        editable.visible = len(datasets) == 0
        datasets.extend([raw, editable])
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    save_project(OUTPUT, datasets, {'title': 'Spectrum measurements', 'xlabel': '', 'ylabel': ''})
    restored, _ = load_project(OUTPUT)
    for original, loaded in zip(datasets, restored, strict=True):
        np.testing.assert_array_equal(original.values, loaded.values)
        assert original.source_text == loaded.source_text
        assert original.columns == loaded.columns
        assert original.parent == loaded.parent
    return len(paths), sum(len(d.values) for d in datasets if d.raw)


def verify_ui():
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    os.environ.setdefault('MPLCONFIGDIR', '/tmp/rogi-matplotlib-tests')
    from PySide6 import QtWidgets as W
    from rogi.ui import MainWindow
    app = W.QApplication.instance() or W.QApplication([])
    window = MainWindow()
    try:
        window.open_project(str(OUTPUT))
        window.browser.setCurrentRow(1)
        assert not window.current().raw
        original = window.current().values[0, window.current().ycol]
        value = float(original) + 0.12345
        index = window.table_model.index(0, window.current().ycol)
        assert window.table_model.setData(index, str(value))
        with tempfile.TemporaryDirectory() as directory:
            window.path = Path(directory) / 'edit-test.h5'
            assert window.save()
            window.open_project(str(window.path))
            assert window.datasets[1].values[0, window.datasets[1].ycol] == value
            assert window.datasets[0].values[0, window.datasets[0].ycol] == original
            assert window.datasets[1].revision == 1
        # Deliver the untouched project, with an editable dataset selected.
        window.open_project(str(OUTPUT))
        window.browser.setCurrentRow(1)
        window.show()
        app.processEvents()
        assert window.grab().save(str(OUTPUT.with_suffix('.png')))
    finally:
        window.dirty = False
        window.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--open', action='store_true', help='Open existing project without reconverting')
    args = parser.parse_args()
    if args.open:
        from PySide6 import QtWidgets as W
        from rogi.ui import MainWindow
        app = W.QApplication.instance() or W.QApplication([])
        window = MainWindow()
        window.open_project(str(OUTPUT))
        window.browser.setCurrentRow(1)
        window.show()
        app.exec()
    else:
        files, rows = convert()
        verify_ui()
        print(f'Converted {files} files, {rows} source rows; {files} raw + {files} editable datasets.')
        print('Verified numeric round-trip and UI edit/save/reopen; test edits were saved only to a temporary file.')
        print(OUTPUT)


if __name__ == '__main__':
    main()
