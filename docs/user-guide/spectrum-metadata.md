# Spectrum metadata and timestamps

[User guide](index.md) · [Validation and limitations](../limitations.md)

Spectrum DAT import preserves the complete decoded UTF-8 source text, including original line endings and any BOM, and populates two optional dataset fields:

- **instrument_metadata** stores ordered sections and entries, occurrence numbers, original values, parsed numeric/text values, explicitly written units, and source line numbers. Empty sections and repeated sections/keys remain separate; unknown header lines are retained. Empty values remain missing. A value such as `100 ms` exposes `100` and `ms`; bare numeric OscFreq values have **no assigned unit**.
- **timestamps** stores each original Time / Time_Timestamp column independently, including its original column number, row-aligned original strings, parsed values, and unrecognized row numbers. Observed text dates use `YYYY/MM/DD_HH:MM:SS` and parse to timezone-free ISO text. Numeric timestamps remain numbers; no epoch, unit, or timezone is inferred. Missing timestamps stay missing; unrecognized dates retain their original text and a diagnostic.

These rules come from the 48 supplied files, including repeated Lockin1/K2401_source blocks. Filename fragments are not interpreted as metadata or units. See [the schema notes](../spectrum-metadata.md).

Select a dataset and choose **Organize → View metadata…** to inspect instrument fields, per-row timestamps, and source text. Metadata and timestamps remain available even when their numeric channels were omitted during import.

Browser search matches metadata names, original and parsed values, and original/ISO timestamps. Try `SR830`, `2026-08-14`, or `TimeConstant[1]=100 ms`.

**Organize → Group by metadata or title…** supports nested groups:

- Choose **Selected files** or **All project files**, with file counts shown for each scope.
- **Add subgroup within existing groups** is the default: grouping `spm` files by scan size keeps `spm` as the parent and adds scan-size children. Choose **Replace grouping** explicitly only to discard the existing hierarchy.
- Besides instrument metadata, fields prefixed **Title:** are read from each file's title. A title is split at `,` or `;`; a `key = value` segment gives field `key` (for example `YSL AOTF - 1.power = 10` gives `Title: YSL AOTF - 1.power` = `10`). Other segments are split at `_` and spaces: `laserpower100` gives `Title: laserpower` = `100` and `4MHz` gives `Title: MHz` = `4 MHz`. Repeated keys are numbered (`[2]`), and other words are ignored. Title fields are used for grouping and for `field = value` searches; maps and import suggestions still use instrument metadata alone. Renaming a file changes its title fields but not groups already assigned.
- Choose the first metadata field, then **Add subgroup level** for each additional subdivision. Each level offers fields with at least two distinct nonblank values within at least one parent group. Remove a level to simplify the hierarchy.
- Set ascending or descending order independently at each level. Numeric values sort numerically, text alphabetically; units are not converted. Original trimmed values remain distinct.
- Inspect the expandable preview: each parent and subgroup shows its file count. The summary counts final groups and files. Missing values form explicit **Missing value** subgroups, sorted last in either direction.
- Apply to assign groups and order the scoped files in their existing browser slots. Files outside the scope stay unchanged. Grouping and ordering are one undoable action.

The collapsible **Groups** navigator above the file list filters by parent or subgroup; a parent includes all its descendants. **All groups** restores the full list. Group paths store each field and value separately, so slashes in labels do not create unintended subgroups. Group labels show only the effective metadata name and value (for example, `Scan Size = 10000 nm`). Fields with colliding short names receive distinct numbered suffixes across the grouping; hover to see the original field. Full field identities remain stored and control filtering, so simplifying names never merges distinct fields. JSON and HDF5 preserve paths, editable copies inherit independent paths, and older group labels remain a single parent level. Manual **Assign group** replaces a hierarchy with a plain label; **Ungroup selected** clears it. Both can be undone.

Repeated sections/keys have distinct occurrence numbers, such as `Lockin1[1].TimeConstant[1]`. First/last timestamps and a date from the first source row, when parseable, are also offered. Dataset IDs and lineage are preserved.

JSON and HDF5 retain this structure. Older projects remain readable with empty metadata; reopening does not silently reparse embedded source. Reimport the original DAT to populate structured fields. Editable copies inherit independent acquisition snapshots and the originating dataset ID: editing a numeric timestamp channel does not rewrite original timestamps or metadata.
