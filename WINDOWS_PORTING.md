# Windows porting instructions for an AI coding agent

You are working on a Windows computer with a downloaded copy of **Rogi**, a
PySide6 desktop app for scientific data analysis. It was developed and tested
only on macOS. Your job is to make it run correctly on Windows. Follow this
file in order. Each task gives the exact location, the problem, the change to
make, and how to check it.

Written 2026-11-19 against commit `b7cb9eb` (branch `formula-columns`). If a
line number no longer matches, search for the quoted code instead.

---

## 0. Ground rules

1. **Do not change scientific behaviour.** Parsing, fitting, units, statistics
   and the project file format must give the same results as on macOS. Projects
   (`.rogi.h5`, `.json`) must stay readable on both systems; do not change the
   HDF5 layout, the `format`/`version` attributes, or any JSON keys.
2. **Keep changes small and portable.** Every fix must also work on macOS and
   Linux. Use `pathlib`, `tempfile` and `os.replace`, not Windows-only APIs,
   unless a task says otherwise.
3. **Raw data stays read-only, and saves stay atomic** (write to a temporary
   file, then replace). A failed save must leave the old file untouched.
4. **One concern per commit.** Use conventional commit messages, e.g.
   `fix(io): write map CSV exports as UTF-8`.
5. **Do not tick boxes in `docs/windows-readiness.md` without evidence.** Tick
   a box only when you ran the check and recorded the result (see section 5).
6. **Do not claim "Windows compatible".** State exactly what you tested: the
   Windows version, the architecture and the Python version.
7. Do not commit `example-data/`, `artifacts/`, `.venv/`, build output or
   `dist/`. They are ignored or must be.

## 1. Project facts you need

- Python package: `rogi/`. Entry points: `python -m rogi` (`rogi/__main__.py`)
  and the console script `rogi = rogi.ui:main` (`pyproject.toml`).
- Dependencies (`pyproject.toml`): Python >= 3.11, PySide6 6.7–6.x, numpy,
  scipy, matplotlib, h5py. Tests use pytest.
- `requirements-tested.txt` is a **macOS** snapshot. Do not assume it installs
  or is valid on Windows. Install from `pyproject.toml`.
- Settings are stored with `QSettings('Rogi', 'Rogi')` (`rogi/ui.py`). On
  Windows they go to the registry, which is fine.
- Keyboard shortcuts already use `QKeySequence.StandardKey` (Ctrl on Windows).
  The two custom shortcuts are `Ctrl+Shift+P` and `Ctrl+Shift+L`; Qt maps them
  correctly. The tooltips mention ⌘ only as the macOS alternative. Leave them.
- UTF-8 byte-order marks are already stripped (`text.removeprefix('\ufeff')`
  in `rogi/core.py`, `rogi/metadata.py`, `rogi/dialogs.py`), and CRLF line
  endings are handled by `splitlines()`.
- Docs to read if needed: `README.md`, `docs/architecture.md`,
  `docs/windows-readiness.md` (full checklist), `docs/limitations.md`,
  `VALIDATION.md` (macOS test record: 322 passed).

## 2. Set up and get a baseline (before any edits)

In PowerShell, from the project folder:

```powershell
py -3.12 --version                  # any 3.11+ is fine; record the exact version
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1          # if blocked: Set-ExecutionPolicy -Scope Process Bypass
python -m pip install --upgrade pip
python -m pip install -e ".[test]"
python -m pip freeze > windows-env.txt   # keep for the report; do not commit unless asked
$env:QT_QPA_PLATFORM = "offscreen"
python -m pytest -q -rs 2>&1 | Tee-Object baseline-tests.txt
```

Then launch the app once on the real desktop to confirm it starts:

```powershell
Remove-Item Env:QT_QPA_PLATFORM
python -m rogi
```

### Expected baseline failures (not bugs)

The `example-data/` folder is not in Git; the maintainer provides it
separately. Without it, tests that read
`example-data/260813/Spectrum/*.dat` or `example-data/260813/spm/*.spm`
**fail** with `FileNotFoundError` or an empty-glob assertion. They do not skip.
These tests are in `tests/test_metadata.py`, `tests/test_ui.py`,
`tests/test_spatial.py` and `tests/test_folder_conversion.py`. Two others
skip cleanly (`tests/test_performance.py`, `tests/test_photodiode_power.py`).

- Sort the baseline results into: (a) missing example data, (b) real Windows
  failures. Only (b) are your bugs.
- If the user can provide `example-data/260813/`, place it there and rerun.
- Optional improvement: make the example-data tests skip with a clear reason
  when the folder is missing (`pytest.mark.skipif(not EXAMPLES.exists(), ...)`),
  following the pattern in `tests/test_photodiode_power.py:95`.

If any test fails because a checked-in text file has CRLF line endings after
the download (Git `core.autocrlf=true`), that is a checkout setting, not a code
bug. Re-clone with `git -c core.autocrlf=false clone ...` and note it in the
report.

## 3. Required code fixes

Make these in order. After each one, rerun `python -m pytest -q` and confirm
that no new failures appeared.

### Fix 1 — Write CSV exports as UTF-8

**Problem.** `open(path, 'w')` without `encoding` uses the Windows ANSI code
page (usually cp1252). Unit labels such as `Ω`, `µ` or `°` can raise
`UnicodeEncodeError` or be written in a different encoding than on macOS.

**Locations.**
- `rogi/maps.py:72`: `with open(path, 'w', newline='') as stream:` (map CSV export)
- `rogi/maps_ui.py:205`: `with open(path, 'w', newline='') as stream:` (cross-section export)

**Change.** Add `encoding='utf-8'` to both, matching the existing exports in
`rogi/core.py:295` and `rogi/core.py:305`:

```python
with open(path, 'w', newline='', encoding='utf-8') as stream:
```

**Also check.** Search the whole repo for any other text-mode
`open(`/`.open(`/`read_text(`/`write_text(` call without `encoding=` and fix it
the same way (binary modes `'rb'`/`'wb'` and `h5py.File` are fine). To catch
leftovers, run the tests once with `$env:PYTHONWARNDEFAULTENCODING = "1"`
(Python 3.10+). It warns at every call that relies on the default encoding.

**Test.** Add a test that exports a map/section whose unit label contains `Ω`
and reads the file back with `encoding='utf-8'`.

### Fix 2 — Accept text files that are not UTF-8 when importing

**Problem.** Text import decodes strictly as UTF-8:
- `rogi/files.py:90` in `read_text_import`: `text = path.read_bytes().decode('utf-8')`
- `rogi/files.py:116` in `read_data_file`: `text = path.read_bytes().decode('utf-8')`

Windows instrument software (LabVIEW, Excel "CSV", older Nanonis/Spectrum
exporters) often writes cp1252. A single `µ` or `°` byte makes the import
fail with `UnicodeDecodeError`.

**Change.** Add one helper in `rogi/files.py` and use it at both locations:

```python
def decode_text(data: bytes) -> str:
    """UTF-8 first (the BOM is kept; callers strip it), then Windows-1252, then Latin-1."""
    for encoding in ('utf-8', 'cp1252'):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            pass
    return data.decode('latin-1')  # never fails: every byte maps to a character
```

- Keep `'utf-8'` (not `'utf-8-sig'`). The callers already strip `\ufeff`,
  and `source_text` should keep the file content unchanged.
- Do not change `rogi/files.py:287` (the file preview). It uses
  `errors='replace'` on purpose, to spot binary files.
- Do not change `rogi/nanonis.py` or `rogi/spm.py`. They decode binary
  headers as `latin-1` on purpose.

**Test.** Add tests that import a CSV and a `.dat` file written with
`'Voltage (µV),Temp (°C)\n1,2\n'.encode('cp1252')` and check the column names
and values. Also check that a UTF-8 file with a BOM still imports exactly as
before.

### Fix 3 — Handle "file in use" when saving

**Problem.** Saves write a temporary file and then call `os.replace(temporary, path)`.
On Windows, `os.replace` raises `PermissionError` (WinError 5 or 32) when the
target is open in another program: HDFView, a second Rogi window, Excel, or
briefly by OneDrive/Dropbox sync or antivirus scanning. macOS never does this.

**Locations (the same pattern three times).**
- `rogi/hdf5.py:89` in `save_hdf5`
- `rogi/project.py` in `save_project`: `os.replace(temporary, path)` (JSON branch)
- `rogi/presets.py:77` in `save_presets`

**Change.** Add one small helper and call it from all three places instead of
`os.replace`. Put it in a module that all three can import without creating an
import cycle (for example, a new `rogi/atomic.py`):

```python
import os, time

def replace_file(source, target, attempts=10, delay=0.2):
    """os.replace with short retries for transient Windows sharing locks."""
    for attempt in range(attempts):
        try:
            os.replace(source, target)
            return
        except PermissionError as error:
            if attempt == attempts - 1:
                raise PermissionError(
                    f'Could not save "{target}" because it is open or locked by another '
                    'program (for example HDFView, Excel, a second Rogi window, or cloud '
                    'sync). Close it and save again; the existing file was not changed.'
                ) from error
            time.sleep(delay)
```

- Leave each `finally:` block that deletes the temporary file exactly as it is.
  It is what guarantees "a failed save leaves the old file".
- In `save_hdf5`, the `h5py.File` and the fsync `open()` are already closed
  before the replace. Keep that order: Windows cannot replace or delete a file
  that is still open.
- No UI change should be needed. Save runs through `self.run_operation(...)`
  (`rogi/project_actions.py:491`), which catches any `Exception` and shows
  `str(error)` in a warning box (`rogi/ui.py:347-352`), so the message above
  reaches the user as written. Confirm this in the manual check (section 4,
  step 6).

**Test.** Monkeypatch `os.replace` to raise `PermissionError` twice and then
succeed (the save succeeds). Monkeypatch it to always raise (you get the
friendly error, the original file is unchanged, and no temporary file is left
in the folder). These tests also run on macOS.

### Fix 4 — Portable temporary folder in tests and scripts

**Problem.** Tests and scripts hard-code `/tmp/...`, which is not a standard
location on Windows.

**Locations.**
- `tests/conftest.py:4` and 14 test files that repeat
  `os.environ.setdefault('MPLCONFIGDIR', '/tmp/rogi-matplotlib-tests')`:
  `test_axis_format.py`, `test_clipboard.py`, `test_folder_conversion.py`,
  `test_history.py`, `test_images.py`, `test_legend_format.py`,
  `test_metadata.py`, `test_organization.py`, `test_panels.py`,
  `test_plot_context.py`, `test_plot_controls.py`, `test_spm.py`,
  `test_statistics.py`, `test_ui.py`. Find them all with
  `Select-String -Path tests\*.py -Pattern "/tmp"`.
- `scripts/benchmark.py:23` and `:142` (default `--output`),
  `scripts/prepare_spectrum.py:54`.

**Change.**

```python
import os, tempfile
os.environ.setdefault('MPLCONFIGDIR', os.path.join(tempfile.gettempdir(), 'rogi-matplotlib-tests'))
```

`conftest.py` runs before the test modules, so the per-file lines are
redundant. Either replace them all as above or delete them from the test
files and keep only `conftest.py`. For `benchmark.py`, use
`Path(tempfile.gettempdir()) / 'rogi-benchmark.json'`.

Also update the usage docstrings that say `.venv/bin/python` to mention
`.venv\Scripts\python.exe` on Windows (`scripts/benchmark.py`,
`scripts/prepare_spectrum.py`, `scripts/hdf5_trial.py`).

### Fix 5 — Fix whatever else the baseline shows

Any failure in category (b) from section 2 is in scope. For each one: find the
root cause, fix it portably, and add a regression test when practical. Likely
causes to check first:

- Comparing paths as strings that contain `/` (use `Path` objects or
  `Path.as_posix()` in tests). Note: `rogi/units.py:87` splits **unit
  strings** on `/`, not paths; it is correct. Leave it.
- Code that uses an OS path as an HDF5 group name, or the reverse. HDF5 names
  always use `/`. Keep them separate from filesystem paths.
- Opening a file that is still open (Windows locks open files). Close or exit
  the `with` block first.
- Case-insensitive filenames (`Data.CSV` vs `data.csv`), or sorting that
  differs between systems.
- `NamedTemporaryFile(delete=True)` reopened by name while still open. This
  fails on Windows; use `delete=False` and unlink afterwards (as `rogi/hdf5.py`
  does).

## 4. Native Windows check (manual, real desktop, not offscreen)

Run `python -m rogi` without `QT_QPA_PLATFORM` and work through these steps.
Record pass/fail and screenshots for any problems.

1. Open `examples\gaussian.csv` and `examples\linear.tsv`, and look at the
   preview and the columns.
2. Create an editable copy, edit a cell, then undo and redo with Ctrl+Z / Ctrl+Y.
3. Copy a table range and paste it into Excel and into Notepad, then paste back.
4. Run a linear fit and a Gaussian fit. Compare the parameters with the same
   fit on macOS, if the user can supply that, to a relative tolerance of 1e-9.
5. Save the project as `.rogi.h5` in a folder whose path contains a space and a
   non-English character (e.g. `C:\Users\<you>\Documents\Rogi tést\`). Close
   Rogi completely, reopen it, and open the project.
6. Keep the `.h5` open in another program (or simply open it in a second
   Rogi), then press Save in the first one. You should get the Fix 3 message
   and the file should be intact.
7. Export a data CSV, a fit CSV, PNG and SVG, and open each one in another
   program.
8. Open the Files window (Ctrl+Shift+L) and the plot window (Ctrl+Shift+P) on
   a data folder.
9. Repeat a few screens at 125%, 150% and 200% display scaling and look for
   cut-off controls.
10. Close the app while a fit is running. It should not crash or hang, and no
    `python.exe` should be left in Task Manager.

## 5. Optional: build a standalone Windows app

Do this only if the user asks for a version that runs without Python.

1. Add `packaging/windows/rogi_launcher.py`:
   ```python
   from rogi.ui import main
   main()
   ```
   (Do not package `rogi/__main__.py` directly. Its relative-import trick is
   meant for running from source.)
2. `python -m pip install pyinstaller`, then from the project root:
   ```powershell
   pyinstaller --noconfirm --windowed --name Rogi `
     --collect-submodules rogi --collect-data matplotlib `
     packaging\windows\rogi_launcher.py
   ```
3. Start `dist\Rogi\Rogi.exe` from Explorer and from a different working
   directory. Repeat the checks in section 4 against the built app. If Qt
   plugins or h5py DLLs are missing, add the matching `--collect-*` /
   `--hidden-import` options. Turn the final command into a committed
   `packaging/windows/build.ps1` script.
4. Add `build/` and `dist/` to `.gitignore`. Do not commit the build output.

## 6. Record the evidence and report back

When you are done:

1. Add a **Windows** section at the top of `VALIDATION.md` with: date, Windows
   edition/version and architecture, Python version, the
   `windows-env.txt` dependency versions (key packages only), the exact pytest
   command and the passed/failed/skipped counts, the failures caused only by
   missing `example-data`, and the manual check results from section 4.
2. In `docs/windows-readiness.md`, tick only the boxes you have evidence for.
3. In `README.md`, replace the line saying Windows has not been verified with
   the exact environment you tested. Add Windows install commands next to the
   macOS ones.
4. Report to the user:
   - each fix and its commit,
   - test counts before and after,
   - remaining failures and their causes,
   - manual check results,
   - anything you could not test (e.g. no example data, no second monitor,
     no packaged build).
