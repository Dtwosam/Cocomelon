"""Mac owner for the frozen volatility PAPER trial; no LIVE adapter or credentials.

Admission is checked before any market connection or account genesis. A pending
remote tail is never a source certificate: unclean recovery disables entries and
qualification permanently while retaining known local protective obligations.
"""

from __future__ import annotations

import argparse
import asyncio
import gzip
import hashlib
import ipaddress
import json
import os
import plistlib
import signal
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Callable, Iterator, Mapping
from decimal import Decimal
from pathlib import Path
from typing import Any

from cocomelon.domain.execution import InstrumentExecutionSpec
from cocomelon.domain.features import EligibilityDecision
from cocomelon.domain.market import MarketId
from cocomelon.domain.stream import StreamEvent, StreamKind
from cocomelon.execution.funding import FundingAccrual, funding_cash_delta
from cocomelon.execution.store import _position_from_payload
from cocomelon.features.assemble import assemble_feature_snapshot
from cocomelon.features.broad import calculate_broad_features
from cocomelon.features.microstructure import calculate_microstructure_features
from cocomelon.hyperliquid.rate_limit import RollingRateBudget
from cocomelon.research.volatility_budget import DAY_MS, PROTOCOL_SHA256
from cocomelon.research.volatility_budget_paper import VolatilityPaperTrial
from cocomelon.research.volatility_custody import GitCustody, capture_trial_files
from cocomelon.research.volatility_source import MARKETS, VolatilitySource
from cocomelon.scanner.eligibility import (
    EligibilityConfig,
    derive_eligibility_thresholds,
    evaluate_eligibility,
)


def wall_ms() -> int:
    return time.time_ns() // 1_000_000


def _json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def validate_admission(receipt: Mapping[str, Any], *, now_ms: int) -> None:
    """Require independently reviewed, expiring evidence; a directory is no proof."""
    network = receipt.get("network", {})
    if (
        network.get("ownership") != "operator_verified"
        or network.get("all_consumers_accounted") is not True
    ):
        raise ValueError("aggregate outbound-IP safety is not admitted")
    try:
        address = ipaddress.ip_address(network["public_ip"])
        limits = {
            "other_rest_peak_weight": 600,
            "other_ws_peak_connections": 8,
            "other_ws_peak_subscriptions": 984,
            "other_ws_new_per_minute": 24,
            "other_ws_sent_per_minute": 1900,
        }
        if not address.is_global or any(
            type(network.get(key)) is not int or not 0 <= network[key] <= limit
            for key, limit in limits.items()
        ):
            raise ValueError("invalid combined resource reserve")
    except (KeyError, ValueError, TypeError) as error:
        raise ValueError("aggregate resource peak/reserve evidence incomplete") from error
    if receipt.get("policy_sha256") != PROTOCOL_SHA256:
        raise ValueError("frozen policy mismatch")
    release, first = receipt.get("release_ms"), receipt.get("first_entry_ms")
    if (
        type(release) is not int
        or type(first) is not int
        or first % DAY_MS != 30_000
        or first < release + 6 * 3_600_000
        or release > now_ms
    ):
        raise ValueError("prospective release/first-entry boundary invalid")
    if not now_ms < receipt.get("review_expires_ms", -1) <= receipt["release_ms"] + 180 * DAY_MS:
        raise ValueError("operational review expired or unbounded")
    gates = receipt.get("mandatory_checks", {})
    if set(gates) != {str(i) for i in range(1, 15)} or set(gates.values()) != {"PASS"}:
        raise ValueError("all fourteen independent admission checks must pass")
    for field in ("code_sha", "independent_review_sha256", "resource_evidence_sha256"):
        length = 40 if field == "code_sha" else 64
        value = receipt.get(field, "")
        if (
            not isinstance(value, str)
            or len(value) != length
            or any(c not in "0123456789abcdef" for c in value)
        ):
            raise ValueError("immutable operational evidence missing")


class SourceJournal:
    """Fsync original receipts before parsing, with an independently exportable chain."""

    def __init__(self, path: Path) -> None:
        if any(p.is_symlink() for p in (path, *path.parents)):
            raise ValueError("source journal alias forbidden")
        if path.is_file() and path.stat().st_nlink != 1:
            raise ValueError("source journal hardlink alias forbidden")
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._chunks: dict[str, bytes] = {}
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS receipts "
            "(ordinal INTEGER PRIMARY KEY, payload BLOB NOT NULL, digest TEXT NOT NULL)"
        )
        self.db.commit()
        # Validate the entire source chain before exposing it for recovery.
        tuple(self.records())

    def append(self, receipt: dict[str, object]) -> None:
        with self._lock:
            self._append(receipt)

    def _append(self, receipt: dict[str, object]) -> None:
        previous = self.db.execute("SELECT digest FROM receipts ORDER BY ordinal DESC LIMIT 1")
        row = previous.fetchone()
        payload = _json(receipt)
        digest = hashlib.sha256((row[0] if row else "").encode() + payload).hexdigest()
        with self.db:
            self.db.execute("INSERT INTO receipts(payload,digest) VALUES(?,?)", (payload, digest))

    def records(self) -> Iterator[dict[str, Any]]:
        with self._lock:
            yield from self._records()

    def _records(self) -> Iterator[dict[str, Any]]:
        previous = ""
        for payload, digest in self.db.execute(
            "SELECT payload,digest FROM receipts ORDER BY ordinal"
        ):
            if hashlib.sha256(previous.encode() + payload).hexdigest() != digest:
                raise ValueError("original source custody chain mismatch")
            value = json.loads(payload)
            if not isinstance(value, dict):
                raise ValueError("original source receipt malformed")
            yield value
            previous = digest

    def archive(self) -> dict[str, bytes]:
        # Fixed-size original segments avoid repeatedly copying full history.
        # A previously published partial tail remains immutable in remote custody.
        with self._lock:
            result = dict(self._chunks)
            cursor = self.db.execute("SELECT payload FROM receipts ORDER BY ordinal")
            index = 0
            while rows := cursor.fetchmany(128):
                key = f"source/{self.path.stem}-{index:010d}-{len(rows):03d}"
                cached = next((k for k in self._chunks if k.startswith(key + "-")), None)
                if cached is not None:
                    result[cached] = self._chunks[cached]
                else:
                    content = gzip.compress(b"\n".join(row[0] for row in rows), mtime=0)
                    name = key + "-" + hashlib.sha256(content).hexdigest() + ".jsonl.gz"
                    result[name] = content
                    if len(rows) == 128:
                        self._chunks[name] = content
                index += 128
            return result

    def close(self) -> None:
        with self._lock:
            self.db.close()


class JournalSet:
    """Raw wire and normalized input custody, kept distinct without clock rewriting."""

    def __init__(self, path: Path) -> None:
        self.normalized = SourceJournal(path)
        self.ingress = SourceJournal(path.with_name("ingress.sqlite"))

    def append(self, row: dict[str, object]) -> None:
        self.normalized.append(row)

    def records(self) -> Iterator[dict[str, Any]]:
        return self.normalized.records()

    def archive(self) -> dict[str, bytes]:
        return {**self.normalized.archive(), **self.ingress.archive()}

    def close(self) -> None:
        self.normalized.close()
        self.ingress.close()


class ServiceBudget:
    """One nonblocking charged ledger; 180/300 remains for held obligations."""

    def __init__(self) -> None:
        self.ledger = RollingRateBudget(limit=300)
        self.priority = False

    def acquire(self, weight: int) -> None:
        if not self.ledger.try_acquire(weight, reserve_remaining=0 if self.priority else 180):
            raise RuntimeError("volatility request quota unavailable")


class VolatilityService:
    """Serialized lifecycle driver. Construction never authorizes new exposure."""

    def __init__(
        self,
        trial: VolatilityPaperTrial,
        *,
        clock: Callable[[], int] = wall_ms,
        unclean_recovery: bool = False,
        fence: Callable[[int], bool] = lambda _: True,
    ) -> None:
        self.trial = trial
        self.clock = clock
        self.fence = fence
        self.custody_complete = not unclean_recovery
        trial.entries_authorized = False
        if unclean_recovery:
            trial.record_source_fault(
                "CUSTODY_UNCLEAN_TAIL_UNQUALIFIED", permanent=True, now_ms=clock()
            )

    def tick(self) -> None:
        self.trial.tick(now_ms=self._now())

    def _now(self) -> int:
        now = self.clock()
        if not self.fence(now):
            self.trial.entries_authorized = False
            raise RuntimeError("independent owner fence expired before mutation")
        return now

    def on_mark(self, event: StreamEvent) -> None:
        self.trial.on_mark(event, now_ms=self._now())

    def on_book(self, event: StreamEvent, instrument: InstrumentExecutionSpec) -> None:
        self.trial.on_book(event, instrument, now_ms=self._now())

    def refresh_entry_authority(self, receipt: Mapping[str, Any], *, source_valid: bool) -> bool:
        try:
            validate_admission(receipt, now_ms=self.clock())
        except ValueError:
            self.trial.entries_authorized = False
            return False
        self.trial.entries_authorized = source_valid and self.custody_complete
        return self.trial.entries_authorized

    def evaluate_batch(self, source: VolatilitySource, *, epoch_ms: int) -> None:
        # Prepare from already received inputs. The final genuine clock is read
        # immediately before evaluate; a delayed timer is UNKNOWN, never retimed.
        windows = source.daily_windows(epoch_ms, eligibility=ordinary_eligibility(source, epoch_ms))
        instruments, books = source.instruments(), source.books
        actual = self._now()
        self.trial.evaluate(windows, instruments, books, now_ms=actual)

    def funding(self, source: VolatilitySource) -> None:
        for boundary in self.trial.snapshot()["funding_obligations"]:
            if boundary["accrual_id"] is not None or boundary["oracle"] is None:
                continue
            position = _position_from_payload(boundary["position"])
            rate = source.funding_rates.get((position.market, boundary["boundary_ms"]))
            if rate is None:
                continue
            oracle = boundary["oracle"]
            signed = position.quantity if position.side.value == "long" else -position.quantity
            price = Decimal(oracle["payload"]["oracle_px"])
            self.trial.apply_funding(
                FundingAccrual(
                    position.market,
                    boundary["boundary_ms"],
                    position.position_id,
                    signed,
                    price,
                    rate.funding_rate,
                    funding_cash_delta(signed, price, rate.funding_rate),
                    oracle["event_key"],
                    rate.source,
                    rate.received_at_ms,
                ),
                now_ms=self._now(),
            )


def ordinary_eligibility(
    source: VolatilitySource, now_ms: int
) -> dict[MarketId, EligibilityDecision]:
    config = EligibilityConfig()
    features = {}
    for market, snapshot in source.snapshots.items():
        if snapshot.received_at_ms > now_ms:
            continue
        try:
            book = source.books.get(market)
            micro = (
                None if book is None else calculate_microstructure_features(book, as_of_ms=now_ms)
            )
            features[market] = assemble_feature_snapshot(
                market,
                calculate_broad_features(snapshot, None, as_of_ms=now_ms),
                microstructure=micro,
                as_of_ms=now_ms,
                provenance=(snapshot.source,),
            )
        except ValueError:
            continue
    if not features:
        return {}
    thresholds = derive_eligibility_thresholds(tuple(features.values()), config)
    return {
        market: evaluate_eligibility(source.snapshots[market], value, thresholds, config)
        for market, value in features.items()
        if market in MARKETS
    }


def launch_agent(python: Path, config: Path, *, code_root: Path | None = None) -> bytes:
    """Render only this reviewed command. Installation is a separate admitted action."""
    return plistlib.dumps(
        {
            "Label": "org.cocomelon.volatility-paper",
            "ProgramArguments": [
                "/usr/bin/caffeinate",
                "-i",
                str(python),
                "-m",
                "cocomelon.research.volatility_service",
                "--config",
                str(config),
            ],
            "KeepAlive": True,
            "RunAtLoad": True,
            "ThrottleInterval": 15,
            "WorkingDirectory": str(code_root or Path(__file__).resolve().parents[3]),
            "EnvironmentVariables": {
                "COCOMELON_EXECUTION_MODE": "paper",
                "PYTHONPATH": str((code_root or Path(__file__).resolve().parents[3]) / "src"),
            },
        }
    )


def verify_deployed_code(root: Path, code_sha: str) -> None:
    if any(p.is_symlink() for p in (root, *root.parents)):
        raise ValueError("deployed code path alias forbidden")
    if root.resolve() != Path(__file__).resolve().parents[3]:
        raise ValueError("imported service differs from deployed checkout")
    head = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True)
    if head.strip() != code_sha:
        raise ValueError("deployed code differs from reviewed activation")
    paths = ["src", "research/experiments/volatility-budget-v1/policy.json", "pyproject.toml"]
    dirty = subprocess.check_output(
        ["git", "-C", str(root), "status", "--porcelain", "--untracked-files=all", "--", *paths]
    )
    if dirty:
        raise ValueError("deployed runtime has unreviewed bytes")
    policy = root / paths[1]
    if hashlib.sha256(policy.read_bytes()).hexdigest() != PROTOCOL_SHA256:
        raise ValueError("deployed frozen policy mismatch")


def funding_requests(trial: VolatilityPaperTrial) -> dict[MarketId, int]:
    requests: dict[MarketId, int] = {}
    for boundary in trial.snapshot()["funding_obligations"]:
        if boundary["accrual_id"] is None:
            market = _position_from_payload(boundary["position"]).market
            requests[market] = min(
                requests.get(market, boundary["boundary_ms"]), boundary["boundary_ms"]
            )
    return requests


def required_markets(trial: VolatilityPaperTrial, now_ms: int) -> tuple[MarketId, ...]:
    snapshot = trial.snapshot()
    if 20_000 <= now_ms % DAY_MS <= 32_000:
        return MARKETS
    held = {position.market for position in trial.candidate.account.positions}
    if snapshot["pending"] is not None and snapshot["selected_market"] is not None:
        held.update(m for m in MARKETS if m.canonical == snapshot["selected_market"])
    return tuple(m for m in MARKETS if m in held)


def verify_egress(expected: str) -> None:
    from urllib.request import urlopen

    # A nonmarket lookup validates route identity, never other NAT consumers.
    # Ownership/consumer evidence is still mandatory before reaching this call.
    with urlopen("https://api.ipify.org", timeout=3) as response:
        actual = response.read(128).decode("ascii").strip()
    if ipaddress.ip_address(actual) != ipaddress.ip_address(expected):
        raise ValueError("current outbound IP differs from admitted resource evidence")


def prepare(config: dict[str, Any]) -> None:
    """Explicit one-time genesis after admission, never a fallback for lost state."""
    receipt = dict(config["activation"])
    now = wall_ms()
    validate_admission(receipt, now_ms=now)
    if receipt["first_entry_ms"] < now + 6 * 3_600_000:
        raise ValueError("new genesis requires a genuinely future six-hour entry boundary")
    receipt["release_ms"] = now
    verify_deployed_code(Path(config["code_root"]), receipt["code_sha"])
    verify_egress(receipt["network"]["public_ip"])
    root = Path(config["root"])
    if root.exists() or any(path.is_symlink() for path in (root, *root.parents)):
        raise ValueError("preparation cannot replace an existing or aliased account root")
    identity = {
        **config["identity"],
        "activation_sha256": hashlib.sha256(_json(receipt)).hexdigest(),
    }
    if identity.get("first_entry_ms") != receipt["first_entry_ms"]:
        raise ValueError("prospective account boundary mismatch")
    if config["custody_remote"] != "https://github.com/Dtwosam/Cocomelon.git":
        raise ValueError("independent production custody must use the authorized repository")
    custody = GitCustody(
        Path(config["custody_cache"]),
        remote=config["custody_remote"],
        branch=config["custody_branch"],
        identity=identity,
        owner_id=uuid.uuid4().hex,
    )
    if custody.latest() is not None:
        raise ValueError("independent original trial exists; no account reset")
    root.mkdir(parents=True, mode=0o700)
    journal = JournalSet(root / "source.sqlite")
    obj = VolatilityPaperTrial(
        root,
        candidate_id=identity["candidate_id"],
        control_id=identity["control_id"],
        first_entry_ms=receipt["first_entry_ms"],
        startup_ms=wall_ms(),
        prepare_new=True,
    )
    try:
        obj.close()  # Final revision precedes independent genesis custody.
        files = {
            **capture_trial_files(root),
            **journal.archive(),
            "activation.json": _json(receipt),
        }
        genesis = custody.initialize(files, summary=obj.snapshot(), now_ms=wall_ms())
        acknowledged = wall_ms()
        if receipt["first_entry_ms"] < acknowledged + 6 * 3_600_000:
            raise ValueError("genesis acknowledgement left less than six prospective hours")
        activation = receipt
        with (root / "activation.json").open("xb") as stream:
            stream.write(_json(activation))
            stream.flush()
            os.fsync(stream.fileno())
        prepared_config = {
            **config,
            "identity": identity,
            "activation": activation,
            "genesis_commit": genesis.commit,
            "genesis_acknowledged_ms": acknowledged,
            "candidate_starting_cash": "10000",
            "control_starting_cash": "10000",
        }
        with (root / "prepared-config.json").open("xb") as stream:
            stream.write(_json(prepared_config))
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        obj.close()
        journal.close()


async def run(config: dict[str, Any]) -> None:
    """Run an already prepared, independently admitted trial. No implicit genesis."""
    from cocomelon.research.volatility_owner import TrialOwner
    from cocomelon.research.volatility_transport import VolatilityTransport

    receipt = config["activation"]
    validate_admission(receipt, now_ms=wall_ms())
    if os.environ.get("COCOMELON_EXECUTION_MODE", "paper") != "paper":
        raise ValueError("this service accepts PAPER only")
    verify_deployed_code(Path(config["code_root"]), receipt["code_sha"])
    await asyncio.to_thread(verify_egress, receipt["network"]["public_ip"])
    if config["custody_remote"] != "https://github.com/Dtwosam/Cocomelon.git":
        raise ValueError("production custody requires the independently held authorized repository")
    root = Path(config["root"])
    if any(path.is_symlink() for path in (root, *root.parents)):
        raise ValueError("original trial root alias forbidden")
    if not (root / "ingress.sqlite").is_file():
        raise ValueError("original raw ingress custody missing; no implicit reset")
    identity = config["identity"]
    if (
        identity.get("protocol_sha256") != PROTOCOL_SHA256
        or identity.get("first_entry_ms") != receipt["first_entry_ms"]
    ):
        raise ValueError("activation and paired-account identity differ")
    activation_bytes = (root / "activation.json").read_bytes()
    if activation_bytes != _json(receipt) or hashlib.sha256(
        activation_bytes
    ).hexdigest() != identity.get("activation_sha256"):
        raise ValueError("immutable independent activation binding differs")
    custody = GitCustody(
        Path(config["custody_cache"]),
        remote=config["custody_remote"],
        branch=config["custody_branch"],
        identity=identity,
        owner_id=uuid.uuid4().hex,
    )
    owner = TrialOwner(
        root, identity=identity, custody=custody, journal_factory=JournalSet, clock=wall_ms
    )
    obj, journal = owner.trial, owner.journal
    if not isinstance(journal, JournalSet):
        raise ValueError("original wire/source journal required")
    source = VolatilitySource(journal.append)
    source.restore(journal.records(), allow_adverse_clocks=True)
    service = VolatilityService(
        obj, clock=wall_ms, unclean_recovery=owner.unclean_recovery, fence=owner.lease_valid
    )
    if source.rejections:
        owner.disable("ORIGINAL_ADVERSE_SOURCE_UNQUALIFIED")
        service.custody_complete = False
    # Every process outage is visible; a held-data gap cannot be repaired using
    # subsequent prices or an old checkpoint labeled current.
    held_at_restart = bool(obj.candidate.account.positions)
    source.gap("owner_start_or_restart", now_ms=wall_ms())
    if held_at_restart:
        owner.disable("HELD_POSITION_RESTART_GAP_UNQUALIFIED")
        service.custody_complete = False
    settings_budget = ServiceBudget()
    transport = VolatilityTransport(
        archive_ingress=journal.ingress.append,
        clock=wall_ms,
        budget=settings_budget,
        request_priority=lambda priority: setattr(settings_budget, "priority", priority),
        funding_requests=lambda: funding_requests(obj),
    )
    queue: asyncio.Queue[tuple[str, object, int, int | None, MarketId | None]] = asyncio.Queue(2048)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    reader: asyncio.Task[None] | None = None
    publication: asyncio.Task[Any] | None = None
    clean_shutdown = False
    custody_degraded = False
    last_checkpoint = wall_ms()
    try:
        # The independently retained dirty-tail obligation precedes source use.
        initial = owner.prepare_checkpoint()
        await asyncio.to_thread(owner.publish_checkpoint, initial)
        reader = asyncio.create_task(
            transport.run(queue, stop, lambda: required_markets(obj, wall_ms()))
        )
        while not stop.is_set():
            if publication is not None and publication.done():
                try:
                    publication.result()
                except Exception:
                    owner.disable("INDEPENDENT_CUSTODY_FAILED_UNQUALIFIED")
                    service.custody_complete = False
                    custody_degraded = True
                    last_checkpoint = wall_ms() - 30_000
                publication = None
            if reader.done():
                reader.result()
                raise RuntimeError("public source owner stopped")
            now = wall_ms()
            if not owner.lease_valid(now):
                # No duplicate unfenced account executor may continue after TTL.
                owner.disable("INDEPENDENT_OWNER_FENCE_EXPIRED")
                raise RuntimeError("owner fence expired; durable obligations retained for recovery")
            service.refresh_entry_authority(
                receipt, source_valid=(owner.entries_allowed and not source.rejections)
            )
            epoch = now - now % DAY_MS + 30_000
            if epoch - 5 <= now and obj.snapshot()["last_decision_ms"] < epoch:
                # Snapshot original pre-cutoff caches before yielding to the
                # final timer. Actual invocation clock is never set backward.
                rows = source.daily_windows(epoch, eligibility=ordinary_eligibility(source, epoch))
                instruments, books = source.instruments(), source.books
                obj.set_source_valid(not source.rejections, now_ms=now)
                while wall_ms() < epoch:
                    await asyncio.sleep(0)
                actual = wall_ms()
                if not owner.lease_valid(actual):
                    raise RuntimeError("owner fence expired at daily boundary")
                # A newer original receipt pending at cutoff must be consumed
                # before a decision. The next actual late call records UNKNOWN;
                # no synthetic epoch or stale predecision E is substituted.
                if queue.empty():
                    obj.evaluate(rows, instruments, books, now_ms=actual)
                journal.ingress.append(
                    {
                        "kind": "daily_clock",
                        "epoch_ms": epoch,
                        "received_at_ms": actual,
                        "late": actual != epoch,
                    }
                )
            try:
                kind, raw, received, started, market = await asyncio.wait_for(queue.get(), 0.05)
                events: tuple[StreamEvent, ...] = ()
                if kind == "ws":
                    events = source.ingest_ws(raw, received_at_ms=received)
                elif kind == "meta":
                    events = source.ingest_meta(
                        raw, received_at_ms=received, request_started_ms=started
                    )
                elif kind == "candles" and market is not None:
                    source.ingest_candles(
                        market, raw, received_at_ms=received, request_started_ms=started
                    )
                elif kind == "funding" and market is not None:
                    source.ingest_funding(
                        market, raw, received_at_ms=received, request_started_ms=started
                    )
                elif kind == "gap":
                    source.gap(str(raw), now_ms=received)
                    material = bool(obj.candidate.account.positions)
                    obj.record_source_fault(str(raw), permanent=material, now_ms=wall_ms())
                    if material:
                        service.custody_complete = False
                for event in events:
                    if event.kind is StreamKind.ACTIVE_ASSET_CTX:
                        service.on_mark(event)
                    elif event.kind is StreamKind.L2_BOOK:
                        instrument = source.instruments().get(event.market)
                        if instrument is not None:
                            service.on_book(event, instrument)
                service.funding(source)
            except TimeoutError:
                pass
            except (ValueError, RuntimeError) as error:
                obj.record_source_fault(type(error).__name__, permanent=True, now_ms=wall_ms())
                service.custody_complete = False
            service.tick()
            now = wall_ms()
            if publication is None and now - last_checkpoint >= 30_000:
                try:
                    if custody_degraded:
                        publication = asyncio.create_task(asyncio.to_thread(owner.renew_fence_only))
                    else:
                        prepared = owner.prepare_checkpoint()
                        publication = asyncio.create_task(
                            asyncio.to_thread(owner.publish_checkpoint, prepared)
                        )
                except Exception:
                    owner.disable("CUSTODY_CAPACITY_OR_CAPTURE_FAILED_UNQUALIFIED")
                    service.custody_complete = False
                    custody_degraded = True
                    publication = asyncio.create_task(asyncio.to_thread(owner.renew_fence_only))
                last_checkpoint = now
            current = obj.snapshot()
            keys = (
                "candidate_equity",
                "candidate_cash",
                "gross",
                "fees",
                "funding",
                "unrealized",
                "control_equity",
                "open_positions",
                "components",
            )
            ack = owner.receipt.summary
            matched = all(current[key] == ack.get(key) for key in keys)
            status = {
                **current,
                "latest_account_verified": (
                    service.custody_complete and matched and owner.receipt.pending is None
                ),
                "independent_ack_commit": owner.receipt.commit,
                "independent_ack_time_ms": owner.receipt.time_ms,
                "unacknowledged_tail_present": owner.receipt.pending is not None,
                "rest_budget": settings_budget.ledger.snapshot(),
                "execution_mode": "paper",
            }
            temporary = root / "status.json.tmp"
            temporary.write_bytes(_json(status))
            os.replace(temporary, root / "status.json")
        clean_shutdown = queue.empty() and not custody_degraded
    finally:
        obj.entries_authorized = False
        stop.set()
        if reader is not None:
            reader.cancel()
            await asyncio.gather(reader, return_exceptions=True)
        if publication is not None:
            try:
                await publication
            except Exception:
                clean_shutdown = False
        # Owner closes the library BEFORE final snapshot, and holds the outer
        # service lock throughout. Failed final custody remains visibly pending.
        owner.close(clean=clean_shutdown and queue.empty())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--prepare", action="store_true")
    modes.add_argument("--check", action="store_true")
    modes.add_argument("--render-launch-agent", type=Path)
    args = parser.parse_args()
    try:
        config = json.loads(args.config.read_text())
        if args.render_launch_agent is not None:
            args.render_launch_agent.write_bytes(
                launch_agent(
                    Path(sys.executable), args.config.resolve(), code_root=Path(config["code_root"])
                )
            )
        elif args.check:
            validate_admission(config["activation"], now_ms=wall_ms())
            verify_deployed_code(Path(config["code_root"]), config["activation"]["code_sha"])
            verify_egress(config["activation"]["network"]["public_ip"])
        elif args.prepare:
            prepare(config)
        else:
            asyncio.run(run(config))
    except (ValueError, RuntimeError, KeyError, OSError) as error:
        print(json.dumps({"status": "BLOCKED", "reason": str(error), "entries_enabled": False}))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
