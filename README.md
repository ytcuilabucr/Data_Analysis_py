# Rogi scientific analysis

A local desktop workspace for importing, inspecting, plotting, fitting, and
preserving numeric data. Uses PySide6, NumPy, SciPy, Matplotlib and h5py.
No service, account, or database is required.

## Install and run

From the project folder on macOS/Linux:

```sh
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[test]"
python -m rogi
```

In PyCharm, open this folder, select `.venv/bin/python`, and create a run
configuration with module `rogi` and the project folder as its working directory.
The Windows interpreter path is `.venv\Scripts\python.exe`; **Windows
compatibility has not been verified**.

Supported Python and dependency ranges are in [pyproject.toml](pyproject.toml).
[requirements-tested.txt](requirements-tested.txt) is a recorded environment
snapshot, not a cross-platform lockfile. The freshly checked environment and
exact test command are in [VALIDATION.md](VALIDATION.md).

## Quick start

- **Open…** `examples/gaussian.csv` or `examples/linear.tsv`; inspect the preview
  and select numeric columns. The **Files** panel lists a whole data folder for
  batch and automatic loading.
- Select a dataset and its X/Y channels. Check datasets to overlay them.
- Raw data is read-only. Use **Editable copy** before changing table cells.
- Enable **View → Show fitting**, choose a model and range, then **Fit selected dataset**.
- **Save as…** writes a portable Rogi HDF5 project; **Open…** restores it.
  Export data or fits as CSV, and plots as PNG/SVG.

## Feature overview

- Text, Spectrum DAT, Bruker SPM and Nanonis SXM imports; a Files window for batch and
  automatic loading from a data folder; folder conversion.
- Metadata search, grouping, annotations, table clipboard and undo/redo.
- Line/scatter plots, channel controls, statistics, fitting and saved views.
- Scan images, cursor profiles, spectrum maps, analysis pipelines and presets.
- Immutable raw data, derived-data provenance, HDF5/JSON projects and atomic saves.
- Background operations with busy indicators, editing locks and cancellation where supported.

See the **[user-guide table of contents](docs/user-guide/index.md)** for detailed
workflows and scientific assumptions. Local instrument fixtures are not in Git;
see [example-data setup](docs/user-guide/example-data.md) before running tests.

## Validation and limits

**Automated UI tests are offscreen. Native dialogs and complete native workflows
remain unvalidated; Windows is unverified.** Recorded performance measurements
cover specific offscreen workloads, not native large-file acceptance or arbitrary
input sizes. Projects remain fully in memory.

- [Current test results and chronological validation history](VALIDATION.md)
- [Limitations and remaining manual checks](docs/limitations.md)
- [Measured performance and memory](docs/performance.md)
- [Current roadmap](PLAN.md) · [Changelog from Git](CHANGELOG.md)
- [Architecture](docs/architecture.md) · [Windows readiness](docs/windows-readiness.md)
