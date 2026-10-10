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


def first_changed_field(before: object, after: object) -> str | None:
    """Locate the first structural mismatch without exposing row contents."""

    def walk(old: object, new: object, path: str) -> str | None:
        if type(old) is not type(new):
            return path or "/"
        if isinstance(old, dict) and isinstance(new, dict):
            for key in sorted(set(old) | set(new)):
                child = path + "/" + _escape(key)
                if key not in old or key not in new:
                    return child
                difference = walk(old[key], new[key], child)
                if difference is not None:
                    return difference
            return None
        if isinstance(old, list) and isinstance(new, list):
            for index, (left, right) in enumerate(zip(old, new)):
                difference = walk(left, right, path + f"/{index}")
                if difference is not None:
                    return difference
            if len(old) != len(new):
                return path + f"/{min(len(old), len(new))}"
            return None
        return None if old == new else path or "/"

    return walk(before, after, "")


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
    changed = first_changed_field(dict(old), dict(current))
    if changed is None:
        raise ValueError("terminal drift receipt requested for equal rows")
    identity = hashlib.sha256(opportunity_id.encode("utf-8")).hexdigest()[:16]
    return f"opportunity_sha256_prefix={identity}, changed_json_pointer={changed}"
