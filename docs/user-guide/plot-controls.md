# Plot controls and saved views

[User guide](index.md) · [Validation and limitations](../limitations.md)

## Plot window

Choose **View → Plot in separate window**, or click the float button on the **Plot** title bar, to move the line plot and 2D map into their own window, for example on a second monitor. The data table then fills the middle column. Undo, Save, Import and the other main-window shortcuts keep working while the plot window has focus, and the plot is locked like the rest of the window during imports, saves and fits. Uncheck the menu item or double-click the plot window's title bar to dock it again. Whether the plot is docked or floating, and where it floats, is remembered per computer, not in the project; a plot window saved on a monitor that is no longer connected reopens on one that is. On macOS the floating plot is a tool window: it stays above the main window and has no full-screen or minimize button. The cursor coordinates and plot hints still appear in the main window's status bar.

## Plot controls

Enable **View → Show plot controls** for advanced presentation options; the default interface stays compact.

- Choose linear or base-10 logarithmic X/Y scales. Leave **Automatic limits** checked to fit visible data, or uncheck it and enter finite minimum/maximum values. Click **Apply axes** to commit both axes together. Log limits must be positive, and minimum must be below maximum. Invalid input leaves the current plot unchanged.
- Zooming or panning with the toolbar switches the affected axes to manual mode. Manual limits survive selection, renaming, colors, labels, overlays, and fitting-panel changes. To fit the data again, enable automatic limits and apply. Applying axes also resets the residual Y view to automatic. Home/Back/Forward retain the toolbar's normal navigation history; applying axes or opening a project resets that history.
- Dataset color and marker controls affect the current highlighted dataset. Automatic markers mean no marker for lines and circles for scatter; None suppresses markers. **Reset color** restores the automatic palette. Fits and residuals use the dataset color. Editable copies inherit color and marker choices.
- Choose a legend position or **hidden**. **Coordinate cursor** displays crosshairs and X/Y coordinates in the status bar, including actual data coordinates on logarithmic axes. It does not snap to samples; residual-panel coordinates are labeled Residual.
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
panels and the hovered position's coordinates in the status bar. Fitting and its
residual panel follow the active panel; the existing per-dataset fit storage is
unchanged.

Named views and project saves preserve channel assignments, panel axes, the
active panel, and X synchronization. PNG and SVG figure export include the full
visible layout, including the active residual panel when fitting is shown.
