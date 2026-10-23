"""Window-level project commands and persistence coordination.

Each command receives the MainWindow explicitly. Panels do not depend on this
module: the coordinator owns sequencing across panels, history and file actions.
"""
import csv
import json
from copy import deepcopy
from pathlib import Path
from PySide6 import QtCore as C, QtWidgets as W, QtGui as G
from .core import export_data as write_data, export_fit as write_fit
from .project import load_project, convert_folder as convert_project_folder
from .scanfile import consolidate_legacy
from .grouping import path_label
from .navigation import export_figure
from .operations import dialog_parent
from . import plot_windows
from .command_bar import CommandBar
from .files import (DATA_SUFFIXES, SCAN_SUFFIXES, is_project, natural_key, resolved, read_data_file,
                    read_with_template, format_name, sort_by_x, folder_group)


def _build_menus(self):
    self.file_menu = self.menuBar().addMenu("File")
    self.edit_menu = self.menuBar().addMenu("Edit")
    self.undo_action = self.history.createUndoAction(self, "Undo")
    self.redo_action = self.history.createRedoAction(self, "Redo")
    self.undo_action.setShortcuts(G.QKeySequence.keyBindings(G.QKeySequence.StandardKey.Undo))
    self.redo_action.setShortcuts(G.QKeySequence.keyBindings(G.QKeySequence.StandardKey.Redo))
    self.edit_menu.addAction(self.undo_action)
    self.edit_menu.addAction(self.redo_action)
    self.history.indexChanged.connect(self.update_dirty)
    self.show_fitting = self.menuBar().addMenu("View").addAction("Show fitting")
    self.saved_views_menu = self.show_fitting.parent().addMenu("Saved views")
    self.refresh_saved_views_menu()
    self.show_fitting.setCheckable(True)
    self.show_plot_controls = self.show_fitting.parent().addAction("Show plot controls")
    self.show_plot_controls.setCheckable(True)
    self.show_statistics = self.show_fitting.parent().addAction("Show statistics")
    self.show_statistics.setCheckable(True)
    # Placed above the file buttons by MainWindow; wraps instead of hiding commands.
    toolbar = self.project_toolbar = CommandBar(self)
    self.project_actions = {}
    standard_keys = {"Open…": G.QKeySequence.StandardKey.Open,
                     "Save": G.QKeySequence.StandardKey.Save,
                     "Save as…": G.QKeySequence.StandardKey.SaveAs}
    # Open… takes projects and data files alike; the Files panel lists a whole folder.
    for label, function in [("Open…", self.open_files),
                            ("Save", self.save), ("Save as…", lambda: self.save(True)),
                            ("Editable copy", self.make_copy), ("Analysis pipeline…", self.analysis_pipeline),
                            ("Apply pipeline preset…", self.apply_pipeline_preset),
                            ("Reopen analysis recipe…", self.reopen_analysis_recipe),
                            ("2D spectrum map…", self.spectrum_map),
                            ("Export data…", self.export_data),
                            ("Export fit…", self.export_fit), ("Export plot…", self.export_plot)]:
        action = self.project_actions[label] = toolbar.addAction(label)
        if label in standard_keys:
            action.setShortcuts(G.QKeySequence.keyBindings(standard_keys[label]))
            self.file_menu.addAction(action)
        action.triggered.connect(lambda checked=False, fn=function: self.guard(fn))
        if label == "Open…":
            action.setToolTip("Open a project, or load data files into this one")
            self.convert_action = self.file_menu.addAction("New project from folder…")
            self.convert_action.triggered.connect(lambda: self.guard(self.convert_folder))
        if label == "Export fit…":
            self.export_fit_action = action
            action.setVisible(False)
    _build_analysis_menu(self)
    # Shortcuts also work while the plot window is the active window.
    for action in [self.undo_action, self.redo_action, *self.project_actions.values()]:
        action.setShortcutContext(C.Qt.ShortcutContext.ApplicationShortcut)
    self.recent_menu = self.file_menu.addMenu("Recent projects")
    self.refresh_recent_projects()


ANALYSIS_ACTIONS = ("Analysis pipeline…", "Apply pipeline preset…", "Reopen analysis recipe…")


def _build_analysis_menu(self):
    """Mirror the pipeline toolbar buttons in an Analysis menu."""
    actions = [self.project_actions[label] for label in ANALYSIS_ACTIONS]
    actions[0].setToolTip("Create a pipeline for the selected dataset(s)")
    actions[1].setToolTip("Run a saved preset on every selected dataset")
    actions[2].setToolTip("Edit the recipe that produced the selected result")
    self.analysis_menu = W.QMenu("Analysis", self)
    self.analysis_menu.setToolTipsVisible(True)
    self.analysis_menu.addActions(actions)
    self.analysis_menu.aboutToShow.connect(lambda: update_analysis_actions(self))
    self.menuBar().insertMenu(self.show_fitting.parent().menuAction(), self.analysis_menu)
    # No dataset or preset exists yet; later selection, history and preset changes re-enable these.
    actions[1].setEnabled(False)
    actions[2].setEnabled(False)


def update_analysis_actions(self, *args):
    """Enable the pipeline commands when the selection supports them."""
    current = self.current()
    self.project_actions["Apply pipeline preset…"].setEnabled(
        bool(self.selected_datasets() and self.pipeline_presets))
    self.project_actions["Reopen analysis recipe…"].setEnabled(
        bool(current and current.analysis and current.analysis.get('version') == 1))


def update_dirty(self, *args):
    self.dirty = self.external_dirty or not self.history.isClean()
    self.setWindowTitle(f"Rogi — {self.path.name if self.path else 'Untitled'}" + (" *" if self.dirty else ""))


def changed(self):
    if not self.replaying and not self.opening:
        self.external_dirty = True
        self.update_dirty()


OPEN_FILTER = ("Projects and data (*.h5 *.hdf5 *.json *.csv *.tsv *.txt *.dat *.spm *.sxm);;"
               "Rogi projects (*.h5 *.hdf5 *.json);;"
               "Data files (*.csv *.tsv *.txt *.dat *.spm *.sxm);;All files (*)")


def open_files(self, paths=None):
    """Open one project, or load data files into the current one."""
    if paths is None:
        paths, _ = W.QFileDialog.getOpenFileNames(self, "Open", self.files_panel.folder or "", OPEN_FILTER)
    paths = [str(path) for path in paths]
    if not paths:
        return
    folders = [p for p in paths if Path(p).is_dir()]
    if folders:
        # A dropped folder is listed in the Files panel rather than loaded wholesale.
        self.files_panel.set_folder(folders[-1])
        self.show_files_button.setChecked(True)
        paths = [p for p in paths if p not in folders]
        if not paths:
            return
    projects = [p for p in paths if is_project(p)]
    if projects:
        if len(paths) > 1:
            raise ValueError("Open one project at a time, or choose only data files to load.")
        return self.open_project(projects[0])
    unsupported = [Path(p).name for p in paths if Path(p).suffix.lower() not in DATA_SUFFIXES]
    if unsupported:
        raise ValueError(f"Unsupported file type: {', '.join(unsupported)}")
    if not self.files_panel.folder:
        self.files_panel.set_folder(str(Path(paths[0]).parent))
    options = self.files_panel.options()
    # Open… always previews, as the import dialog did; panel loads follow its checkbox.
    options['preview'] = True
    return self.import_paths(paths, **options)


def import_paths(self, paths, *, preview=False, name_pattern='', start=0, grouping='ask',
                 sort_x=False, folder=None):
    """Load data files into the project as one undoable step.

    With preview, the first file's import dialog sets the columns or channels for
    the rest. Files that fail are skipped and reported; the others still load.
    """
    from .dialogs import ImportDialog, SpmImportDialog, ImportGroupDialog
    paths = sorted(dict.fromkeys(resolved(p) for p in paths), key=natural_key)
    if not paths:
        return []
    imported, skipped, rest = [], [], paths
    if preview:
        first = paths[0]
        dialog = (SpmImportDialog if Path(first).suffix.lower() in SCAN_SUFFIXES else ImportDialog)(first, self)
        if not dialog.exec():
            return []
        imported = [(first, dialog.datasets[0] if isinstance(dialog, SpmImportDialog) else dialog.dataset)]
        template, rest = dialog.template(), paths[1:]
        read = lambda path: read_with_template(path, template)
    else:
        read = read_data_file
    if rest:
        def work(check, commit):
            results = []
            for path in rest:
                check()
                try:
                    results.append((path, read(path), None))
                except (ValueError, OSError, UnicodeError, csv.Error) as error:
                    results.append((path, None, str(error)))
            return results
        results = self.run_operation(f"Loading {len(rest)} file(s)", work, cancellable=True, cooperative=True)
        imported += [(path, dataset) for path, dataset, error in results if dataset is not None]
        skipped = [f"{Path(path).name}: {error}" for path, dataset, error in results if error]
    if not imported:
        raise ValueError("No files were loaded.\n" + "\n".join(skipped))
    for number, (path, dataset) in enumerate(imported, start=start):
        dataset.name = format_name(name_pattern, path, number)
        if sort_x:
            sort_by_x(dataset)
    datasets = [dataset for _, dataset in imported]
    if grouping == 'folders' and folder:
        for path, dataset in imported:
            dataset.group = folder_group(path, folder)
    elif grouping == 'last' and self.last_import_group:
        for dataset in datasets:
            set_group_path(dataset, self.last_import_group)
    elif grouping == 'ask' and (self.datasets or self.path):
        destination = ImportGroupDialog(datasets[0], self.datasets, self.path, self)
        if not destination.exec():
            return []
        self.last_import_group = destination.selected_path()
        for dataset in datasets:
            set_group_path(dataset, self.last_import_group)
    # Reveal the newly loaded files even if the browser was filtered.
    self.browser_panel.reset_filters()
    for index, dataset in enumerate(datasets):
        dataset.visible = index == 0
    self.add_datasets(datasets)
    self.files_panel.advance_number(len(datasets))
    message = f"Loaded {len(datasets)} file(s). Use Save to store them in the project."
    if skipped:
        message = f"Loaded {len(datasets)}, skipped {len(skipped)} file(s). Use Save to store them."
        W.QMessageBox.warning(dialog_parent(self), "Rogi", "Some files were not loaded:\n\n" + "\n".join(skipped))
    self.statusBar().showMessage(message, 8000)
    return datasets


def set_group_path(dataset, path):
    dataset.group_path = deepcopy(path)
    dataset.group = path_label(dataset.group_path)


def auto_load(self, paths, options):
    """Watcher loads wait for any running operation instead of interrupting it."""
    if getattr(self, 'operation_active', False) or (self.worker and self.worker.isRunning()):
        C.QTimer.singleShot(1000, lambda: auto_load(self, paths, options))
        return
    self.guard(lambda: self.import_paths(paths, **options))


def convert_folder(self, folder=None):
    if folder is None:
        folder = W.QFileDialog.getExistingDirectory(
            self, 'Select folder of CSV, TSV, TXT, DAT, SPM, or SXM files', self.files_panel.folder or '')
    if not folder:
        return
    folder = Path(folder)
    destination, _ = W.QFileDialog.getSaveFileName(
        self, 'Convert folder to HDF5 project', str(folder.parent / (folder.name + '.rogi.h5')),
        'Rogi HDF5 project (*.h5 *.hdf5)')
    if not destination:
        return
    if not Path(destination).suffix:
        destination += '.h5'
    if not self.confirm_discard():
        return
    count = self.run_operation("Converting folder",
        lambda check, commit: convert_project_folder(folder, destination,
            cancel_check=check, before_save=commit),
        cancellable=True, cooperative=True)
    self.open_project(destination, confirm=False)
    remember_files_folder(self, str(folder))
    self.files_panel.set_folder(str(folder))
    self.statusBar().showMessage(f"Created and opened {count} dataset(s) in {destination}", 8000)


def files_folders(self):
    try:
        folders = json.loads(self.preferences.value('files_folders', '{}', type=str))
    except ValueError:
        return {}
    return folders if isinstance(folders, dict) else {}


def remember_files_folder(self, folder):
    """The Files panel reopens the last data folder used with each project."""
    if not folder:
        return
    self.preferences.setValue('files_folder', folder)
    if self.path:
        folders = files_folders(self)
        folders[str(Path(self.path).resolve())] = folder
        self.preferences.setValue('files_folders', json.dumps(folders))


def restore_files_folder(self):
    folder = (files_folders(self).get(str(Path(self.path).resolve())) if self.path else None) \
        or self.preferences.value('files_folder', '', type=str)
    if folder and Path(folder).is_dir():
        self.files_panel.set_folder(folder)


def drag_enter(self, event):
    if any(url.isLocalFile() for url in event.mimeData().urls()):
        event.acceptProposedAction()


def drop(self, event):
    paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
    if not paths:
        return
    event.acceptProposedAction()
    # Dropped files load with the Files panel options, as its Load button does.
    data = [p for p in paths if not Path(p).is_dir() and not is_project(p)]
    if data and len(data) == len(paths):
        self.guard(lambda: self.import_paths(data, **self.files_panel.options()))
    else:
        self.guard(lambda: self.open_files(paths))


def refresh_saved_views_menu(self):
    menu = self.saved_views_menu
    menu.clear()
    menu.addAction("Save current view…", lambda: self.guard(self.prompt_save_view))
    for name in self.saved_views:
        entry = menu.addMenu(name)
        entry.addAction("Restore", lambda checked=False, n=name: self.guard(lambda: self.restore_view(n)))
        entry.addAction("Rename…", lambda checked=False, n=name: self.guard(lambda: self.prompt_rename_view(n)))
        entry.addAction("Delete", lambda checked=False, n=name: self.delete_view(n))


def prompt_save_view(self):
    name, ok = W.QInputDialog.getText(self, "Save view", "View name:")
    if ok:
        self.create_view(name)


def prompt_rename_view(self, name):
    new_name, ok = W.QInputDialog.getText(self, "Rename view", "View name:", text=name)
    if ok:
        self.rename_view(name, new_name)


def view_name(self, name, previous=None):
    name = name.strip()
    if not name:
        raise ValueError("Enter a view name.")
    if name in self.saved_views and name != previous:
        raise ValueError("A view with that name already exists.")
    return name


def create_view(self, name):
    from .views import validate_saved_views
    name = self.view_name(name)
    plot = self.settings()
    plot.pop('saved_views', None)
    plot.pop('pipeline_presets', None)
    snapshot = dict(plot=plot, active=self.current().id if self.current() else None,
                    mode=self.plot_tabs.currentIndex(), image=self.image_viewer.snapshot(),
                    datasets={d.id: dict(visible=d.visible, xcol=d.xcol, ycol=d.ycol)
                              for d in self.datasets})
    validate_saved_views({name: snapshot})
    self.saved_views[name] = deepcopy(snapshot)
    self.refresh_saved_views_menu()
    self.changed()


def rename_view(self, name, new_name):
    new_name = self.view_name(new_name, name)
    self.saved_views = {new_name if key == name else key: value
                        for key, value in self.saved_views.items()}
    self.refresh_saved_views_menu()
    self.changed()


def delete_view(self, name):
    del self.saved_views[name]
    self.refresh_saved_views_menu()
    self.changed()


def restore_view(self, name):
    snapshot = deepcopy(self.saved_views[name])
    if snapshot.get('kind') == 'spectrum_map':
        self.spectrum_map(snapshot['recipe'])
        return
    settings = snapshot['plot']
    for dataset in self.datasets:
        state = snapshot['datasets'].get(dataset.id)
        if state:
            dataset.visible = state['visible']
            for field in ('xcol', 'ycol'):
                if state[field] < len(dataset.columns):
                    setattr(dataset, field, state[field])
    self.search.clear()
    self.group_filter.setCurrentIndex(0)
    self.kind_filter.setCurrentIndex(0)
    self.refresh_history_view()
    active = next((d for d in self.datasets if d.id == snapshot['active']), None)
    if active is None:
        active = next((d for d in self.datasets if d.visible),
                      self.datasets[0] if self.datasets else None)
    if active:
        self.activate_dataset(active.id)
        self.select(self.browser.currentRow())
    self.loading = True
    for field in ('title', 'xlabel', 'ylabel'):
        getattr(self, field).setText(settings.get(field, ''))
    self.legend_position.setCurrentText(settings.get('legend', 'best'))
    self.cursor_enabled.setChecked(settings.get('cursor', False))
    self.show_fitting.setChecked(settings.get('show_fitting', False))
    self.loading = False
    for axis in self.view:
        self.view[axis] = dict(scale=settings.get(axis + 'scale', 'linear'),
                              auto=settings.get(axis + 'auto', True),
                              limits=settings.get(axis + 'lim'))
    self.restore_panels(settings)
    self.redraw()
    plot_windows.ensure_plot(self, snapshot['mode'])
    self.image_viewer.restore_snapshot(snapshot['image'], self.datasets, active)
    self.navigation.update()
    self.changed()
    missing = set(snapshot['datasets']) - {d.id for d in self.datasets}
    if missing:
        self.statusBar().showMessage(f"Restored view; skipped {len(missing)} missing dataset(s).", 6000)


def settings(self):
    settings = dict(title=self.title.text(), xlabel=self.xlabel.text(), ylabel=self.ylabel.text(),
                    selected_dataset_id=self.current().id if self.current() else None,
                    legend=self.legend_position.currentText(), cursor=self.cursor_enabled.isChecked(),
                    show_fitting=self.show_fitting.isChecked())
    for axis, state in self.view.items():
        settings.update({axis + 'scale': state['scale'], axis + 'auto': state['auto'],
                         axis + 'lim': state['limits']})
    settings.update(panels=deepcopy(self.panels), active_panel=self.active_panel, sync_x=self.sync_x)
    settings['saved_views'] = deepcopy(self.saved_views)
    settings['pipeline_presets'] = deepcopy(self.pipeline_presets)
    return settings


def recent_projects(self):
    paths = self.preferences.value('recent_projects', [], type=list)
    return list(dict.fromkeys(str(Path(path).resolve()) for path in paths
                              if isinstance(path, str) and Path(path).is_file()))[:10]


def refresh_recent_projects(self):
    self.recent_menu.clear()
    paths = self.recent_projects()
    self.recent_menu.setEnabled(bool(paths))
    for path in paths:
        action = self.recent_menu.addAction(path.replace('&', '&&'))
        action.triggered.connect(lambda checked=False, p=path: self.guard(lambda: self.open_project(p)))


def remember_project(self, path):
    path = str(Path(path).resolve())
    paths = [path] + [p for p in self.recent_projects() if p != path]
    self.preferences.setValue('recent_projects', paths[:10])
    self.preferences.sync()
    self.refresh_recent_projects()


def suggest_recent_project(self):
    paths = self.recent_projects()
    if not paths or self.path is not None or self.datasets:
        return
    path, ok = W.QInputDialog.getItem(self, "Recent projects",
        "Open a recent project (Cancel starts an empty workspace):", paths, 0, False)
    if ok and path:
        self.guard(lambda: self.open_project(path))


def save(self, save_project, save_as=False):
    path = self.path
    if path is None or save_as:
        default = Path(path).with_suffix('.h5') if path else Path('analysis.rogi.h5')
        name, chosen = W.QFileDialog.getSaveFileName(self, "Save project", str(default),
            "Rogi HDF5 project (*.h5 *.hdf5);;Rogi JSON project (*.json)")
        if not name:
            return False
        path = Path(name)
        if path.suffix.lower() not in ('.h5', '.hdf5', '.json'):
            path = Path(str(path) + ('.json' if 'JSON' in chosen else '.h5'))
    datasets, settings = self.datasets, self.settings()
    self.run_operation("Saving project", lambda: save_project(path, datasets, settings))
    self.path = Path(path)
    self.remember_project(path)
    remember_files_folder(self, self.files_panel.folder)
    self.external_dirty = False
    self.history.setClean()
    self.update_dirty()
    return True


def confirm_discard(self):
    if not self.dirty:
        return True
    answer = W.QMessageBox.question(self, "Unsaved project", "Save changes before continuing?",
                                   W.QMessageBox.StandardButton.Save | W.QMessageBox.StandardButton.Discard | W.QMessageBox.StandardButton.Cancel)
    if answer == W.QMessageBox.StandardButton.Save:
        return bool(self.guard(self.save))
    return answer == W.QMessageBox.StandardButton.Discard


def open_project(self, path=None, *, confirm=True):
    if confirm and not self.confirm_discard():
        return
    if path is None:
        path, _ = W.QFileDialog.getOpenFileName(self, "Open project", "", "Rogi projects (*.h5 *.hdf5 *.json)")
    if path:
        datasets, settings = self.run_operation("Opening project",
            lambda: read_project(path), cancellable=True)
        self.saved_views = deepcopy(settings.get('saved_views', {}))
        self.pipeline_presets = deepcopy(settings.get('pipeline_presets', {}))
        self.image_viewer.set_presets(self.pipeline_presets)
        self.refresh_saved_views_menu()
        self.redraw_deferred = True
        try:
            self.opening = True
            self.history.clear()
            self.stats_region = None
            self.stats_context = None
            self.stats_drag.setChecked(False)
            self.browser_panel.reset_filters()
            with C.QSignalBlocker(self.browser):
                self.browser.clear()
                self.datasets = []
            self.update_groups()
            self.selection_changed()
            self.table.setModel(None)
            self.result.clear()
            for field in ('title', 'xlabel', 'ylabel'):
                getattr(self, field).setText(settings.get(field, ''))
            self.datasets = datasets
            self.refresh_history_view()
            if datasets:
                fallback = next((i for i, d in enumerate(datasets) if d.visible), 0)
                row = next((i for i, d in enumerate(datasets)
                            if d.id == settings.get('selected_dataset_id')), fallback)
                self.activate_dataset(datasets[row].id)
            self.loading = True
            self.legend_position.setCurrentText(settings.get('legend', 'best'))
            self.cursor_enabled.setChecked(settings.get('cursor', False))
            with C.QSignalBlocker(self.show_fitting):
                self.show_fitting.setChecked(settings.get('show_fitting', False))
            self.fit_panel.setVisible(self.show_fitting.isChecked())
            self.export_fit_action.setVisible(self.show_fitting.isChecked())
            self.drag.setChecked(False)
            self.loading = False
            for axis in self.view:
                self.view[axis] = dict(scale=settings.get(axis + 'scale', 'linear'),
                                      auto=settings.get(axis + 'auto', axis + 'lim' not in settings),
                                      limits=settings.get(axis + 'lim'))
            self.restore_panels(settings)
        finally:
            self.redraw_deferred = False
        self.redraw()
        self.navigation.update()
        self.path = Path(path)
        self.remember_project(path)
        self.opening = False
        self.external_dirty = False
        self.history.setClean()
        self.update_dirty()
        update_analysis_actions(self)
        restore_files_folder(self)
        self.canvas.draw_idle()


def export_data(self):
    if not self.current():
        raise ValueError("Select a dataset first.")
    path, _ = W.QFileDialog.getSaveFileName(self, "Export selected dataset", "data.csv", "CSV (*.csv)")
    if path:
        write_data(self.current(), path)


def export_fit(self):
    if not self.current() or not self.current().fit:
        raise ValueError("Fit a dataset first.")
    path, _ = W.QFileDialog.getSaveFileName(self, "Export parameters and residuals", "fit.csv", "CSV (*.csv)")
    if path:
        write_fit(self.current(), path)


def export_plot(self):
    plot_windows.ensure_plot(self)
    figure = self.image_viewer.figure if self.plot_tabs.currentIndex() == 1 else self.figure
    export_figure(dialog_parent(self), figure)


def closeEvent(self, event):
    if self.worker and self.worker.isRunning():
        self.statusBar().showMessage("Wait for the current operation to finish before closing.")
        event.ignore()
    elif self.confirm_discard():
        self.save_plot_window()
        # A child window outlives a hidden parent; without this the application keeps running.
        self.plot_window.hide()
        event.accept()
    else:
        event.ignore()




def read_project(path):
    datasets, settings = load_project(path)
    datasets, selected_id = consolidate_legacy(datasets, settings.get('selected_dataset_id'))
    settings['selected_dataset_id'] = selected_id
    return datasets, settings
