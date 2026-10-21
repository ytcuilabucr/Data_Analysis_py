# Spectrum metadata schema (version 1)

Inspected all 48 files in `example-data/Spectrum`. Before `[Data]`, files contain
named sections and `Key: value` lines: 48 Time and Rotator sections, 76 Lockin1,
39 K2400, 62 K2401_source, and 24 K2401_preamp sections. Repeated section names
are not collapsed; empty sections are retained.

Observed Lockin1 fields include Aux1–Aux4, Harmonics, Input, InputCoupling,
InputGrounding, Model, OscAmp, OscFreq, RefPhase, RefSource, Sensitivity,
TimeConstant and VarList. K2400/K2401_source fields include Compliance, Enable,
Mode, SenseRange, SourceRange, VarList and Voltage.

`Dataset.instrument_metadata` is empty for unstructured/legacy data; otherwise:

```text
format: "spectrum"
version: 1
source_dataset_id: original importing dataset ID
sections: [
  name, occurrence (1-based per name), source_line (1-based),
  entries: [
    key, raw_value (exact text after the first colon),
    value (finite number, text, or null for empty),
    unit (explicit suffix after a numeric value, or null), source_line
  ]
]
unparsed: [source_line, text]
```

Numeric suffixes are split only on whitespace after a complete number: examples
include `100 mV/nA` and `300 ms`. No unit is assigned to bare numeric values.
Enable remains a number, not an inferred boolean. Unknown/nonfinite metadata
tokens remain text. Absent values, empty values and empty sections generate no
defaults. Both section order and duplicate key order are preserved.

`Dataset.timestamps` contains one stream for each original Time/Time_Timestamp
column:

```text
name, source_column (1-based original column)
kind: "datetime" or "numeric"
raw: one original string per source data row
values: one parsed ISO datetime string / finite number / null per row
invalid_rows: 1-based rows with unrecognized nonmissing tokens
```

The observed text format is `%Y/%m/%d_%H:%M:%S`. ISO output has no timezone.
Time_Timestamp contains scientific-notation numbers with no declared epoch or
unit; these are never converted into dates or used to fill missing text dates.
Repeated/coarsely rounded values are retained, not interpolated. Row numbers
exclude the header; array order follows the source. Streams are independent of
the selected numeric import columns.

JSON and HDF5 store these optional fields without changing project version 1.
The loader validates section structure, scalar types, timestamp types and row
alignment. Older files default to `{}` and `[]`; source text is not reparsed.
New files may require this Rogi version when opened by older software.

Derived datasets independently copy these structures and retain the original
source_dataset_id. They describe acquisition, not edited channel values. Raw
datasets retain full source text; derived datasets retain parent links. Search
includes all timestamp rows. Grouping uses exact original field values (trimmed)
and occurrence numbers. Missing fields are skipped without assigning a value.

The reader retains UTF-8 decoded source text including CRLF and BOM. It does not
claim support for arbitrary encodings, timezone interpretation, alternative
date formats, or filename-derived metadata.
