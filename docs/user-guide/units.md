# Channel units and axis labels

Every channel stores one unit. A blank unit means unknown, and `1` means dimensionless.

## Where units come from

- **Plain tables and DAT files:** the unit is read from a trailing `(unit)` in the column header, so `Current (A)` gets `A`. Scan directions such as `(forward)` or `(Retrace)` are not treated as units.
- **Nanonis scans:** each channel's declared unit is used.
- **Bruker scans:** the unit is `raw counts`.
- **Analysis results:** units are calculated by the pipeline.
- **Older projects:** projects saved without units get them from column names when they open.

Spellings are standardized: `um` becomes `µm`, and `ohm` becomes `Ω`. Column names are never changed. Plots, analysis compatibility checks, and maps all read the stored unit.

## Labels

All plots use the label format `Name (unit)`.

- The main plot's default labels come from the visible channels.
- A custom X or Y label keeps the axis unit unless the text you type already ends in `)` or `]`.
- When curves on one axis have different units, the plot controls show a notice. Values are never converted silently.
- Analysis previews show missing units as `(unknown unit)`.

## Editing units

Select one dataset, then choose **Organize → Edit units…**. The dialog has two modes:

- **Relabel only:** fixes a missing or wrong unit. Values stay unchanged, and this works on raw data. You can undo it with **Edit → Undo**.
- **Convert values:** rescales values when only the SI prefix changes, for example nA → pA or (V)/(s) → (mV)/(ms). This creates an editable copy and renames columns that carried the old unit. Use it before combining spectra or assembling maps that need matching units.
