"""Reproducible storage trial; run with .venv/bin/python scripts/hdf5_trial.py.

Requires numpy and h5py. Original instrument files are never modified.
This is a standalone experiment, not the Rogi project-file implementation.
"""
from pathlib import Path
import json
import platform
import statistics
import time

import h5py
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "example-data"
OUT = ROOT / "artifacts/hdf5-trial"


def parse(path):
    # Keep duplicate labels and trailing spaces: column position is identity.
    with path.open(encoding="utf-8-sig", newline="") as stream:
        header = []
        for line in stream:
            if line.strip() == "[Data]":
                break
            header.append(line)
        else:
            raise ValueError(f"Missing [Data]: {path}")
        columns = stream.readline().rstrip("\r\n").split("\t")
        while columns and columns[-1] == "":
            columns.pop()
        if columns[0] != "Time":
            raise ValueError(f"Unexpected first column: {path}")
        rows, times = [], []
        for line in stream:
            if not line.strip():
                continue
            fields = line.rstrip("\r\n").split("\t")
            while len(fields) > len(columns) and fields[-1] == "":
                fields.pop()
            if len(fields) != len(columns):
                raise ValueError(f"Wrong field count: {path}")
            times.append(fields[0])
            rows.append([float(v) for v in fields[1:]])
    values = np.asarray(rows, dtype="f8")
    if not np.isfinite(values).all():
        raise ValueError(f"Nonfinite input: {path}")
    return dict(source=path.relative_to(SOURCE).as_posix(),
                header="".join(header), columns=columns,
                timestamps=times, values=values)


def timed(function, repeats=7):
    function()  # Warm cache; these are not cold-disk benchmarks.
    elapsed = []
    for _ in range(repeats):
        start = time.perf_counter()
        function()
        elapsed.append((time.perf_counter() - start) * 1000)
    return round(statistics.median(elapsed), 3)


def write_h5(path, records, compressed=False, archive=False):
    with h5py.File(path, "w") as file:
        file.attrs["format"] = "rogi-hdf5-trial"
        file.attrs["version"] = 1
        for i, record in enumerate(records):
            group = file.create_group(f"runs/{i:04d}")
            for key in ("source", "header"):
                group.attrs[key] = record[key]
            group.attrs["columns_json"] = json.dumps(record["columns"])
            data = record["values"]
            options = dict(chunks=(min(4096, len(data)), 1),
                           compression="gzip", compression_opts=4,
                           shuffle=True) if compressed else {}
            group.create_dataset("values", data=data, **options)
            # Fixed-length ASCII timestamps retain the original textual precision.
            encoded = [t.encode("ascii") for t in record["timestamps"]]
            group.create_dataset("timestamps", data=np.asarray(encoded),
                                 **(dict(compression="gzip", compression_opts=4) if compressed else {}))
            if archive:
                raw = (SOURCE / record["source"]).read_bytes()
                group.create_dataset("source_bytes", data=np.frombuffer(raw, dtype="u1"),
                                     compression="gzip", compression_opts=4)


def validate(path, records, archive=False):
    with h5py.File(path, "r") as file:
        assert len(file["runs"]) == len(records)
        for i, record in enumerate(records):
            group = file[f"runs/{i:04d}"]
            np.testing.assert_array_equal(group["values"][:], record["values"])
            assert group["timestamps"].asstr()[:].tolist() == record["timestamps"]
            assert json.loads(group.attrs["columns_json"]) == record["columns"]
            assert group.attrs["header"] == record["header"]
            assert group.attrs["source"] == record["source"]
            if archive:
                assert group["source_bytes"][:].tobytes() == (SOURCE / record["source"]).read_bytes()


def h5_sum(path):
    total = 0.0
    with h5py.File(path, "r") as file:
        for group in file["runs"].values():
            data = group["values"]
            for start in range(0, len(data), 4096):
                total += data[start:start+4096].sum()
    return total


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    paths = sorted(SOURCE.rglob("*.dat"))
    if not paths:
        raise ValueError("No .dat files found")
    records = [parse(p) for p in paths]
    target = max(range(len(records)), key=lambda i: len(records[i]["values"]))
    record = records[target]
    selection = slice(len(record["values"]) // 2, len(record["values"]) // 2 + 100)
    expected = sum(r["values"].sum() for r in records)
    json_path = OUT / "parsed.json"
    payload = [{**r, "values": r["values"].tolist()} for r in records]
    start = time.perf_counter()
    json_path.write_text(json.dumps(payload, allow_nan=False, separators=(",", ":")))
    json_write = (time.perf_counter()-start)*1000

    def json_sum():
        return sum(np.asarray(r["values"]).sum() for r in json.loads(json_path.read_text()))

    def text_sum():
        return sum(parse(p)["values"].sum() for p in paths)

    def json_slice():
        return np.asarray(json.loads(json_path.read_text())[target]["values"])[selection, :2]

    def text_slice():
        return parse(paths[target])["values"][selection, :2]

    results = []
    for name, compressed, archive in [("uncompressed", False, False),
                                       ("gzip", True, False), ("archive", True, True)]:
        path = OUT / f"{name}.h5"
        start = time.perf_counter()
        write_h5(path, records, compressed, archive)
        write_ms = (time.perf_counter()-start)*1000
        validate(path, records, archive)

        def partial():
            with h5py.File(path, "r") as file:
                return file[f"runs/{target:04d}/values"][selection, :2]

        np.testing.assert_array_equal(partial(), record["values"][selection, :2])
        np.testing.assert_allclose(h5_sum(path), expected, rtol=1e-14)
        results.append(dict(format=name, bytes=path.stat().st_size,
                            write_ms=round(write_ms, 3),
                            batch_sum_ms=timed(lambda: h5_sum(path)),
                            slice_ms=timed(partial)))
    np.testing.assert_allclose(json_sum(), expected, rtol=1e-14)
    np.testing.assert_array_equal(json_slice(), text_slice())
    results.extend([
        dict(format="parsed JSON", bytes=json_path.stat().st_size,
             write_ms=round(json_write, 3), batch_sum_ms=timed(json_sum), slice_ms=timed(json_slice)),
        dict(format="original DAT", bytes=sum(p.stat().st_size for p in paths),
             write_ms=None, batch_sum_ms=timed(text_sum), slice_ms=timed(text_slice))])
    report = dict(files=len(paths), rows=sum(len(r["values"]) for r in records),
                  numeric_values=sum(r["values"].size for r in records),
                  raw_numeric_bytes=sum(r["values"].nbytes for r in records),
                  row_range=[min(len(r["values"]) for r in records), max(len(r["values"]) for r in records)],
                  numeric_column_counts=sorted(set(r["values"].shape[1] for r in records)),
                  duplicate_column_files=[r["source"] for r in records if len(r["columns"]) != len(set(r["columns"]))],
                  slice_source=record["source"],
                  validation="All HDF5 numeric values, timestamps, labels, headers and paths match; archive original bytes match exactly; partial reads and batch sums match.",
                  environment=dict(python=platform.python_version(), numpy=np.__version__,
                                   h5py=h5py.__version__, hdf5=h5py.version.hdf5_version,
                                   platform=platform.platform()), results=results)
    (OUT / "results.json").write_text(json.dumps(report, indent=2))
    lines = ["# HDF5 trial on example-data", "", json.dumps({k: report[k] for k in ("files", "rows", "numeric_values", "row_range", "numeric_column_counts")}, indent=2), "",
             "| Format | Bytes | Write ms | Batch sum ms | 100 rows × 2 columns ms |",
             "|---|---:|---:|---:|---:|"]
    for r in results:
        lines.append(f"| {r['format']} | {r['bytes']:,} | {r['write_ms']} | {r['batch_sum_ms']} | {r['slice_ms']} |")
    lines += ["", report["validation"], "",
              "Method: read timings are medians of 7 runs after warmup, including file opening. Batch operation sums all numeric values across all files; HDF5 processes at most 4096 rows at a time. Slice reads use the middle 100 rows and first two numeric columns of the largest run. DAT parses only that run for the slice; JSON loads the whole project. Writes are single measurements from already-parsed records (JSON list conversion excluded), without fsync; they measure serialization, not durable commit time. No cache flushing or peak-RAM measurement was performed.", "",
              "Uncompressed HDF5 uses contiguous arrays. Gzip HDF5 uses level 4 + shuffle and chunks of up to 4096 rows × 1 column. Parsed JSON and both non-archive HDF5 variants contain equivalent metadata, timestamps, and float64 numeric data. Archive additionally embeds exact original file bytes (compressed). Input float64 parsing preserves source numeric precision, not original numeric text formatting; archive preserves the latter.", "",
              "Duplicate instrument column names are intentionally preserved by position, as are repeated header sections. Four files contain duplicate K2400_Voltage labels. No timestamp epoch or time zone is inferred. This format is experimental and is not yet loadable by Rogi's GUI.", "",
              "This small corpus does not validate larger-than-memory performance, parallel throughput, fitting performance, or crash recovery. Compression and per-dataset overhead depend on the actual data and layout.", "",
              "Reproduce: `.venv/bin/python scripts/hdf5_trial.py` (requires numpy and h5py).",
              "", "Environment: " + json.dumps(report["environment"])]
    (OUT / "REPORT.md").write_text("\n".join(lines)+"\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
