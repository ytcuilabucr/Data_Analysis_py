"""Dataset workflows coordinated by MainWindow.

Functions receive the window explicitly to preserve ordering across history,
selection and presentation. They are not panel components; extracted panels
communicate with the window through their signals and data arguments.
"""
from copy import deepcopy
from PySide6 import QtCore as C, QtWidgets as W
from .core import remove_datasets
from .history import ChangeCommand
from .grouping import partitions, path_label, path_key
from .dialogs import MetadataGroupingDialog, MetadataDialog


def annotate_selected(self, attribute, value):
    self.change_attributes(self.selected_datasets(), attribute, value, f'Edit {attribute}')


def edit_tags(self):
    selected = self.selected_datasets()
    if not selected:
        return
    value, ok = W.QInputDialog.getText(self, 'Edit tags', 'Tags, comma separated (replaces selected tags):',
                                     text=', '.join(selected[0].tags) if len(selected) == 1 else '')
    if ok:
        self.annotate_selected('tags', list(dict.fromkeys(tag.strip() for tag in value.split(',') if tag.strip())))


def edit_comments(self):
    selected = self.selected_datasets()
    if not selected:
        return
    value, ok = W.QInputDialog.getMultiLineText(self, 'Edit comments', 'Comments (replaces selected comments):',
                                              selected[0].comments if len(selected) == 1 else '')
    if ok:
        self.annotate_selected('comments', value)


def rename_dataset(self):
    selected = self.selected_datasets()
    if len(selected) != 1:
        return
    d = selected[0]
    name, ok = W.QInputDialog.getText(self, "Rename dataset", "Display name:", text=d.name)
    if not ok:
        return
    name = name.strip()
    if not name:
        raise ValueError("Dataset name cannot be blank.")
    if name != d.name:
        self.change_attributes([d], 'name', name, f'Rename {d.name} to {name}')


def assign_group(self):
    if not self.selected_datasets():
        return
    groups = sorted({d.group for d in self.datasets if d.group}, key=str.casefold)
    group, ok = W.QInputDialog.getItem(self, "Assign group", "Group (blank = ungrouped):",
                                      groups, 0, True)
    if ok:
        self.set_selected_group(group.strip())


def group_by_metadata(self):
    selected = self.selected_datasets()
    dialog = MetadataGroupingDialog(selected, self, all_datasets=self.datasets)
    if dialog.exec() == W.QDialog.DialogCode.Accepted:
        self.group_by_levels(dialog.datasets, dialog.levels, dialog.mode.currentIndex() == 1)


def group_by_levels(self, datasets, levels, append=False):
    if not levels or not datasets:
        return
    pairs = partitions(datasets, levels, append)
    before = list(self.datasets)
    old = [(d, d.group, deepcopy(d.group_path)) for d, _ in pairs]
    ids = {d.id for d, _ in pairs}
    ordered = iter(d for d, _ in pairs)
    after = [next(ordered) if d.id in ids else d for d in before]
    def apply():
        for d, path in pairs:
            d.group_path = deepcopy(path)
            d.group = path_label(path)
        self.datasets[:] = after
    def revert():
        for d, label, path in old:
            d.group, d.group_path = label, deepcopy(path)
        self.datasets[:] = before
    self.history.push(ChangeCommand(self, 'Group by metadata levels', apply, revert))
    self.statusBar().showMessage(f'Grouped {len(pairs)} files into '
                                f'{len({path_key(p) for _, p in pairs})} groups.', 6000)


def group_selected_by_metadata(self, key, descending=False, datasets=None):
    self.group_by_levels(self.selected_datasets() if datasets is None else datasets,
                         [(key, descending)])


def view_metadata(self):
    d = self.current()
    if d is None:
        raise ValueError("Select a dataset to inspect its metadata.")
    dialog = MetadataDialog(d, self)
    dialog.exec()


def set_selected_group(self, group):
    selected = self.selected_datasets()
    label = f"Group {len(selected)} dataset(s) as {group}" if group else f"Ungroup {len(selected)} dataset(s)"
    self.change_attributes(selected, 'group', group, label)


def change_attributes(self, datasets, attribute, value, label):
    changes = [(d, getattr(d, attribute)) for d in datasets
               if getattr(d, attribute) != value or (attribute == 'group' and d.group_path)]
    if not changes:
        return
    old_paths = {d.id: deepcopy(d.group_path) for d, _ in changes} if attribute == 'group' else {}
    def apply():
        for d, old in changes:
            setattr(d, attribute, deepcopy(value))
            if attribute == 'group':
                d.group_path = []
    def revert():
        for d, old in changes:
            setattr(d, attribute, deepcopy(old))
            if attribute == 'group':
                d.group_path = deepcopy(old_paths[d.id])
    self.history.push(ChangeCommand(self, label, apply, revert))


def set_selected_visibility(self, visible):
    selected = self.selected_datasets()
    self.change_attributes(selected, 'visible', visible,
                           f"{'Show' if visible else 'Hide'} {len(selected)} dataset(s)")


def remove_selected(self):
    selected = self.selected_datasets()
    if not selected:
        return
    ids = {d.id for d in selected}
    remove_datasets(self.datasets, ids)  # Validate before confirmation.
    answer = W.QMessageBox.question(
        self, "Remove datasets",
        f"Remove {len(selected)} selected dataset(s) from this project?\n"
        + "\n".join(d.name for d in selected)
        + "\n\nTheir data, edits, and fits will be removed. Source files are untouched. Use Edit → Undo to restore them during this session.",
        W.QMessageBox.StandardButton.Yes | W.QMessageBox.StandardButton.Cancel,
        W.QMessageBox.StandardButton.Cancel)
    if answer != W.QMessageBox.StandardButton.Yes:
        return
    removed = [(i, d) for i, d in enumerate(self.datasets) if d.id in ids]
    def apply():
        self.datasets = remove_datasets(self.datasets, ids)
    def revert():
        for index, d in removed:
            self.datasets.insert(index, d)
        self.history_selection = ids
    self.history.push(ChangeCommand(self, f"Remove {len(removed)} dataset(s)", apply, revert))


def add_dataset(self, dataset):
    def apply():
        self.datasets.append(dataset)
        self.history_selection = {dataset.id}
        # Keep the newly added dataset as the inspection target.
        with C.QSignalBlocker(self.browser):
            self.browser.setCurrentItem(None)
    def revert():
        self.datasets = remove_datasets(self.datasets, {dataset.id})
    if self.opening:
        apply()
        self.refresh_history_view()
    else:
        label = "Create analysis dataset" if dataset.analysis else ("Import" if dataset.raw else "Create editable copy")
        self.history.push(ChangeCommand(self, f"{label} {dataset.name}", apply, revert))


def spectrum_map(self, recipe=None):
    from .maps_ui import MapDialog
    sources = self.selected_datasets()
    if recipe is not None:
        ids = recipe['ids']
        lookup = {d.id: d for d in self.datasets}
        if any(i not in lookup for i in ids):
            raise ValueError('A saved map source is missing. Reselect spectra to create a new map.')
        sources = [lookup[i] for i in ids]
    if not sources:
        raise ValueError('Select spectra in the dataset browser first.')
    dialog = MapDialog(sources, self, recipe)
    dialog.exec()


def analysis_pipeline(self):
    if self.current():
        from .analysis_ui import AnalysisDialog, MultiAnalysisDialog
        selected = self.selected_datasets()
        dialog = (MultiAnalysisDialog(selected, self) if len(selected) > 1 else
                  AnalysisDialog(self.current(), self, self.pipeline_presets, self.pipeline_presets_changed,
                                 self.image_viewer.display_settings()))
        if dialog.exec() == W.QDialog.DialogCode.Accepted:
            for result in dialog.datasets if len(selected) > 1 else [dialog.dataset]:
                self.add_dataset(result)


def add_analysis_batch(self, results):
    if not results:
        return
    def apply():
        self.datasets.extend(results)
        self.history_selection = {d.id for d in results}
    def revert():
        self.datasets = remove_datasets(self.datasets, {d.id for d in results})
    self.history.push(ChangeCommand(self, f'Apply pipeline to {len(results)} datasets', apply, revert))


def pipeline_presets_changed(self):
    self.image_viewer.set_presets(self.pipeline_presets)
    self.changed()


def preview_image_preset(self, name):
    from .image_analysis import ImagePreviewDialog
    from .presets import validate_presets
    source = self.image_viewer.current
    if source is None:
        raise ValueError('Select an image file and channel in 2D Map first.')
    if name not in self.pipeline_presets:
        raise ValueError('The selected preset is no longer available.')
    validate_presets({name: self.pipeline_presets[name]})
    dialog = ImagePreviewDialog(source, self.pipeline_presets[name], name, self,
                                palette=self.image_viewer.palette.currentText(),
                                transpose=self.image_viewer.transpose.isChecked())
    try:
        dialog.exec()
    finally:
        dialog.deleteLater()


def apply_pipeline_preset(self):
    from .analysis_ui import BatchPipelineDialog
    selected = self.selected_datasets()
    if not selected:
        raise ValueError('Select datasets in the browser first.')
    dialog = BatchPipelineDialog(selected, self.pipeline_presets, self)
    if dialog.exec() == W.QDialog.DialogCode.Accepted:
        self.add_analysis_batch(dialog.datasets)


def reopen_analysis_recipe(self):
    from .analysis_ui import AnalysisDialog
    result = self.current()
    if result is None or not result.analysis or result.analysis.get('version') != 1:
        raise ValueError('Select a result from a single-signal analysis pipeline.')
    record = result.analysis
    source = next((d for d in self.datasets if d.id == record['source']['dataset_id']), None)
    if source is None:
        raise ValueError('The source dataset is unavailable. Its recipe cannot be reopened against the source.')
    dialog = AnalysisDialog(source, self, self.pipeline_presets, self.pipeline_presets_changed,
                            self.image_viewer.display_settings())
    dialog.load_operations(record['operations'])
    for axis in ('x', 'y'):
        channel = record['input_channels'][axis]
        if channel['index'] >= len(source.columns) or source.columns[channel['index']] != channel['name']:
            raise ValueError('The original input channels are unavailable.')
        getattr(dialog, axis + 'channel').setCurrentIndex(channel['index'])
        getattr(dialog, axis + 'unit').setText(channel['unit'])
    dialog.name.setText(result.name + ' (rerun)')
    if source.revision != record['source']['revision']:
        dialog.status.setText(f"Source changed: recorded revision {record['source']['revision']}, current revision {source.revision}. Preview will use current data.")
    else:
        dialog.status.setText('Saved recipe loaded against its source. Edit or save a preset, then preview to create a new result.')
    if dialog.exec() == W.QDialog.DialogCode.Accepted:
        self.add_dataset(dialog.dataset)


def make_copy(self):
    if self.current():
        self.add_dataset(self.current().derived())


