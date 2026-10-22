# Plot controls and saved views

[User guide](index.md) · [Validation and limitations](../limitations.md)

## Plot window

Rogi starts with a compact file window: the dataset list, with **Open plot window** and **Show data table** buttons above it. **Show data table** widens the window to show the selected dataset's values beside the list; **Hide data table** shrinks it again. The choice is remembered on this computer. Plots open in a separate **plot window** holding the **Line plot** (with the plot controls beside it) and the **2D Map** tabs, for example on a second monitor.

- Click the blue **Open plot window** button at the top of the file window (it reads **Bring plot window to front** while the window is open), or use **Plot window** on the toolbar, **View → Plot window**, or Ctrl+Shift+P (⌘⇧P on macOS). Double-clicking a dataset in the list also opens it. Closing the plot window only hides it; closing the file window ends Rogi.
- Commands that act on the plot open it: **Show fitting**, **Show statistics**, **Show plot controls**, **Export plot…** and restoring a saved view. Opening a project does not.
- While the plot window is closed, plots are not redrawn; selecting datasets is faster on large scans. The plot is drawn when the window opens.
- The plot window is a normal window: it can go full screen, be minimized, and stays visible when another application is active. Its title names the view, the active dataset, and the panel when there are several.
- Undo, Save, Open, Import and the other file-window shortcuts also work while the plot window is active, and on macOS the menu bar stays available. The plot window is locked like the file window during imports, saves and fits. Error messages, the color picker, progress and export dialogs open over the window you are working in.
- Plot hints and the coordinate cursor readout appear in the plot window's status bar.
- **Copy** on a plot's toolbar puts that plot on the clipboard as an image; **Export…** saves it as PNG or SVG.
- Whether the plot window was open, and where, is remembered per computer, not in the project. On the very first start it stays closed. A window saved on a monitor that is no longer connected reopens on one that is.

## Plot controls

**Curves — active panel**, at the top of the plot controls, lists the curves in the active panel. To compare another dataset without going back to the dataset list, choose it under the list and click **Add curve**: it is shown in the active panel and becomes the active dataset, so its X/Y channels can be changed right away. **Remove selected curve** hides that curve; in a panel with its own channel list it only leaves that panel. Both can be undone. Adding a hidden dataset to one panel does not make it appear in the other panels. Checking datasets in the dataset list still works as before.

Enable **View → Show plot controls** for advanced presentation options; the default interface stays compact.

- Choose linear or base-10 logarithmic X/Y scales. Leave **Automatic limits** checked to fit visible data, or uncheck it and enter finite minimum/maximum values. Click **Apply axes** to commit both axes together. Log limits must be positive, and minimum must be below maximum. Invalid input leaves the current plot unchanged.
- Zooming or panning with the toolbar switches the affected axes to manual mode. Manual limits survive selection, renaming, colors, labels, overlays, and fitting-panel changes. To fit the data again, enable automatic limits and apply. Applying axes also resets the residual Y view to automatic. Home/Back/Forward retain the toolbar's normal navigation history; applying axes or opening a project resets that history.
- Dataset color and marker controls affect the current highlighted dataset. Automatic markers mean no marker for lines and circles for scatter; None suppresses markers. **Reset color** restores the automatic palette. Fits and residuals use the dataset color. Editable copies inherit color and marker choices.
- Choose a legend position or **hidden**. **Coordinate cursor** displays crosshairs and X/Y coordinates in the line plot's status line, including actual data coordinates on logarithmic axes. It does not snap to samples; residual-panel coordinates are labeled Residual.
- Log axes cannot display zero or negative coordinates. Rogi masks affected display rows, leaving line gaps, and reports counts for data and fit points. Missing values also remain gaps. Stored arrays, source text, fits, exports, and fitting calculations are unchanged. Empty logarithmic views use a positive fallback range. Residual Y is always linear.

JSON and HDF5 projects retain scales, automatic/manual modes, limits (including residual Y zoom), colors, markers, legend position, cursor toggle, and fitting visibility. View changes trigger unsaved-change prompts; moving the cursor does not. Older projects default to linear scales and automatic styles; saved legacy limits restore as manual views. Pending axis entries are not saved until applied. Opening the controls panel itself is temporary.

## Named saved views

Use **View → Saved views → Save current view…** to name the current presentation.
Each named view has **Restore**, **Rename…**, and **Delete** actions in that menu.
Names must be nonempty and unique. Save the project after changing saved views.

Views preserve dataset visibility, the active dataset, each dataset's X/Y channels,
the Line plot / 2D Map tab, plot title and axis labels, axis scales and automatic or
manual limits (including line-plot zoom), legend and cursor settings, and fitting
panel visibility. Image settings include the palette, contrast mode and limits,
per-file map channel choices, comparison channel, and each displayed map's zoom.
Restoring a view changes presentation only; it does not copy or revert data or fits.

Views are stored in the optional `settings.saved_views` field in both HDF5 and JSON
projects. Older projects without that field open with no saved views. Restoration
uses stable dataset IDs, so renamed or reordered datasets still match. Missing
datasets are skipped with a status message; if the active dataset is missing,
Rogi selects an available visible dataset, or the first remaining dataset. A missing
comparison becomes “None.” Datasets added after a view was saved retain their
current visibility and channels; unavailable channel indices retain their current
selection. Restoration clears browser filters to reveal the active dataset.

## Multiple line-plot panels

Use **Add panel with selected channels** in the axis-channel controls to create
another panel, then choose its X and Y channels. The **Active panel** selector
chooses which panel the channel controls, axis limits, statistics selection, and
fitting tools operate on. Each panel can overlay datasets: select a dataset and
use **Assign selected channels to active panel**. Use the corresponding remove
button to remove that dataset's assignment without deleting its data. Changing
channels updates only its assignment in the active panel. Existing single-panel
projects continue to overlay visible datasets as before.

Y scales, limits, and custom labels are independent for each panel. Enable
**Synchronize X limits** to use the active panel's X range and scale throughout
the layout; subsequent X zooms propagate across panels. Disable it to zoom each
panel independently. **Coordinate cursor** shows a common X guide across visible
panels and the hovered position's coordinates in the line plot's status line. Fitting and its
residual panel follow the active panel; the existing per-dataset fit storage is
unchanged.

Named views and project saves preserve channel assignments, panel axes, the
active panel, and X synchronization. PNG and SVG figure export include the full
visible layout, including the active residual panel when fitting is shown.
