# Windows readiness checklist

Status: planned; Windows compatibility has not been verified. Existing validation records describe macOS testing. Check a task only when its evidence is recorded, not when its implementation is merely present.

Goal: a user on a supported Windows computer can install and use the distributed Rogi app without Python, an IDE, or developer tools, and exchange project files with macOS users.

## 1. Define support and acceptance criteria — before more release work

- [ ] Choose and document the supported Windows versions and CPU architectures. Start with one explicitly supported target; do not imply that other architectures are tested.
- [ ] Choose a supported Python version for the Windows build and verify that every required dependency installs on that target.
- [ ] Decide whether the initial release is an installer or a portable application folder, and document the installation and update workflow.
- [ ] Define representative small, typical, and large datasets, including a large multichannel scan and a folder of mixed instrument files.
- [ ] Set measurable targets for startup, import, folder conversion, project open/save, and memory use on a named reference Windows machine.
- [ ] Define release blockers: installation/startup failures, crashes in supported workflows, data loss or changed scientific results, broken save/reopen, and unusable core controls.

Done when: the supported environment, delivery format, datasets, performance targets, and blockers are written down.

## 2. Audit platform assumptions — during development

- [ ] Review application code, helper scripts, and tests for hardcoded `/tmp`, `/Users`, `/`, `.venv/bin`, shell commands, and macOS-only APIs.
- [ ] Replace the hardcoded `/tmp/rogi-matplotlib-tests` default in `tests/conftest.py` with a portable temporary-directory mechanism that avoids collisions between test runs.
- [ ] Use platform-aware path operations for filesystem paths; preserve logical HDF5 group names separately from operating-system paths.
- [ ] Ensure application startup does not depend on the current working directory or the source checkout being present.
- [ ] Resolve bundled resources from the installed application rather than relative to the launch directory.
- [ ] Write settings, caches, temporary files, and logs to suitable writable user locations, not the application installation folder.
- [ ] Audit temporary-file closure and replacement during JSON/HDF5 saves for Windows file-locking behavior.
- [ ] Ensure failed imports, exports, and saves show useful errors and preserve existing files and unsaved work.
- [ ] Review shortcuts for platform-standard Qt key bindings and remove assumptions that Command is available.
- [ ] Review background fitting, shutdown, and error handling for clean thread termination.

Done when: each finding is fixed or tracked with its user impact and a regression check where appropriate.

## 3. Add continuous Windows verification — before feature freeze

- [ ] Add a CI job on a Windows runner that installs the project and its test dependencies in a fresh environment.
- [ ] Run the entire existing test suite, including Qt integration tests, on each pull request and release candidate.
- [ ] Keep macOS verification alongside Windows so platform fixes do not introduce regressions.
- [ ] Retain the offscreen Qt test configuration for automated tests, while treating native desktop checks as a separate requirement.
- [ ] Ensure CI has every fixture it needs; identify tests depending on local `example-data` files and provide approved, reproducible fixtures.
- [ ] Capture the Python version, installed dependency versions, OS version, test results, and failure logs.
- [ ] Add focused Windows regressions for actual portability failures discovered during the audit.
- [ ] Make the Windows job a required release check; investigate skipped tests and failures rather than treating them as a pass.

Done when: a clean Windows runner completes the full intended suite with no unexplained failures or skips.

## 4. Test files and scientific workflows on Windows

- [ ] Import CSV, TSV, TXT, and DAT examples, including UTF-8 BOM and CRLF line endings.
- [ ] Import Spectrum DAT metadata, repeated channel names, timestamps, and lock-in channels; compare against the source columns.
- [ ] Import supported Bruker SPM and Nanonis SXM files and check channel values, units, dimensions, and scan directions.
- [ ] Confirm unsupported and malformed instrument files fail with understandable errors and no partial dataset additions.
- [ ] Convert nested folders containing mixed supported file types; verify grouping, channel retention, and failure behavior.
- [ ] Test filenames and directories with spaces, non-English characters, mixed-case extensions, and deep paths. Document any supported path-length limit.
- [ ] Test read-only destinations, an externally locked destination, and an interrupted or otherwise failed save; confirm the old project survives.
- [ ] Verify editable copies, missing-value handling, undo/redo, grouping, renaming, and deletion behavior.
- [ ] Run linear and Gaussian fits with known expected results, including missing values, invalid ranges, and background-fit failures.
- [ ] Export data CSV, fit CSV, PNG, and SVG; inspect contents and reopen exports with independent viewers where applicable.

Done when: workflows pass with expected data and numerical tolerances, and failures leave recoverable state.

## 5. Verify the native Windows interface

- [ ] Launch on a real Windows desktop and use the app through complete workflows; an offscreen test alone does not satisfy this item.
- [ ] Check native Open, Import, Save, Save As, export, and folder-selection dialogs, including cancellation and overwrite confirmation.
- [ ] Check menus, tooltips, focus order, keyboard navigation, and standard Ctrl shortcuts for copy/paste, undo/redo, open, and save.
- [ ] Copy rectangular tables to and from Excel and a plain text editor; check headers, missing cells, tabs, and newline handling.
- [ ] Check dataset selection, checkboxes, multiselection, filtering, and X/Y channel changes with actual mouse events.
- [ ] Check plot pan/zoom, toolbar history, fit-range handles, statistics selection, and cursor readouts.
- [ ] Check 2D map channel switching, comparison, color bars, contrast controls, zoom, and export.
- [ ] Inspect layouts at 100%, 150%, and 200% display scaling and at the minimum supported screen size.
- [ ] Move the window between monitors with different scaling, if supported; check text, plots, pointer coordinates, and dialogs.
- [ ] Check long filenames/channel labels and expanded controls for clipped buttons or inaccessible content.
- [ ] Check unsaved-change prompts when opening another project and closing the app, including Cancel.
- [ ] Close during or after a background fit and confirm there is no crash, hang, or orphaned process.

Done when: all essential workflows are usable with native Windows input and display behavior; screenshots and defects are recorded.

## 6. Verify macOS–Windows project exchange

- [ ] Create a project on macOS with raw data, edited copies, metadata, groups, fit results, and saved plot settings; open it on Windows.
- [ ] Modify and save that project on Windows, then reopen it on macOS.
- [ ] Repeat with HDF5 and supported JSON project files, including older supported project versions.
- [ ] Compare arrays, missing values, IDs, parent relationships, units, metadata, source text, and fit provenance after each round trip.
- [ ] Compare numerical fit results using justified tolerances; do not require identical binary files or pixel-identical plots.
- [ ] Move a saved project away from its original input files and confirm embedded data/source text remain usable as documented.
- [ ] Confirm session-only controls are documented so users do not mistake intentionally unsaved state for a portability bug.

Done when: round trips preserve the documented project contents without reliance on original macOS paths.

## 7. Build the Windows distribution — before release-candidate testing

- [ ] Select and validate a packaging tool against Rogi's Python, PySide6, NumPy, SciPy, Matplotlib, and h5py dependencies.
- [ ] Add a reproducible Windows build script and packaging configuration to the repository.
- [ ] Build on Windows using a recorded dependency set; do not assume the macOS `requirements-tested.txt` snapshot validates Windows.
- [ ] Include the required Qt platform plugins, native numerical/HDF5 libraries, Matplotlib resources, and application assets.
- [ ] Add application name, version, icon, and appropriate executable metadata.
- [ ] Ensure normal GUI launch has no distracting terminal window and that startup failures produce actionable diagnostics.
- [ ] Include dependency licenses/notices and concise installation, troubleshooting, and version information.
- [ ] Verify the packaged program launches from Explorer, a shortcut, and a different working directory.
- [ ] If using an installer, test installation as a standard user, upgrades, uninstall, and preservation of user-created project files.
- [ ] Decide how signing will be handled for distribution; test the actual downloaded artifact under ordinary Windows security settings and record any warnings.
- [ ] Produce a versioned artifact and checksum tied to the source revision and build record.

Done when: another person can reproduce the artifact and launch it without the development environment.

## 8. Clean-machine acceptance — required for each release candidate

Use the exact artifact intended for distribution on a clean supported Windows machine or VM with a native desktop, no Python installation, no source checkout, and no developer tools.

- [ ] Download or copy the release artifact through the intended delivery route and install/extract it using the documented steps.
- [ ] Launch as a standard user and confirm normal startup without network access if the application is intended to work offline.
- [ ] Import a representative DAT spectrum, SPM file, and SXM scan; inspect channels and metadata.
- [ ] Convert a representative mixed folder and open the resulting HDF5 project.
- [ ] Create and edit a copy, use undo/redo, perform a fit, and inspect residuals/statistics.
- [ ] Use line plots and 2D maps; export data, fit results, and an image.
- [ ] Save, close the application fully, relaunch, and reopen the project; compare preserved data and results.
- [ ] Repeat representative large-data operations and record timings, peak memory, and responsiveness against the agreed targets.
- [ ] Exercise failed-open/failed-save scenarios and confirm the user can recover without losing existing data.
- [ ] Complete the native UI and cross-platform checks above against the packaged build, not just the source version.
- [ ] Resolve all release blockers and rerun affected checks on the rebuilt artifact.

Done when: the actual release artifact completes the agreed workflows on every declared supported Windows target.

## 9. Record evidence and maintain readiness

- [ ] Add Windows installation, launch, update, and troubleshooting instructions to `README.md`.
- [ ] Add a Windows results section to `VALIDATION.md` with date, tester, source revision, artifact version/checksum, OS/architecture, hardware, scaling, dependencies, test command/results, manual results, and known limitations.
- [ ] Maintain a short acceptance-results table: check, environment, result, evidence link, and associated defect.
- [ ] State exactly which Windows environments were tested; avoid claiming blanket Windows compatibility.
- [ ] Rerun packaging and clean-machine acceptance after dependency, packaging, file-storage, or significant UI changes.
- [ ] Keep the previous release available and document how to revert without overwriting user projects.

## Final release gate

Release as Windows-ready only when Windows automated checks pass, native workflows are usable, macOS–Windows round trips preserve data, the exact distributed build passes clean-machine acceptance, and no release blockers remain. Record unresolved nonblocking limitations in the release notes.
