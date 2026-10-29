# Formula columns

**Analysis → New column from formula…** computes a new column from the highlighted dataset's existing columns.

## Where the column goes

- **Raw data** stays read-only: Rogi creates an editable copy named `<dataset> (+ <column>)` with the new column at the end.
- **Editable data** gets the column added at the end, in place. Existing cells, the revision number and any fit are unchanged.

Either way it is one step in **Edit → Undo**. The column holds computed numbers: it does not recalculate if you later edit the cells it was computed from. Each dataset keeps a record of its formula columns (name, formula, unit and the revision they were computed from), which is saved in JSON and HDF5 projects and carried into editable copies.

## Writing formulas

| You write | Meaning |
| --- | --- |
| `[Current (A)]` | A column by its full name. Double-click a column in the dialog to insert it. |
| `c1`, `c2`, … | A column by position. |
| `Time` | A column by bare name, when the name has no spaces or symbols. |
| `+ - * /`, `^` or `**`, `%` | Arithmetic, powers, remainder. |
| `1.5e-3`, `pi`, `e` | Numbers and constants. |
| `row` | The row number, starting at 1. |

Row-by-row functions: `sqrt`, `exp`, `log` (or `ln`), `log10`, `log2`, `abs`, `sign`, `floor`, `ceil`, `round`, `sin`, `cos`, `tan`, `asin`, `acos`, `atan`, `atan2(y, x)`, `sinh`, `cosh`, `tanh`, `hypot(a, b)`.

Whole-column values, ignoring missing cells: `mean`, `median`, `std` (sample), `sum`, and `min`/`max` with one argument. With two arguments `min(a, b)` and `max(a, b)` compare row by row.

Examples:

- `[Current (A)] * [Bias (V)]`: power, with the name `Power (W)`.
- `c2 / max(c2)`: normalize to the peak.
- `c2 - mean(c2)`: subtract the mean.
- `[Current (A)] * 1e9`: amps to nanoamps (or use [Edit units…](units.md) for prefix-only changes).

Comparisons, conditions, attribute access and any other Python are refused. Rogi reads the formula itself and never runs it as code.

## Missing values and units

A row with a missing input gives a missing result. Results that are not finite numbers (division by zero, overflow, `log` of a negative number) are also stored as missing. The dialog previews the first rows and counts both kinds before you accept.

The unit field is optional. Left blank, the unit comes from a trailing `(unit)` in the column name, as for imported files; otherwise it is unknown. Rogi does not derive units from the formula.
