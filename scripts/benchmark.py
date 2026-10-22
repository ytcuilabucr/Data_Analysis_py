#!/usr/bin/env python3
"""Reproducible, isolated-process timings and 10 ms Qt event-loop gap probe.

Run: QT_QPA_PLATFORM=offscreen .venv/bin/python scripts/benchmark.py --output /tmp/before.json
HDF5 files are projects, not supported raw imports. Import/conversion therefore
use their original example-data/260813 source folder, plus a generated SXM scan.
"""
import argparse
import gc
import json
import os
from pathlib import Path
import platform
import resource
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('MPLCONFIGDIR', '/tmp/rogi-benchmark-matplotlib')


def measure(operation, settle_ms=100, ready=lambda: True):
    """Measure a real GUI callback, including deferred draws, without polling it."""
    from PySide6 import QtCore as C
    loop = C.QEventLoop()
    timer = C.QTimer()
    timer.setTimerType(C.Qt.TimerType.PreciseTimer)
    timer.setInterval(10)
    ticks, result, errors = [], [], []
    timer.timeout.connect(lambda: ticks.append(time.perf_counter()))
    times = []
    gc_starts, gc_pauses = {}, []
    def gc_event(phase, info):
        generation = info['generation']
        if phase == 'start':
            gc_starts[generation] = time.perf_counter()
        elif generation in gc_starts:
            gc_pauses.append(time.perf_counter() - gc_starts.pop(generation))
    gc.callbacks.append(gc_event)
    def invoke():
        if not ready():
            C.QTimer.singleShot(10, invoke)
            return
        times.append(time.perf_counter())
        try:
            result.append(operation())
        except BaseException as error:
            errors.append(error)
        times.append(time.perf_counter())
        C.QTimer.singleShot(settle_ms, loop.quit)
    timer.start()
    C.QTimer.singleShot(50, invoke)
    loop.exec()
    timer.stop()
    gc.callbacks.remove(gc_event)
    if errors:
        raise errors[0]
    gaps = [b-a for a,b in zip(ticks, ticks[1:])]
    return dict(seconds=times[1]-times[0], max_gap_ms=1000*max(gaps, default=0), ticks=len(ticks),
                max_gc_pause_ms=1000*max(gc_pauses, default=0)), result[0]


def synthetic_scan(path, side=1024, channels=8):
    import numpy as np
    header = (f':NANONIS_VERSION:\n2\n:SCANIT_TYPE:\nFLOAT MSBFIRST\n'
              f':SCAN_PIXELS:\n{side} {side}\n:DATA_INFO:\n'
              'Channel\tName\tUnit\tDirection\tCalibration\tOffset\n'
              + ''.join(f'{i}\tSignal{i}\tV\tforward\t1\t0\n' for i in range(channels))
              + ':SCANIT_END:\n\n').encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    x = np.arange(side*side, dtype=np.float64)
    with path.open('wb') as stream:
        stream.write(header + b'\x1a\x04')
        for i in range(channels):
            stream.write((np.sin(x/1000+i)+i).astype('>f4').tobytes())


def child(operation, path, temp):
    from PySide6 import QtCore as C, QtWidgets as W
    from rogi import ui
    from rogi.project import load_project, save_project, convert_folder
    from rogi.dialogs import SpmImportDialog
    app = W.QApplication.instance() or W.QApplication([])
    ui.project_preferences = lambda: C.QSettings(str(temp/'prefs.ini'), C.QSettings.Format.IniFormat)
    window = ui.MainWindow()
    window.canvas.draw()
    app.processEvents()
    retained = []
    if operation == 'import':
        def work():
            dialog = SpmImportDialog(path, window)
            dialog.import_data()
            retained.append(dialog)
            return len(dialog.datasets)
    elif operation == 'conversion':
        def work():
            # The GUI wrapper also opens the generated project; conversion itself
            # is isolated here so its cost is not counted twice.
            if hasattr(window, 'run_operation'):
                return window.run_operation('Converting folder', lambda: convert_folder(path, temp/'converted.h5'))
            return convert_folder(path, temp/'converted.h5')
    elif operation == 'open':
        def work():
            window.open_project(path, confirm=False)
            window.canvas.draw()
            return len(window.datasets)
    elif operation == 'save':
        window.datasets, _ = load_project(path)
        window.path = temp/'saved.h5'
        def work():
            return window.save()
    elif operation == 'first_plot':
        datasets, _ = load_project(path)
        def work():
            window.datasets = datasets
            window.refresh_history_view()
            window.canvas.draw()
            return len(datasets)
    else:
        raise ValueError(operation)
    metrics, _ = measure(work, ready=lambda: not getattr(window, "operation_active", False))
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    metrics['peak_rss_mb'] = rss/(1024**2 if sys.platform == 'darwin' else 1024)
    metrics.update(operation=operation, input=Path(path).name)
    window.dirty = False
    window.close()
    print('RESULT '+json.dumps(metrics), flush=True)


def versions():
    from importlib.metadata import version
    return dict(machine=platform.platform(), processor=platform.processor(), python=sys.version,
                packages={n: version(n) for n in ['numpy','scipy','h5py','matplotlib','PySide6','pytest']})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('/tmp/rogi-benchmark.json'))
    parser.add_argument('--child', choices=['import','conversion','open','save','first_plot'])
    parser.add_argument('--input', type=Path)
    parser.add_argument('--temp', type=Path)
    parser.add_argument('--only', help='Substring of case label to run')
    args = parser.parse_args()
    if args.child:
        return child(args.child, args.input, args.temp)
    with tempfile.TemporaryDirectory(prefix='rogi-benchmark-') as directory:
        temp = Path(directory)
        synthetic = temp/'synthetic'/'large.sxm'
        synthetic_scan(synthetic)
        from rogi.project import convert_folder
        synthetic_project = temp/'synthetic.h5'
        convert_folder(synthetic.parent, synthetic_project)
        sources = ROOT/'example-data'/'260813'
        raw = max(sources.rglob('*.spm'), key=lambda p:p.stat().st_size)
        cases = [(op,p) for p in sorted((ROOT/'example-data').glob('260813*.h5'))+[synthetic_project]
                 for op in ['open','save','first_plot']]
        cases += [('import',raw),('conversion',sources),('import',synthetic),('conversion',synthetic.parent)]
        report = dict(environment=versions(), clock='perf_counter; 10 ms precise QTimer', results=[])
        print(f'{"Input":30} {"Operation":12} {"Seconds":>10} {"Gap ms":>10} {"Peak RSS MiB":>12}', flush=True)
        for index,(op,path) in enumerate(cases):
            if args.only and args.only not in f'{path.name}/{op}':
                continue
            case_temp = temp/str(index)
            case_temp.mkdir()
            process = subprocess.run([sys.executable,__file__,'--child',op,'--input',str(path),'--temp',str(case_temp)],
                                     capture_output=True,text=True)
            if process.returncode:
                raise RuntimeError(process.stdout+'\n'+process.stderr)
            result = json.loads(next(s[7:] for s in process.stdout.splitlines() if s.startswith('RESULT ')))
            report['results'].append(result)
            args.output.write_text(json.dumps(report,indent=2)+'\n')
            print(f'{result["input"]:30} {op:12} {result["seconds"]:10.3f} {result["max_gap_ms"]:10.1f} {result["peak_rss_mb"]:12.1f}',flush=True)


if __name__ == '__main__':
    main()
