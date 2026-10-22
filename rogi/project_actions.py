"""Window-level project commands and persistence coordination.

Each command receives the MainWindow explicitly. Panels do not depend on this
module: the coordinator owns sequencing across panels, history and file actions.
"""
from copy import deepcopy
from pathlib import Path
from PySide6 import QtCore as C, QtWidgets as W, QtGui as G
from .core import export_data as write_data, export_fit as write_fit
from .project import load_project, convert_folder as convert_project_folder
from .scanfile import consolidate_legacy
from .grouping import path_label


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
    toolbar = self.addToolBar("Project")
    self.project_actions = {}
    standard_keys = {"Open project…": G.QKeySequence.StandardKey.Open,
                     "Save": G.QKeySequence.StandardKey.Save,
                     "Save as…": G.QKeySequence.StandardKey.SaveAs}
    for label, function in [("Import…", self.import_file), ("Convert folder…", self.convert_folder),
                            ("Open project…", self.open_project),
                            ("Save", self.save), ("Save as…", lambda: self.save(True)),
                            ("Editable copy", self.make_copy), ("Analysis pipeline…", self.analysis_pipeline),
                            ("Apply pipeline preset…", self.apply_pipeline_preset),
                            ("Reopen analysis recipe…", self.reopen_analysis_recipe),
                            ("2D spectrum map…", self.spectrum_map),
                            ("Export data…", self.export_data),
                            ("Export fit…", self.export_fit), ("Export plot…", self.export_plot)]:
        action = toolbar.addAction(label)
        self.project_actions[label] = action
        if label in standard_keys:
            action.setShortcuts(G.QKeySequence.keyBindings(standard_keys[label]))
        elif label == "Import…":
            action.setShortcut(G.QKeySequence("Ctrl+I"))
        if label in standard_keys or label == "Import…":
            self.file_menu.addAction(action)
        action.triggered.connect(lambda checked=False, fn=function: self.guard(fn))
        if label == "Export fit…":
            self.export_fit_action = action
            action.setVisible(False)
    self.recent_menu = self.file_menu.addMenu("Recent projects")
    self.refresh_recent_projects()


def update_dirty(self, *args):
    self.dirty = self.external_dirty or not self.history.isClean()
    self.setWindowTitle(f"Rogi — {self.path.name if self.path else 'Untitled'}" + (" *" if self.dirty else ""))


def changed(self):
    if not self.replaying and not self.opening:
        self.external_dirty = True
        self.update_dirty()


def import_file(self):
    from .dialogs import ImportDialog, SpmImportDialog, ImportGroupDialog
    path, _ = W.QFileDialog.getOpenFileName(self, "Import numeric data", "", "Supported data (*.csv *.tsv *.txt *.dat *.spm *.sxm);;SPM scans and curves (*.spm *.sxm);;Text data (*.csv *.tsv *.txt *.dat);;All files (*)")
    if path:
        if Path(path).suffix.lower() in ('.spm', '.sxm'):
            dialog = SpmImportDialog(path, self)
            if not dialog.exec():
                return
            imported = dialog.datasets
        else:
            dialog = ImportDialog(path, self)
            if not dialog.exec():
                return
            imported = [dialog.dataset]
        if self.datasets or self.path:
            destination = ImportGroupDialog(imported[0], self.datasets, self.path, self)
            if not destination.exec():
                return
            for dataset in imported:
                dataset.group_path = destination.selected_path()
                dataset.group = path_label(dataset.group_path)
        # Reveal the newly imported file even if the browser was filtered.
        self.search.clear()
        for field in (self.tag_filter, self.metadata_filter, self.date_from, self.date_to):
            field.clear()
        self.favorites_filter.setChecked(False)
        self.group_filter.setCurrentIndex(0)
        for index, dataset in enumerate(imported):
            dataset.visible = index == 0
            self.add_dataset(dataset)
        self.statusBar().showMessage('File added. Use Save to store it in the project.', 6000)


def convert_folder(self):
    folder = W.QFileDialog.getExistingDirectory(self, 'Select folder of CSV, TSV, TXT, DAT, SPM, or SXM files')
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
    self.statusBar().showMessage(f"Created and opened {count} dataset(s) in {destination}", 8000)


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
    self.plot_tabs.setCurrentIndex(snapshot['mode'])
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
            self.search.clear()
            for field in (self.tag_filter, self.metadata_filter, self.date_from, self.date_to):
                field.clear()
            self.favorites_filter.setChecked(False)
            self.group_filter.setCurrentIndex(0)
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
    path, chosen = W.QFileDialog.getSaveFileName(self, "Export plot", "plot.png", "PNG (*.png);;SVG (*.svg)")
    if path:
        if not Path(path).suffix:
            path += '.svg' if chosen.startswith('SVG') else '.png'
        if Path(path).suffix.lower() not in ('.png', '.svg'):
            raise ValueError("Choose a .png or .svg filename.")
        figure = self.image_viewer.figure if self.plot_tabs.currentIndex() == 1 else self.figure
        figure.savefig(path, dpi=180)


def closeEvent(self, event):
    if self.worker and self.worker.isRunning():
        self.statusBar().showMessage("Wait for the current operation to finish before closing.")
        event.ignore()
    elif self.confirm_discard():
        self.save_plot_layout()
        event.accept()
    else:
        event.ignore()




def read_project(path):
    datasets, settings = load_project(path)
    datasets, selected_id = consolidate_legacy(datasets, settings.get('selected_dataset_id'))
    settings['selected_dataset_id'] = selected_id
    return datasets, settings
