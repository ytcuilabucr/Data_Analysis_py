# Image cross-section profiles

[User guide](index.md) · [Validation and limitations](../limitations.md)

The **2D Map** tab shows two crosshair cursors marked by a cyan square and an
orange circle. Drag either marker with the left mouse button to move both X and
Y simultaneously, or drag a crosshair line to move one axis. Toolbar pan/zoom
must be off. The horizontal cut sits below the image and the vertical cut sits
to its right, with spatial axes aligned and linked to image zoom. Both cursor
profiles appear in matching colors. Profiles
snap to pixel centers and retain missing signal values as gaps. Coordinates use
scan dimensions and units when available, otherwise zero-based pixel indices.
The comparison map remains available alongside the selected map.

Choose **Cursor 1** or **Cursor 2** and **X profile** or **Y profile**, then **Export profile CSV…** to save the
coordinate and signal columns (missing values are blank), or **Create profile
dataset** to add an editable derived dataset. The derived dataset records its
parent, source channel, source revision, original extraction axis, pixel index,
and coordinate position with units in its instrument metadata. Creation supports
undo/redo, and provenance is retained in saved projects.

**Transpose display** swaps the displayed image axes and labels without changing
source values or calibration. X and Y profile names and extraction positions
always refer to the original data axes. View snapshots retain transpose and
cursor positions.

Enable **Select rectangle between cursors** to highlight all pixels between the
cursor positions, including both boundary pixels. The selection shows pixel and
missing-value counts and the mean of finite values. **Create region dataset**
creates an editable coordinate table for further analysis, preserving original
X/Y coordinates, signal values, missing pixels, source channel/revision, and
inclusive region bounds. Region creation supports undo/redo and project saving.
Transpose swaps the displayed horizontal/vertical cuts while preserving original
X/Y meaning for exports. View snapshots retain both cursors and region selection.
