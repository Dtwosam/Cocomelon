"""Exclusive Mac account owner and independent custody for volatility V1 only.

Clean recovery requires byte-identical account checkpoints and all authenticated
original source. An unacknowledged tail is permanently UNQUALIFIED; known local
positions may be protected, but their latest economics are not certified. Missing
or rolled-back original stores are never replaced with an older remote account.
"""

from __future__ import annotations

import fcntl
import gzip
import json
import os
import re
import sqlite3
import tempfile
import threading
import time
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from cocomelon.research.volatility_budget_paper import (
    IMMUTABLE_ACCOUNT_TABLES,
    VolatilityPaperTrial,
)
from cocomelon.research.volatility_custody import CustodyReceipt, GitCustody, capture_trial_files


def _wall_ms() -> int:
    return time.time_ns() // 1_000_000


def _json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


class OwnerJournal(Protocol):
    def archive(self) -> dict[str, bytes]: ...
    def records(self) -> Iterator[dict[str, Any]]: ...
    def close(self) -> None: ...


@dataclass(frozen=True)
class PreparedCheckpoint:
    files: dict[str, bytes]
    summary: dict[str, Any]
    pending: dict[str, Any] | None
    expected_head: str


def _source_rows(content: bytes) -> tuple[bytes, ...]:
    return tuple(_json(json.loads(line)) for line in gzip.decompress(content).splitlines())


def _source_prefix(remote: Mapping[str, bytes], local: Mapping[str, bytes]) -> None:
    """Compare original ordered ordinals; overlapping exports cannot multiply rows."""
    pattern = re.compile(r"source/(.+)-(\d{10})-(\d{3})-[0-9a-f]{64}\.jsonl\.gz")
    ordinal_rows: dict[str, dict[int, bytes]] = {}
    fragments: list[tuple[bytes, ...]] = []
    for name, content in local.items():
        if not name.startswith("source/"):
            continue
        if not name.endswith(".jsonl.gz"):
            raise ValueError("unsupported original source archive")
        rows = _source_rows(content)
        fragments.append(rows)
        match = pattern.fullmatch(name)
        if match is None:
            continue
        journal, start, count = match.group(1), int(match.group(2)), int(match.group(3))
        if len(rows) != count:
            raise ValueError("original source ordering/count mismatch")
        positions = ordinal_rows.setdefault(journal, {})
        for offset, row in enumerate(rows):
            position = start + offset
            if position in positions and positions[position] != row:
                raise ValueError("original source ordering conflict")
            positions[position] = row
    for name, content in remote.items():
        if not name.startswith("source/"):
            continue
        if not name.endswith(".jsonl.gz"):
            raise ValueError("unsupported original source archive")
        rows = _source_rows(content)
        match = pattern.fullmatch(name)
        if match is not None:
            journal, start, count = match.group(1), int(match.group(2)), int(match.group(3))
            actual = ordinal_rows.get(journal, {})
            valid = len(rows) == count and all(
                actual.get(start + offset) == row for offset, row in enumerate(rows)
            )
        else:
            # A complete legacy export is acceptable only as an ordered,
            # contiguous original fragment, never a multiset of equal clocks.
            valid = any(
                fragment[offset : offset + len(rows)] == rows
                for fragment in fragments
                for offset in range(len(fragment) - len(rows) + 1)
            )
        if not valid:
            raise ValueError("original source rollback/missing custody fragment or ordering")


def _database_rows(content: bytes, tables: tuple[str, ...]) -> dict[str, list[tuple[Any, ...]]]:
    with tempfile.TemporaryDirectory(prefix="volatility-owner-verify-") as directory:
        path = Path(directory) / "original.sqlite"
        path.write_bytes(content)
        with sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True) as connection:
            return {
                table: list(connection.execute(f'SELECT * FROM "{table}" ORDER BY rowid'))
                for table in tables
            }


def _checkpoint(content: bytes) -> dict[str, Any]:
    rows = _database_rows(content, ("checkpoint",))["checkpoint"]
    if len(rows) != 1 or rows[0][0] != 1:
        raise ValueError("original trial checkpoint missing")
    value: dict[str, Any] = json.loads(rows[0][1])
    return value


def _ledger_prefix(remote: Mapping[str, bytes], local: Mapping[str, bytes]) -> None:
    old, current = _checkpoint(remote["trial.sqlite"]), _checkpoint(local["trial.sqlite"])
    if old["identity"] != current["identity"] or current["revision"] < old["revision"]:
        raise ValueError("original account checkpoint rollback/identity mismatch")
    for name in ("candidate.sqlite", "control.sqlite", "trial.sqlite"):
        tables = ("events",) if name == "trial.sqlite" else IMMUTABLE_ACCOUNT_TABLES
        before = _database_rows(remote[name], tables)
        after = _database_rows(local[name], tables)
        if any(after[table][: len(rows)] != rows for table, rows in before.items()):
            raise ValueError("original account immutable history rollback/conflict")


class TrialOwner:
    """Root flock precedes every journal/state access and outlives final custody."""

    def __init__(
        self,
        root: Path,
        *,
        identity: Mapping[str, Any],
        custody: GitCustody,
        journal_factory: Callable[[Path], OwnerJournal],
        clock: Callable[[], int] = _wall_ms,
    ) -> None:
        if dict(identity) != custody.identity:
            raise ValueError("owner/independent custody identity mismatch")
        if any(p.is_symlink() for p in (root, *root.parents)):
            raise ValueError("original owner root alias forbidden")
        if not root.is_dir():
            raise ValueError("original owner root required; no implicit genesis")
        for name in ("trial.sqlite", "candidate.sqlite", "control.sqlite", "source.sqlite"):
            path = root / name
            if not path.is_file() or path.stat().st_size == 0:
                raise ValueError("original account/source history required")
            if path.is_symlink() or path.stat().st_nlink != 1:
                raise ValueError("original account/source alias forbidden")
        self.root, self.clock, self.custody = root, clock, custody
        self._closed = False
        self._failure: str | None = None
        self._publishing = threading.Lock()
        self._lock = os.open(root / ".service.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(self._lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            os.close(self._lock)
            raise RuntimeError("exclusive volatility service owner lease held") from error
        try:
            self.journal = journal_factory(root / "source.sqlite")
            tuple(self.journal.records())
            latest = custody.latest()
            if latest is None:
                raise ValueError("original independent account custody missing")
            remote = custody.read_files(latest)
            local = {**capture_trial_files(root), **self.journal.archive()}
            _source_prefix(remote, local)
            self.unclean_recovery = (
                latest.pending is not None
                or latest.summary.get("latest_account_verified", True) is not True
            )
            if self.unclean_recovery:
                _ledger_prefix(remote, local)
            else:
                custody.assert_current({**remote, **local})
            self.receipt = custody.acquire(now_ms=clock())
            self._files = remote
            # Constructing the durable trial legitimately advances its revision.
            # Fence that unacknowledged startup tail BEFORE any such local write,
            # so interruption cannot strand protection behind a clean receipt.
            self.receipt = custody.publish(
                remote,
                summary=latest.summary,
                pending={"owner_startup": True, "unacknowledged_tail_is_not_complete": True},
                now_ms=clock(),
            )
            self.trial = VolatilityPaperTrial(
                root,
                candidate_id=identity["candidate_id"],
                control_id=identity["control_id"],
                first_entry_ms=identity["first_entry_ms"],
                startup_ms=clock(),
            )
            if self.unclean_recovery:
                self.trial.record_source_fault(
                    "CUSTODY_UNCLEAN_TAIL_UNQUALIFIED", permanent=True, now_ms=clock()
                )
            if not self.lease_valid():
                raise RuntimeError("independent owner lease expired during recovery")
        except Exception:
            if hasattr(self, "trial"):
                self.trial.close()
            if hasattr(self, "journal"):
                self.journal.close()
            self._unlock()
            raise

    def _unlock(self) -> None:
        fcntl.flock(self._lock, fcntl.LOCK_UN)
        os.close(self._lock)
        self._closed = True

    def lease_valid(self, now_ms: int | None = None) -> bool:
        now = self.clock() if now_ms is None else now_ms
        return (
            not self._closed
            and self.receipt.owner_id == self.custody.owner_id
            and self.receipt.time_ms <= now < self.receipt.lease_until_ms
        )

    @property
    def entries_allowed(self) -> bool:
        return (
            self.lease_valid()
            and self._failure is None
            and not self.unclean_recovery
            and not self.trial.snapshot()["permanently_disabled"]
        )

    def disable(self, reason: str) -> None:
        self._failure = reason
        self.trial.entries_authorized = False
        if not self.trial._closed:
            self.trial.record_source_fault(reason, permanent=True, now_ms=self.clock())

    def prepare_checkpoint(self, *, clean: bool = False) -> PreparedCheckpoint:
        """Call on the serialized actor, then publish immutable bytes off-loop."""
        if self._closed:
            raise RuntimeError("volatility owner closed")
        try:
            files = {**self._files, **capture_trial_files(self.root), **self.journal.archive()}
            summary = json.loads(_json(self.trial.snapshot()))
            summary["latest_account_verified"] = not self.unclean_recovery and self._failure is None
            return PreparedCheckpoint(
                files=files,
                summary=summary,
                pending=None
                if clean
                else {"running": True, "unacknowledged_tail_is_not_complete": True},
                expected_head=self.receipt.commit,
            )
        except Exception:
            self.disable("CUSTODY_PREPARATION_FAILED_UNQUALIFIED")
            raise

    def publish_checkpoint(self, prepared: PreparedCheckpoint) -> CustodyReceipt:
        """Publish off-loop; failures disable entries while known protection survives."""
        if not self._publishing.acquire(blocking=False):
            raise RuntimeError("volatility custody publication already in progress")
        try:
            if prepared.expected_head != self.receipt.commit:
                raise RuntimeError("stale prepared volatility custody checkpoint")
            if not self.lease_valid():
                raise RuntimeError("independent owner lease expired; fenced recovery required")
            receipt = self.custody.publish(
                prepared.files,
                summary=prepared.summary,
                pending=prepared.pending,
                now_ms=self.clock(),
            )
            self.receipt, self._files = receipt, dict(prepared.files)
            if not self.lease_valid():
                raise RuntimeError("independent owner lease expired during publication")
            return receipt
        except Exception:
            # Do not call the SQLite actor from this worker thread. The caller
            # must invoke disable() on its serialized actor after observing this.
            self._failure = "CUSTODY_PUBLICATION_FAILED_UNQUALIFIED"
            self.trial.entries_authorized = False
            raise
        finally:
            self._publishing.release()

    def renew_fence_only(self) -> CustodyReceipt:
        """Retain protection ownership without certifying an unarchived local tail.

        Call off-loop only after the actor permanently disables qualification.
        The payload and economic summary remain the last independently confirmed
        account; no current cash, fills or source completeness is substituted.
        """
        if self._failure is None and not self.unclean_recovery:
            raise RuntimeError("fence-only renewal requires already UNQUALIFIED owner")
        if not self._publishing.acquire(blocking=False):
            raise RuntimeError("volatility custody publication already in progress")
        try:
            if not self.lease_valid():
                raise RuntimeError("independent owner lease expired; fenced recovery required")
            summary = json.loads(_json(self.receipt.summary))
            summary.update(
                latest_account_verified=False,
                entries_authorized=False,
                source_valid=False,
                current_account_has_unacknowledged_tail=True,
                custody_fault=self._failure or "CUSTODY_UNCLEAN_TAIL_UNQUALIFIED",
            )
            receipt = self.custody.publish(
                self._files,
                summary=summary,
                pending={
                    "protection_only": True,
                    "unacknowledged_tail_is_not_complete": True,
                    "last_confirmed_account_commit": self.receipt.commit,
                },
                now_ms=self.clock(),
            )
            self.receipt = receipt
            if not self.lease_valid():
                raise RuntimeError("independent owner lease expired during fence renewal")
            return receipt
        finally:
            self._publishing.release()

    def checkpoint(self, *, clean: bool = False) -> CustodyReceipt:
        """Synchronous convenience for a stopped/serialized actor, not a network loop."""
        prepared = self.prepare_checkpoint(clean=clean)
        try:
            return self.publish_checkpoint(prepared)
        except Exception:
            self.disable("CUSTODY_PUBLICATION_FAILED_UNQUALIFIED")
            raise

    def close(self, *, clean: bool = True) -> None:
        if self._closed:
            return
        if self._publishing.locked():
            raise RuntimeError("join custody publication before closing volatility owner")
        try:
            self.trial.entries_authorized = False
            # close() writes one final lifecycle revision. Capture only afterward.
            self.trial.close()
            self.checkpoint(clean=clean)
        finally:
            self.journal.close()
            self._unlock()

    def abandon(self) -> None:
        """Preserve an interrupted pending obligation; never acknowledge as clean."""
        if not self._closed:
            try:
                self.trial.entries_authorized = False
                self.trial.close()
                self.journal.close()
            finally:
                self._unlock()
