"""Strategy-specific independent Git custody; never grants entry permission.

A remote pending receipt is an obligation, not a completed source archive. Missing
local bytes under such a receipt remain unknown and cannot be reset to genesis.
The caller must serialize lifecycle callbacks while capturing the three stores,
recheck actual wall-clock freshness after publication, and keep exits active when
custody prevents entries. GitHub is used for bounded critical custody, not an
unlimited market-data archive. No ordinary trader ref is modified here.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import tempfile
import zlib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from cocomelon.research.volatility_budget import PROTOCOL_SHA256

_LEDGER_NAMES = ("candidate.sqlite", "control.sqlite", "trial.sqlite")
_PAGE_SIZE = 64 * 1024
_MAX_FILE = 1024 * 1024 * 1024
_MAX_TOTAL = 2 * 1024 * 1024 * 1024
_MAX_HISTORY = 2 * 1024 * 1024 * 1024


def _json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _no_alias(path: Path) -> None:
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("custody path alias forbidden")
    if path.is_file() and path.stat().st_nlink != 1:
        raise ValueError("custody path hardlink forbidden")


def _manifest(files: Mapping[str, bytes]) -> dict[str, str]:
    if any(name not in files for name in _LEDGER_NAMES):
        raise ValueError("complete three-ledger custody required")
    total = 0
    result = {}
    for name, content in sorted(files.items()):
        parts = PurePosixPath(name).parts
        if (
            not name
            or name.startswith("/")
            or "\\" in name
            or any(part in {".", "..", ".git"} for part in parts)
            or PurePosixPath(name).as_posix() != name
            or not re.fullmatch(r"[A-Za-z0-9_./-]+", name)
        ):
            raise ValueError("unsafe custody payload path")
        if not isinstance(content, bytes) or not content or len(content) > _MAX_FILE:
            raise ValueError("custody file capacity exceeded or empty")
        total += len(content)
        result[name] = _digest(content)
    if total > _MAX_TOTAL:
        raise ValueError("custody snapshot capacity exceeded")
    return result


def capture_trial_files(root: Path) -> dict[str, bytes]:
    """Backup live SQLite including WAL; caller must hold its serialized owner lock."""
    result = {}
    for name in _LEDGER_NAMES:
        path = root / name
        _no_alias(path)
        if not path.is_file():
            raise ValueError("original trial ledger missing")
        with tempfile.TemporaryDirectory(prefix="volatility-sqlite-") as directory:
            destination = Path(directory) / name
            with (
                sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True) as source,
                sqlite3.connect(destination) as target,
            ):
                source.backup(target)
            result[name] = destination.read_bytes()
    return result


@dataclass(frozen=True)
class CustodyReceipt:
    commit: str
    revision: int
    owner_id: str
    owner_generation: int
    lease_until_ms: int
    pending: dict[str, Any] | None
    summary: dict[str, Any]
    manifest: dict[str, str]
    identity: dict[str, Any]
    time_ms: int
    push_times_ms: tuple[int, ...]
    cumulative_bytes: int
    layout: dict[str, tuple[str, ...]]


class GitCustody:
    """One fixed policy identity, fenced owner generation and CAS checkpoint chain."""

    def __init__(
        self,
        cache: Path,
        *,
        remote: str,
        branch: str,
        identity: Mapping[str, Any],
        owner_id: str,
        lease_ms: int = 60_000,
    ) -> None:
        if identity.get("protocol_sha256") != PROTOCOL_SHA256:
            raise ValueError("frozen policy mismatch")
        if (
            not identity.get("candidate_id")
            or not identity.get("control_id")
            or identity["candidate_id"] == identity["control_id"]
            or type(identity.get("first_entry_ms")) is not int
        ):
            raise ValueError("immutable paired account identity required")
        if (
            not re.fullmatch(r"codex/volatility-[A-Za-z0-9_-]+-custody", branch)
            or not owner_id
            or not 15_000 <= lease_ms <= 120_000
        ):
            raise ValueError("invalid custody branch/owner/lease")
        if remote != "https://github.com/Dtwosam/Cocomelon.git" and not (
            Path(remote).is_absolute() and Path(remote).is_dir()
        ):
            raise ValueError("only the authorized repository or local test remote is permitted")
        _no_alias(cache)
        cache.mkdir(parents=True, exist_ok=True)
        self.cache = cache
        self.git_dir = cache / "objects.git"
        self.remote = remote
        self.ref = f"refs/heads/{branch}"
        self.identity = json.loads(_json(dict(identity)))
        self.owner_id = owner_id
        self.lease_ms = lease_ms
        self._held: CustodyReceipt | None = None
        self._known_remote_commit: str | None = None
        self._remote_objects: set[str] = set()
        self._page_cache: dict[str, bytes] = {}
        if not self.git_dir.exists():
            self._run(["init", "--bare", str(self.git_dir)], own_git=False)
        _no_alias(self.git_dir)

    def _run(
        self,
        arguments: list[str],
        *,
        data: bytes | None = None,
        own_git: bool = True,
        index_file: Path | None = None,
    ) -> bytes:
        command = ["git", "-c", "core.hooksPath=/dev/null", "-c", "credential.interactive=false"]
        if own_git:
            command += ["--git-dir", str(self.git_dir)]
        command += arguments
        environment = {
            **os.environ,
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_AUTHOR_NAME": "Cocomelon volatility PAPER custody",
            "GIT_AUTHOR_EMAIL": "paper-custody@localhost",
            "GIT_COMMITTER_NAME": "Cocomelon volatility PAPER custody",
            "GIT_COMMITTER_EMAIL": "paper-custody@localhost",
        }
        if index_file is not None:
            environment["GIT_INDEX_FILE"] = str(index_file)
        try:
            outcome = subprocess.run(
                command,
                input=data,
                capture_output=True,
                timeout=15,
                env=environment,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise RuntimeError("independent custody transport unavailable") from error
        if outcome.returncode:
            raise RuntimeError("independent custody Git operation failed; no entry authority")
        return outcome.stdout

    def latest(self) -> CustodyReceipt | None:
        found = self._run(["ls-remote", "--refs", self.remote, self.ref]).decode().strip()
        if not found:
            return None
        commit = found.split()[0]
        if not re.fullmatch(r"[0-9a-f]{40}", commit):
            raise RuntimeError("invalid independent custody head")
        self._run(["fetch", "--no-tags", "--no-write-fetch-head", self.remote, commit])
        document = json.loads(self._run(["show", f"{commit}:receipt.json"]))
        if document["identity"] != self.identity:
            raise RuntimeError("independent custody identity mismatch")
        if (
            document.get("schema") != "volatility-custody-v2"
            or document["revision"] < 1
            or document["owner_generation"] < 1
            or document["lease_until_ms"] <= document["time_ms"]
            or document["cumulative_bytes"] > _MAX_HISTORY
        ):
            raise RuntimeError("invalid independent custody receipt")
        receipt = CustodyReceipt(
            commit=commit,
            revision=document["revision"],
            owner_id=document["owner_id"],
            owner_generation=document["owner_generation"],
            lease_until_ms=document["lease_until_ms"],
            pending=document["pending"],
            summary=document["summary"],
            manifest=document["manifest"],
            identity=document["identity"],
            time_ms=document["time_ms"],
            push_times_ms=tuple(document["push_times_ms"]),
            cumulative_bytes=document["cumulative_bytes"],
            layout={name: tuple(pages) for name, pages in document["layout"].items()},
        )
        if set(receipt.layout) != set(receipt.manifest) or any(
            not pages or any(not re.fullmatch(r"[0-9a-f]{64}", page) for page in pages)
            for pages in receipt.layout.values()
        ):
            raise RuntimeError("invalid independent custody page layout")
        if self._known_remote_commit != commit:
            # Only objects reachable from the independently observed remote head
            # are already paid custody. Failed local publications never count.
            self._remote_objects = {
                line.split()[0]
                for line in self._run(["rev-list", "--objects", commit]).decode().splitlines()
            }
            self._known_remote_commit = commit
        return receipt

    def read_files(self, receipt: CustodyReceipt) -> dict[str, bytes]:
        if set(receipt.layout) != set(receipt.manifest):
            raise RuntimeError("independent custody page layout mismatch")
        digests = sorted({digest for pages in receipt.layout.values() for digest in pages})
        if any(not re.fullmatch(r"[0-9a-f]{64}", digest) for digest in digests):
            raise RuntimeError("invalid independent custody page identifier")
        # A single Git process returns all authenticated blobs. Per-page process
        # spawning would make a large genuine account exceed its owner lease.
        request = b"".join(f"{receipt.commit}:pages/{digest}.gz\n".encode() for digest in digests)
        batch = self._run(["cat-file", "--batch"], data=request)
        compressed: dict[str, bytes] = {}
        offset = 0
        for digest in digests:
            header_end = batch.find(b"\n", offset)
            header = batch[offset:header_end].split()
            if header_end < 0 or len(header) != 3 or header[1] != b"blob":
                raise RuntimeError("independent custody page missing/malformed")
            try:
                size = int(header[2])
            except ValueError as error:
                raise RuntimeError("invalid independent custody page length") from error
            offset = header_end + 1
            content = batch[offset : offset + size]
            offset += size
            if (
                size <= 0
                or size > _PAGE_SIZE + 1024
                or len(content) != size
                or batch[offset : offset + 1] != b"\n"
                or _digest(content) != digest
            ):
                raise RuntimeError("independent custody page digest/length mismatch")
            compressed[digest] = content
            offset += 1
        if offset != len(batch):
            raise RuntimeError("independent custody batch trailing/conflicting data")
        files: dict[str, bytes] = {}
        for name, pages in receipt.layout.items():
            pieces = []
            for digest in pages:
                content = compressed[digest]
                decompressor = zlib.decompressobj(wbits=31)
                page = decompressor.decompress(content, _PAGE_SIZE + 1)
                if len(page) > _PAGE_SIZE or not decompressor.eof or decompressor.unused_data:
                    raise RuntimeError("invalid independent custody compressed page")
                self._page_cache[_digest(page)] = content
                pieces.append(page)
            files[name] = b"".join(pieces)
        if _manifest(files) != receipt.manifest:
            raise RuntimeError("independent custody payload digest mismatch")
        return files

    def initialize(
        self,
        files: Mapping[str, bytes],
        *,
        summary: dict[str, Any],
        now_ms: int,
        pending: dict[str, Any] | None = None,
    ) -> CustodyReceipt:
        _manifest(files)
        if self.latest() is not None:
            raise RuntimeError("original independent custody already exists; reset forbidden")
        return self._publish(files, summary, now_ms, pending, prior=None, generation=1)

    def acquire(self, *, now_ms: int) -> CustodyReceipt:
        prior = self.latest()
        if prior is None:
            raise RuntimeError("original independent custody missing; no implicit genesis")
        if now_ms < prior.time_ms:
            raise RuntimeError("custody clock regression")
        if now_ms < prior.lease_until_ms:
            raise RuntimeError("independent custody owner lease still held")
        return self._publish(
            self.read_files(prior),
            prior.summary,
            now_ms,
            prior.pending,
            prior=prior,
            generation=prior.owner_generation + 1,
        )

    def publish(
        self,
        files: Mapping[str, bytes],
        *,
        summary: dict[str, Any],
        now_ms: int,
        pending: dict[str, Any] | None = None,
    ) -> CustodyReceipt:
        held = self._held
        if held is None:
            raise RuntimeError("independent custody owner not acquired")
        prior = self.latest()
        if (
            prior is None
            or prior.commit != held.commit
            or prior.owner_id != self.owner_id
            or prior.owner_generation != held.owner_generation
        ):
            raise RuntimeError("stale independent custody owner/head")
        if now_ms < prior.time_ms:
            raise RuntimeError("custody clock regression")
        if now_ms >= prior.lease_until_ms:
            raise RuntimeError("independent custody lease expired")
        return self._publish(
            files, summary, now_ms, pending, prior=prior, generation=prior.owner_generation
        )

    def _publish(
        self,
        files: Mapping[str, bytes],
        summary: dict[str, Any],
        now_ms: int,
        pending: dict[str, Any] | None,
        *,
        prior: CustodyReceipt | None,
        generation: int,
    ) -> CustodyReceipt:
        manifest = _manifest(files)
        if prior is not None and any(
            name.startswith("source/") and manifest.get(name) != digest
            for name, digest in prior.manifest.items()
        ):
            raise RuntimeError("original source custody cannot be deleted or rewritten")
        if type(now_ms) is not int or now_ms < 0:
            raise ValueError("valid custody clock required")
        push_times = tuple(t for t in (prior.push_times_ms if prior else ()) if t > now_ms - 60_000)
        if len(push_times) >= 6:
            raise RuntimeError("independent custody push budget exhausted")
        layout: dict[str, list[str]] = {}
        page_assets: dict[str, bytes] = {}
        page_objects: dict[str, str] = {}
        current_cache: dict[str, bytes] = {}
        for name, value in files.items():
            layout[name] = []
            for offset in range(0, len(value), _PAGE_SIZE):
                raw_page = value[offset : offset + _PAGE_SIZE]
                raw_digest = _digest(raw_page)
                compressed = self._page_cache.get(raw_digest)
                if compressed is None:
                    compressed = gzip.compress(raw_page, compresslevel=1, mtime=0)
                    # Python3.12 may inherit zlib's platform-specific OS byte.
                    # Fix it so identical original pages deduplicate on Mac/Linux.
                    compressed = compressed[:9] + b"\xff" + compressed[10:]
                current_cache[raw_digest] = compressed
                digest = _digest(compressed)
                layout[name].append(digest)
                page_assets[digest] = compressed
                # Git's object identity includes its typed length header. A page
                # reachable in an earlier committed tree is reused even if the
                # latest SQLite snapshot temporarily stopped referring to it.
                page_objects[digest] = hashlib.sha1(
                    f"blob {len(compressed)}\0".encode() + compressed, usedforsecurity=False
                ).hexdigest()
        changed_bytes = sum(
            len(content)
            for digest, content in page_assets.items()
            if page_objects[digest] not in self._remote_objects
        )
        cumulative = (prior.cumulative_bytes if prior else 0) + changed_bytes
        if cumulative > _MAX_HISTORY:
            raise RuntimeError("independent custody remote capacity exhausted")
        document = {
            "schema": "volatility-custody-v2",
            "identity": self.identity,
            "revision": prior.revision + 1 if prior else 1,
            "parent": prior.commit if prior else None,
            "owner_id": self.owner_id,
            "owner_generation": generation,
            "time_ms": now_ms,
            "lease_until_ms": now_ms + self.lease_ms,
            "push_times_ms": [*push_times, now_ms],
            "cumulative_bytes": cumulative,
            "pending": pending,
            "summary": summary,
            "manifest": manifest,
            "layout": layout,
        }
        with tempfile.TemporaryDirectory(prefix="volatility-custody-stage-") as directory:
            staging = Path(directory) / "staging"
            staging.mkdir()
            index_file = Path(directory) / "index"
            (staging / "receipt.json").write_bytes(_json(document))
            pages_directory = staging / "pages"
            pages_directory.mkdir()
            for digest, value in page_assets.items():
                (pages_directory / f"{digest}.gz").write_bytes(value)
            self._run(["read-tree", "--empty"], index_file=index_file)
            self._run(
                [f"--work-tree={staging}", "add", "--force", "--all", "."],
                index_file=index_file,
            )
            tree = self._run(["write-tree"], index_file=index_file).decode().strip()
        parents = ["-p", prior.commit] if prior else []
        commit = (
            self._run(["commit-tree", tree, *parents], data=b"Frozen volatility PAPER custody\n")
            .decode()
            .strip()
        )
        expected = prior.commit if prior else ""
        self._run(
            [
                "push",
                "--porcelain",
                f"--force-with-lease={self.ref}:{expected}",
                self.remote,
                f"{commit}:{self.ref}",
            ]
        )
        # The successful CAS made these page objects independently reachable;
        # retain the set rather than rewalking growing history on every renewal.
        self._remote_objects.update(page_objects.values())
        self._page_cache = current_cache
        self._known_remote_commit = commit
        receipt = self.latest()
        if receipt is None or receipt.commit != commit:
            raise RuntimeError("independent custody publication not authenticated")
        self._held = receipt
        return receipt

    def assert_current(self, files: Mapping[str, bytes]) -> CustodyReceipt:
        receipt = self.latest()
        if receipt is None or _manifest(files) != receipt.manifest:
            raise RuntimeError("local custody rollback/mismatch; original recovery required")
        return receipt

    def restore(self, destination: Path, receipt: CustodyReceipt | None = None) -> CustodyReceipt:
        latest = self.latest()
        if latest is None or (receipt is not None and latest.commit != receipt.commit):
            raise RuntimeError("latest independent custody required for restore")
        _no_alias(destination)
        if destination.exists() and any(destination.iterdir()):
            raise ValueError("custody restore requires empty destination; no account overwrite")
        destination.mkdir(parents=True, exist_ok=True)
        for name, value in self.read_files(latest).items():
            path = destination / name
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("xb") as output:
                output.write(value)
                output.flush()
                os.fsync(output.fileno())
        receipt_document = {
            **json.loads(self._run(["show", f"{latest.commit}:receipt.json"])),
            "commit": latest.commit,
        }
        with (destination / "custody-receipt.json").open("xb") as output:
            output.write(_json(receipt_document))
            output.flush()
            os.fsync(output.fileno())
        if self.latest() != latest:
            raise RuntimeError("independent custody changed during restore; entries forbidden")
        return latest
