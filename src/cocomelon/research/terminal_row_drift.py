"""Minimal fail-closed diagnostics for immutable prospective terminal rows.

Return a stable JSON-pointer to the first changed field, never original or
replacement values. A receipt is diagnostic only: callers MUST still reject
any change to already published terminal economic rows.
"""
from __future__ import annotations

import hashlib
from collections.abc import Mapping


def _escape(part: object) -> str:
    return str(part).replace("~", "~0").replace("/", "~1")


MAX_DRIFT_PATHS = 12


def changed_field_paths(
    before: object,
    after: object,
    *,
    limit: int = MAX_DRIFT_PATHS,
) -> tuple[str, ...]:
    """List bounded, ordered JSON pointers only; never publish old/new values."""
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValueError("drift path limit must be positive")
    paths: list[str] = []

    def walk(old: object, new: object, path: str) -> None:
        if len(paths) >= limit:
            return
        if type(old) is not type(new):
            paths.append(path or "/")
            return
        if isinstance(old, dict) and isinstance(new, dict):
            for key in sorted(set(old) | set(new)):
                if len(paths) >= limit:
                    break
                child = path + "/" + _escape(key)
                if key not in old or key not in new:
                    paths.append(child)
                else:
                    walk(old[key], new[key], child)
            return
        if isinstance(old, list) and isinstance(new, list):
            for index, (left, right) in enumerate(zip(old, new, strict=False)):
                if len(paths) >= limit:
                    break
                walk(left, right, path + f"/{index}")
            if len(old) != len(new) and len(paths) < limit:
                paths.append(path + f"/{min(len(old), len(new))}")
            return
        if old != new:
            paths.append(path or "/")

    walk(before, after, "")
    return tuple(paths)


def first_changed_field(before: object, after: object) -> str | None:
    """Locate the first structural mismatch without exposing row contents."""
    changes = changed_field_paths(before, after, limit=1)
    return changes[0] if changes else None


def terminal_row_drift_receipt(
    opportunity_id: str,
    old: Mapping[str, object],
    current: Mapping[str, object],
) -> str:
    """An opaque opportunity fingerprint and safe deterministic changed path.

    This NEVER declares a row safe to merge or overwrites an earlier row.
    """
    if not isinstance(opportunity_id, str) or not opportunity_id:
        raise ValueError("terminal opportunity identity must be nonempty")
    changes = changed_field_paths(
        dict(old), dict(current), limit=MAX_DRIFT_PATHS + 1
    )
    if not changes:
        raise ValueError("terminal drift receipt requested for equal rows")
    truncated = len(changes) > MAX_DRIFT_PATHS
    paths = ",".join(changes[:MAX_DRIFT_PATHS])
    identity = hashlib.sha256(opportunity_id.encode("utf-8")).hexdigest()[:16]
    return (
        f"opportunity_sha256_prefix={identity}, "
        f"changed_json_pointer={changes[0]}, "
        f"changed_json_pointers={paths}, "
        f"drift_paths_truncated={str(truncated).lower()}"
    )
