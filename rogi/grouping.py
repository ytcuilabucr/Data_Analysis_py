"""Structured group paths and deterministic metadata partitioning."""
from copy import deepcopy
from collections import Counter
import re
from .metadata import metadata_fields, metadata_sort_key


def group_path(dataset):
    return deepcopy(dataset.group_path) or ([{'field': None, 'value': dataset.group}] if dataset.group else [])


def path_key(path):
    return tuple((node['field'], node['value']) for node in path)


def import_destinations(dataset, existing):
    """Return existing paths and evidence for conservative metadata suggestions.

    Explicit metadata levels must all match. For manually named groups, use
    fields shared by every member that vary across the project. Never infer
    metadata from a filename or interpret slashes in a manual group name.
    """
    incoming = metadata_fields(dataset)
    records = [(group_path(d), metadata_fields(d)) for d in existing]
    keys = {key for _, fields in records for key in fields}
    varying = {key for key in keys if len({f.get(key) for _, f in records}) > 1}
    paths = {}
    for path, _ in records:
        for depth in range(1, len(path) + 1):
            paths.setdefault(path_key(path[:depth]), path[:depth])
    result = []
    for path in paths.values():
        explicit = [(n['field'], n['value']) for n in path if n['field'] is not None]
        evidence = {}
        if all(incoming.get(key) == value for key, value in explicit):
            evidence = {key: value for key, value in explicit if value is not None}
            if path[-1]['field'] is None:
                members = [fields for p, fields in records if p[:len(path)] == path]
                shared = {key: members[0][key] for key in varying if key in members[0]
                          and all(f.get(key) == members[0][key] for f in members)}
                # A known conflict is stronger evidence than a partial match.
                if any(key in incoming and incoming[key] != value for key, value in shared.items()):
                    evidence = {}
                else:
                    evidence.update({k: v for k, v in shared.items() if incoming.get(k) == v})
        result.append((deepcopy(path), evidence))
    return result


def field_labels(fields):
    """Short display names, unique across the supplied full field identities."""
    fields = sorted(set(fields))
    names = {}
    for field in fields:
        match = re.fullmatch(r'.+?\[\d+\]\.(.+)\[\d+\]', field)
        name = match[1] if match else field
        names[field] = re.sub(r'^@\d+:', '', name)
    counts = Counter(name.casefold() for name in names.values())
    reserved = {name.casefold() for name in names.values()}
    labels = {}
    for field, name in names.items():
        label = name
        if counts[name.casefold()] > 1:
            number = 1
            while f'{name} [{number}]'.casefold() in reserved:
                number += 1
            label = f'{name} [{number}]'
        labels[field] = label
        reserved.add(label.casefold())
    return labels


def node_label(node, labels=None):
    value = 'Missing value' if node['value'] is None else node['value']
    field = node['field']
    return f"{(labels or {}).get(field, field)} = {value}" if field is not None else value


def path_label(path, labels=None):
    return ' / '.join(node_label(node, labels) for node in path)


def partitions(datasets, levels, append=False):
    """Return ordered (dataset, path) pairs; missing values always sort last."""
    fields = {d.id: metadata_fields(d) for d in datasets}
    def split(members, path, depth):
        if depth == len(levels):
            return [(d, deepcopy(path)) for d in members]
        key, descending = levels[depth]
        buckets = {}
        for d in members:
            buckets.setdefault(fields[d.id].get(key), []).append(d)
        values = sorted((v for v in buckets if v is not None), key=metadata_sort_key, reverse=descending)
        if None in buckets:
            values.append(None)
        return [pair for value in values for pair in split(
            buckets[value], path + [{'field': key, 'value': value}], depth + 1)]
    parents = {}
    for d in datasets:
        path = group_path(d) if append else []
        parents.setdefault(path_key(path), (path, []))[1].append(d)
    return [pair for path, members in parents.values() for pair in split(members, path, 0)]


def varying_fields(datasets, levels=(), append=False):
    buckets = {}
    for d, path in partitions(datasets, levels, append):
        buckets.setdefault(path_key(path), []).append(metadata_fields(d))
    used = {key for key, _ in levels}
    candidates = set()
    for fields in buckets.values():
        for key in {key for f in fields for key in f} - used:
            if len({f[key] for f in fields if key in f}) > 1:
                candidates.add(key)
    return sorted(candidates)
