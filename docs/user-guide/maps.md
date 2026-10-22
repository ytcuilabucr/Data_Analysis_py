# Spectrum maps

[User guide](index.md) · [Validation and limitations](../limitations.md)

Select spectra in the dataset browser and choose **2D spectrum map…**. Choose an
X channel, signal channel, and an explicit numeric metadata sweep field (for
example temperature or magnetic field). Rogi never infers sweep coordinates from
file order or filenames. Additional metadata selectors fix other sweep dimensions;
a combination without measurements is reported instead of synthesized.

Channel and sweep units must be known and identical across the selected slice.
There is no automatic unit conversion; `1` denotes dimensionless quantities.
Repeated sweep values are rejected: select another dimension or distinct spectra.
Missing/nonfinite sweep coordinates, missing channels, and duplicate or missing
X coordinates are rejected. Missing signals can either fail validation or remain
visible as gaps, selected explicitly.

Choose an alignment even when the grids match:

- **Identical measured X grids** accepts the same coordinates in any row order.
- **Union of measured X coordinates** preserves every measured X value and leaves
  unmeasured cells empty.
- **Reference interpolation** uses the chosen spectrum's measured X coordinates
  and piecewise linear interpolation. It never extrapolates or bridges missing
  samples. The reference must belong to the selected slice.

The plot uses physical coordinate spacing, including irregular sweeps. Cross-section
selectors choose actual plotted coordinates. Named map views save source identities,
channel/metadata choices, filters, alignment, and cross-section selection in the
project's existing saved-view menu. Restoring a view rebuilds from current source
values and validates again; missing sources cause an error.

Export the map as CSV (plotted X/sweep/signal coordinates) or NPZ (plotted arrays,
units, recipe, source IDs, and each spectrum's original X and signal samples).
Cross-sections export to CSV; figures export to PNG, PDF, or SVG. Map assembly and
sorting never modify the source datasets. NPZ is the export to use when the original
measured grids must accompany an interpolated map.
