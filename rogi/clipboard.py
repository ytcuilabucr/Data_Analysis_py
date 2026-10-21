"""Plain-text table interchange. Validation never mutates a dataset."""
import csv
import io
import numpy as np

MIME = 'application/x-rogi-table-with-headers'


def selection_rectangle(indexes):
    cells = {(index.row(), index.column()) for index in indexes}
    if not cells:
        raise ValueError("Select table cells first.")
    rows, columns = zip(*cells)
    top, left, bottom, right = min(rows), min(columns), max(rows), max(columns)
    if len(cells) != (bottom - top + 1) * (right - left + 1):
        raise ValueError("Select one complete rectangular block of table cells.")
    return top, left, bottom, right


def copy_table(dataset, rectangle):
    top, left, bottom, right = rectangle
    stream = io.StringIO()
    writer = csv.writer(stream, delimiter='\t', lineterminator='\n')
    writer.writerow(dataset.columns[left:right + 1])
    for row in dataset.values[top:bottom + 1, left:right + 1]:
        writer.writerow(['' if np.isnan(value) else str(float(value)) for value in row])
    return stream.getvalue()


def parse_paste(dataset, text, top, left, copied_headers=False):
    if dataset.raw:
        raise ValueError("Raw data is read-only. Create an editable copy before pasting.")
    if not text:
        raise ValueError("The clipboard contains no table data.")
    try:
        rows = list(csv.reader(io.StringIO(text), delimiter='\t' if copied_headers or '\t' in text else ',', strict=True))
    except csv.Error as error:
        raise ValueError(f"Invalid clipboard table: {error}") from error
    rows = [row if row else [''] for row in rows]
    if not rows:
        raise ValueError("The clipboard contains no table data.")
    width = len(rows[0])
    # Never guess that a valid numeric/missing row is a header, even if the
    # destination happens to have numeric-looking column names.
    header_has_text = False
    for token in rows[0]:
        if token.strip().lower() in ('', 'na', 'nan', 'n/a'):
            continue
        try:
            float(token)
        except ValueError:
            header_has_text = True
    matching_headers = header_has_text and rows[0] == dataset.columns[left:left + width]
    if copied_headers or matching_headers:
        rows = rows[1:]
    if not rows:
        raise ValueError("The clipboard has headers but no data rows.")
    for number, row in enumerate(rows, start=1):
        if len(row) != width:
            raise ValueError(f"Paste row {number}: expected {width} columns, found {len(row)}.")
    if (top < 0 or left < 0 or top + len(rows) > len(dataset.values)
            or left + width > len(dataset.columns)):
        raise ValueError(f"Paste is {len(rows)} × {width} cells at row {top + 1}, column {left + 1}; "
                         f"it does not fit the {len(dataset.values)} × {len(dataset.columns)} dataset. "
                         "No rows or columns are added.")
    values = np.empty((len(rows), width), dtype=float)
    errors = []
    for r, row in enumerate(rows):
        for c, token in enumerate(row):
            try:
                value = np.nan if token.strip().lower() in ('', 'na', 'nan', 'n/a') else float(token)
                if np.isinf(value):
                    raise ValueError()
                values[r, c] = value
            except ValueError:
                errors.append(f"Paste row {r + 1}, column {c + 1} → dataset row {top + r + 1}, "
                              f"column {left + c + 1} ({dataset.columns[left + c]}): {token!r}")
    if errors:
        raise ValueError(f"Paste rejected: {len(errors)} invalid cell(s). Use finite numbers or blank/NA/NaN/N/A.\n"
                         + '\n'.join(errors[:10])
                         + (f"\n… and {len(errors) - 10} more." if len(errors) > 10 else ''))
    return values
