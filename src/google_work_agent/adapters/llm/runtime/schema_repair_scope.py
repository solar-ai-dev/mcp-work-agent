"""Deterministic authority guard for one schema-repair candidate."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

type PathToken = str | int
type JsonPath = tuple[PathToken, ...]
type StableGroup = tuple[int, Mapping[object, object], int]

_PATH_TOKEN = re.compile(r"\.([A-Za-z_][A-Za-z0-9_]*)|\[(\d+)\]")
_STABLE_ARRAY_KEYS = ("route_id", "resource_type")


def find_out_of_scope_schema_repair_changes(
    *,
    failed_output: object,
    repaired_output: object,
    affected_field_paths: Sequence[str],
    output_schema: Mapping[str, object],
) -> tuple[str, ...]:
    """Return repaired paths that exceed the schema validator's failure scope."""

    scopes = tuple(
        path
        for value in affected_field_paths
        if (path := _parse_json_path(value)) is not None
    )
    if not scopes:
        return () if failed_output == repaired_output else ("$",)
    changes = _changes(
        failed_output,
        repaired_output,
        schema=output_schema,
        path=(),
        value_scopes=_narrowest(scopes),
        membership_scopes=scopes,
    )
    return tuple(sorted({_render(path) for path in changes}))


def _changes(
    before: object,
    after: object,
    *,
    schema: Mapping[str, object],
    path: JsonPath,
    value_scopes: tuple[JsonPath, ...],
    membership_scopes: tuple[JsonPath, ...],
) -> list[JsonPath]:
    if before == after:
        return []
    if isinstance(before, Mapping) and isinstance(after, Mapping):
        changes: list[JsonPath] = []
        properties = schema.get("properties")
        for key in sorted(set(before).union(after), key=str):
            child_path = path if not isinstance(key, str) else (*path, key)
            if key not in before or key not in after:
                if not _allowed(child_path, value_scopes):
                    changes.append(child_path)
                continue
            child_schema = properties.get(key) if isinstance(properties, Mapping) else None
            changes.extend(
                _changes(
                    before[key],
                    after[key],
                    schema=child_schema if isinstance(child_schema, Mapping) else {},
                    path=child_path,
                    value_scopes=value_scopes,
                    membership_scopes=membership_scopes,
                )
            )
        return changes
    if isinstance(before, list) and isinstance(after, list):
        stable_key = _stable_array_key(schema)
        if stable_key is not None:
            stable_changes = _stable_array_changes(
                before,
                after,
                schema=schema,
                path=path,
                stable_key=stable_key,
                value_scopes=value_scopes,
                membership_scopes=membership_scopes,
            )
            if stable_changes is not None:
                return stable_changes
        return _positional_array_changes(
            before,
            after,
            schema=schema,
            path=path,
            value_scopes=value_scopes,
            membership_scopes=membership_scopes,
        )
    return [] if _allowed(path, value_scopes) else [path]


def _stable_array_changes(
    before: list[object],
    after: list[object],
    *,
    schema: Mapping[str, object],
    path: JsonPath,
    stable_key: str,
    value_scopes: tuple[JsonPath, ...],
    membership_scopes: tuple[JsonPath, ...],
) -> list[JsonPath] | None:
    before_groups = _stable_groups(before, stable_key)
    after_groups = _stable_groups(after, stable_key)
    if before_groups is None or after_groups is None:
        return None
    item_schema = schema.get("items")
    item_schema = item_schema if isinstance(item_schema, Mapping) else {}
    item_scopes = tuple(scope for scope in value_scopes if scope != path)
    changes: list[JsonPath] = []
    common = set(before_groups).intersection(after_groups)
    for identity in sorted(common, key=str):
        before_index, before_item, before_count = before_groups[identity]
        _, after_item, after_count = after_groups[identity]
        changes.extend(
            _changes(
                before_item,
                after_item,
                schema=item_schema,
                path=(*path, before_index),
                value_scopes=item_scopes,
                membership_scopes=membership_scopes,
            )
        )
        duplicate_removed = after_count < before_count
        if before_count != after_count and (
            not duplicate_removed or not _membership_allowed(path, membership_scopes)
        ):
            changes.append(path)
    for identity in sorted(set(before_groups) - common, key=str):
        changes.append((*path, before_groups[identity][0]))
    required_additions = _required_stable_keys(schema, stable_key) - set(before_groups)
    for identity in sorted(set(after_groups) - common, key=str):
        if (
            identity not in required_additions
            or not _membership_allowed(path, membership_scopes)
        ):
            changes.append(path)
    return changes


def _positional_array_changes(
    before: list[object],
    after: list[object],
    *,
    schema: Mapping[str, object],
    path: JsonPath,
    value_scopes: tuple[JsonPath, ...],
    membership_scopes: tuple[JsonPath, ...],
) -> list[JsonPath]:
    items = schema.get("items")
    item_schema = items if isinstance(items, Mapping) else {}
    changes: list[JsonPath] = []
    for index, (before_item, after_item) in enumerate(zip(before, after, strict=False)):
        changes.extend(
            _changes(
                before_item,
                after_item,
                schema=item_schema,
                path=(*path, index),
                value_scopes=value_scopes,
                membership_scopes=membership_scopes,
            )
        )
    if len(before) != len(after) and not _membership_allowed(path, membership_scopes):
        changes.append(path)
    return changes


def _stable_groups(values: list[object], stable_key: str) -> dict[object, StableGroup] | None:
    groups: dict[object, StableGroup] = {}
    for index, item in enumerate(values):
        if not isinstance(item, Mapping):
            return None
        identity = item.get(stable_key)
        if not isinstance(identity, str | int) or isinstance(identity, bool):
            return None
        existing = groups.get(identity)
        if existing is not None and existing[1] != item:
            return None
        groups[identity] = (index, item, 1 if existing is None else existing[2] + 1)
    return groups


def _stable_array_key(schema: Mapping[str, object]) -> str | None:
    items = schema.get("items")
    if not isinstance(items, Mapping):
        return None
    one_of = items.get("oneOf")
    variants = (
        [item for item in one_of if isinstance(item, Mapping)]
        if isinstance(one_of, list)
        else [items]
    )
    for stable_key in _STABLE_ARRAY_KEYS:
        if variants and all(_requires_property(item, stable_key) for item in variants):
            return stable_key
    return None


def _requires_property(schema: Mapping[str, object], field: str) -> bool:
    required = schema.get("required")
    properties = schema.get("properties")
    return (
        isinstance(required, list)
        and field in required
        and isinstance(properties, Mapping)
        and field in properties
    )


def _required_stable_keys(schema: Mapping[str, object], stable_key: str) -> set[object]:
    required: set[object] = set()
    all_of = schema.get("allOf")
    if not isinstance(all_of, list):
        return required
    for constraint in all_of:
        contains = constraint.get("contains") if isinstance(constraint, Mapping) else None
        properties = contains.get("properties") if isinstance(contains, Mapping) else None
        field = properties.get(stable_key) if isinstance(properties, Mapping) else None
        if isinstance(field, Mapping) and "const" in field:
            required.add(field["const"])
    return required


def _narrowest(paths: tuple[JsonPath, ...]) -> tuple[JsonPath, ...]:
    return tuple(
        path
        for path in paths
        if not any(path != other and _prefix(path, other) for other in paths)
    )


def _allowed(path: JsonPath, scopes: tuple[JsonPath, ...]) -> bool:
    return any(_prefix(scope, path) or _prefix(path, scope) for scope in scopes)


def _membership_allowed(path: JsonPath, scopes: tuple[JsonPath, ...]) -> bool:
    return any(_prefix(scope, path) for scope in scopes)


def _prefix(prefix: JsonPath, path: JsonPath) -> bool:
    return len(prefix) <= len(path) and prefix == path[: len(prefix)]


def _parse_json_path(value: str) -> JsonPath | None:
    if value == "$":
        return ()
    if not value.startswith("$"):
        return None
    tokens: list[PathToken] = []
    position = 1
    while position < len(value):
        match = _PATH_TOKEN.match(value, position)
        if match is None:
            return None
        field, index = match.groups()
        tokens.append(field if field is not None else int(index))
        position = match.end()
    return tuple(tokens)


def _render(path: JsonPath) -> str:
    return "$" + "".join(
        f"[{token}]" if isinstance(token, int) else f".{token}" for token in path
    )


__all__ = ["find_out_of_scope_schema_repair_changes"]
