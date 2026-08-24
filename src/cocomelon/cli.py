from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sqlite3
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from cocomelon.config import ExecutionMode, Settings
from cocomelon.domain.features import (
    EligibilityDecision,
    FeatureSnapshot,
    OpportunityRank,
)
from cocomelon.domain.market import MarketId, PerpMarketSnapshot
from cocomelon.domain.replay import EvidenceClass, ReplayManifest, SourceRecordKind, SourceSegment
from cocomelon.domain.stream import DataGap, StreamEvent
from cocomelon.evaluation.cli_support import (
    evaluation_result_payload,
    freeze_evaluation_dataset_payload,
    freeze_evaluation_splits_payload,
    inspect_evaluation_payload,
    run_evaluation,
)
from cocomelon.evidence.cli_support import record_mainnet_evidence_payload
from cocomelon.features.assemble import assemble_feature_snapshot
from cocomelon.features.broad import calculate_broad_features
from cocomelon.hyperliquid.client import InfoClient
from cocomelon.hyperliquid.registry import (
    InfoReader,
    MarketRegistry,
    MarketRegistrySnapshot,
)
from cocomelon.hyperliquid.watchlist import DeepWatchlistManager
from cocomelon.hyperliquid.ws_client import WsConnection, connect_mainnet_ws
from cocomelon.hyperliquid.ws_supervisor import WebSocketSupervisor
from cocomelon.journal.store import JournalStore
from cocomelon.replay.clock import canonical_record_order
from cocomelon.replay.compaction import compact_recording
from cocomelon.replay.source import JsonlReplaySource, validate_recording
from cocomelon.scanner.eligibility import (
    EligibilityConfig,
    derive_eligibility_thresholds,
    evaluate_eligibility,
)
from cocomelon.scanner.ranker import rank_opportunities
from cocomelon.util.time import utc_now_ms

DEFAULT_SCAN_LIMIT = 20
MAX_SCAN_LIMIT = 100
DEFAULT_SMOKE_MARKETS = ("BTC",)
DEFAULT_SMOKE_SECONDS = 5.0
MAX_SMOKE_SECONDS = 30.0
MAX_SMOKE_MARKETS = 20

SmokeResult = dict[str, object]
SmokeRunner = Callable[[Settings, float, tuple[str, ...]], SmokeResult]


@dataclass(frozen=True, slots=True)
class BroadScanResult:
    features: tuple[FeatureSnapshot, ...]
    decisions: tuple[EligibilityDecision, ...]
    ranks: tuple[OpportunityRank, ...]


class RegistryReader(Protocol):
    def refresh(self) -> MarketRegistrySnapshot: ...


class BroadScanRunner(Protocol):
    def __call__(
        self,
        markets: Mapping[str, PerpMarketSnapshot],
        *,
        as_of_ms: int,
    ) -> BroadScanResult: ...


def status_payload(settings: Settings) -> dict[str, Any]:
    return {
        "execution_mode": settings.execution_mode.value,
        "api_url": settings.api_url,
        "ws_url": settings.ws_url,
        "live_activation_valid": settings.live_activation_valid,
        "risk_per_trade": float(settings.risk_per_trade),
        "max_open_risk": float(settings.max_open_risk),
        "daily_loss_limit": float(settings.daily_loss_limit),
        "weekly_drawdown_limit": float(settings.weekly_drawdown_limit),
    }


def markets_payload(
    settings: Settings,
    *,
    client: InfoReader | None = None,
) -> dict[str, Any]:
    reader = client or InfoClient(settings)
    snapshot = MarketRegistry(reader).refresh()
    market_names = list(snapshot.markets)
    delisted_count = sum(1 for item in snapshot.markets.values() if item.meta.is_delisted)
    return {
        "execution_mode": settings.execution_mode.value,
        "api_url": settings.api_url,
        "live_activation_valid": settings.live_activation_valid,
        "perp_dex_count": 1 + len(snapshot.dexs),
        "hip3_dex_count": len(snapshot.dexs),
        "market_count": len(snapshot.markets),
        "active_market_count": len(snapshot.markets) - delisted_count,
        "delisted_market_count": delisted_count,
        "sample_markets": market_names[:20],
    }


def run_broad_scan(
    markets: Mapping[str, PerpMarketSnapshot],
    *,
    as_of_ms: int,
) -> BroadScanResult:
    current_by_market: dict[str, PerpMarketSnapshot] = {}
    features: list[FeatureSnapshot] = []

    for current in sorted(
        markets.values(),
        key=lambda item: item.meta.market.canonical,
    ):
        market = current.meta.market
        key = market.canonical
        if key in current_by_market:
            raise ValueError(f"duplicate current market snapshot: {key}")
        if current.context.market != market or current.received_at_ms > as_of_ms:
            continue

        current_by_market[key] = current
        broad = calculate_broad_features(current, None, as_of_ms=as_of_ms)
        features.append(
            assemble_feature_snapshot(
                market,
                broad,
                as_of_ms=as_of_ms,
                provenance=(current.source,),
            )
        )

    feature_tuple = tuple(features)
    if not feature_tuple:
        return BroadScanResult(features=(), decisions=(), ranks=())

    config = EligibilityConfig()
    thresholds = derive_eligibility_thresholds(feature_tuple, config)
    decisions = tuple(
        evaluate_eligibility(
            current_by_market[feature.market.canonical],
            feature,
            thresholds,
            config,
        )
        for feature in feature_tuple
    )
    ranks = rank_opportunities(feature_tuple, decisions, mode="coarse")
    return BroadScanResult(
        features=feature_tuple,
        decisions=decisions,
        ranks=ranks,
    )


def scan_once_payload(
    settings: Settings,
    *,
    limit: int = DEFAULT_SCAN_LIMIT,
    registry: RegistryReader | None = None,
    scanner: BroadScanRunner = run_broad_scan,
) -> dict[str, object]:
    if limit <= 0 or limit > MAX_SCAN_LIMIT:
        raise ValueError(f"limit must be between 1 and {MAX_SCAN_LIMIT}")

    registry_reader = registry or MarketRegistry(InfoClient(settings))
    registry_snapshot = registry_reader.refresh()
    scan = scanner(
        registry_snapshot.markets,
        as_of_ms=registry_snapshot.received_at_ms,
    )

    features = {item.market.canonical: item for item in scan.features}
    decisions = {item.market.canonical: item for item in scan.decisions}
    results: list[dict[str, object]] = []
    for rank in scan.ranks[:limit]:
        key = rank.market.canonical
        feature = features[key]
        decision = decisions[key]
        results.append(
            {
                "market": key,
                "ordinal": rank.ordinal,
                "score": float(rank.score),
                "reasons": list(decision.reasons),
                "feature_snapshot_id": feature.snapshot_id,
            }
        )

    rankable_count = sum(1 for item in scan.decisions if item.rankable)
    return {
        "execution_mode": settings.execution_mode.value,
        "api_url": settings.api_url,
        "market_count": len(registry_snapshot.markets),
        "feature_count": len(scan.features),
        "rankable_count": rankable_count,
        "rejected_count": len(scan.decisions) - rankable_count,
        "skipped_count": len(registry_snapshot.markets) - len(scan.features),
        "result_limit": limit,
        "results": results,
    }


def _market_id(value: str) -> MarketId:
    name = value.strip()
    if not name:
        raise ValueError("market must not be empty")
    if ":" in name:
        dex = name.split(":", 1)[0]
        return MarketId.from_wire_name(dex, name)
    return MarketId.from_wire_name("", name)


async def _stream_smoke_async(
    settings: Settings,
    seconds: float,
    markets: tuple[str, ...],
) -> SmokeResult:
    market_ids = tuple(_market_id(item) for item in markets)
    broad_dexes = tuple(sorted({item.dex for item in market_ids if item.dex}))
    plan = DeepWatchlistManager(broad_dexes=broad_dexes).reconcile(market_ids)

    event_count = 0
    gap_count = 0

    async def event_sink(_: StreamEvent) -> None:
        nonlocal event_count
        event_count += 1

    async def gap_sink(_: DataGap) -> None:
        nonlocal gap_count
        gap_count += 1

    async def connection_factory() -> WsConnection:
        return await connect_mainnet_ws(settings)

    supervisor = WebSocketSupervisor(
        connection_factory,
        plan.subscribe,
        event_sink=event_sink,
        gap_sink=gap_sink,
        clock_ms=utc_now_ms,
        utcnow=lambda: datetime.now(UTC),
    )

    try:
        await asyncio.wait_for(supervisor.run(), timeout=seconds)
    except TimeoutError:
        pass

    health = supervisor.health
    if event_count == 0:
        raise RuntimeError("stream smoke observed no market events")

    now_ms = utc_now_ms()
    return {
        "event_count": event_count,
        "gap_count": gap_count,
        "observed_server_message": health.last_server_message_ms is not None,
        "reconnect_count": health.reconnect_count,
        "duplicate_count": health.duplicate_count,
        "anomaly_count": health.anomaly_count,
        "stale_streams": list(supervisor.stale_streams(now_ms=now_ms)),
        "subscription_count": plan.desired_count,
    }


def run_stream_smoke(
    settings: Settings,
    seconds: float,
    markets: tuple[str, ...],
) -> SmokeResult:
    return asyncio.run(_stream_smoke_async(settings, seconds, markets))


def stream_smoke_payload(
    settings: Settings,
    *,
    seconds: float = DEFAULT_SMOKE_SECONDS,
    markets: tuple[str, ...] = DEFAULT_SMOKE_MARKETS,
    runner: SmokeRunner = run_stream_smoke,
) -> dict[str, object]:
    if settings.execution_mode is not ExecutionMode.PAPER:
        raise ValueError("stream-smoke is available only in paper mode")
    if seconds <= 0 or seconds > MAX_SMOKE_SECONDS:
        raise ValueError(f"seconds must be > 0 and <= {MAX_SMOKE_SECONDS:g}")
    if not markets:
        raise ValueError("at least one market is required")
    if len(markets) > MAX_SMOKE_MARKETS:
        raise ValueError(f"stream-smoke accepts at most {MAX_SMOKE_MARKETS} markets")

    normalized_markets = tuple(_market_id(item).canonical for item in markets)
    result = runner(settings, seconds, normalized_markets)
    return {
        "execution_mode": settings.execution_mode.value,
        "ws_url": settings.ws_url,
        "seconds": seconds,
        "markets": list(normalized_markets),
        **result,
    }


def _source_set_sha256(segments: Sequence[SourceSegment]) -> str:
    payload = [item.canonical_payload() for item in segments]
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_recording_payload(root: str | Path) -> dict[str, object]:
    source_root = Path(root)
    segments = validate_recording(source_root)
    return {
        "root": str(source_root),
        "segment_count": len(segments),
        "row_count": sum(item.row_count for item in segments),
        "byte_count": sum(item.byte_count for item in segments),
        "source_set_sha256": _source_set_sha256(segments),
        "segments": [item.canonical_payload() for item in segments],
    }


def compact_recording_payload(
    root: str | Path,
    out: str | Path,
) -> dict[str, object]:
    source_root = Path(root)
    segments = validate_recording(source_root)
    result = compact_recording(source_root, Path(out), segments)
    return {
        "dataset_id": result.dataset_id,
        "dataset_root": str(result.dataset_root),
        "evidence_class": result.evidence_class.value,
        "row_count": result.row_count,
        "logical_sha256": result.logical_sha256,
        "source_set_sha256": _source_set_sha256(result.source_segments),
        "outputs": [item.canonical_payload() for item in result.output_files],
    }


def _require_mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object")
    return value


def _require_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value


def _optional_string(value: object, field: str) -> str | None:
    if value is None:
        return None
    return _require_string(value, field)


def _require_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be an integer")
    return value


def _string_tuple(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{field} must be a string array")
    return tuple(value)


def _source_segment(value: object) -> SourceSegment:
    item = _require_mapping(value, "source segment")
    return SourceSegment(
        relative_path=_require_string(item.get("relative_path"), "relative_path"),
        partition=_require_string(item.get("partition"), "partition"),
        sha256=_require_string(item.get("sha256"), "sha256"),
        byte_count=_require_int(item.get("byte_count"), "byte_count"),
        row_count=_require_int(item.get("row_count"), "row_count"),
        schema_version=_require_int(item.get("schema_version"), "schema_version"),
        first_available_at_ms=_require_int(
            item.get("first_available_at_ms"), "first_available_at_ms"
        ),
        last_available_at_ms=_require_int(
            item.get("last_available_at_ms"), "last_available_at_ms"
        ),
    )


def _load_replay_manifest(path: str | Path) -> ReplayManifest:
    manifest_path = Path(path)
    if not manifest_path.is_file():
        raise ValueError("replay manifest must be an existing file")
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("replay manifest must contain valid JSON") from exc
    item = _require_mapping(raw, "replay manifest")
    raw_segments = item.get("segments")
    if not isinstance(raw_segments, list):
        raise ValueError("segments must be an array")
    try:
        evidence_class = EvidenceClass(
            _require_string(item.get("evidence_class"), "evidence_class")
        )
    except ValueError as exc:
        raise ValueError("unsupported replay evidence_class") from exc
    return ReplayManifest(
        evidence_class=evidence_class,
        start_ms=_require_int(item.get("start_ms"), "start_ms"),
        end_ms=_require_int(item.get("end_ms"), "end_ms"),
        segments=tuple(_source_segment(segment) for segment in raw_segments),
        gap_refs=_string_tuple(item.get("gap_refs"), "gap_refs"),
        code_revision=_require_string(item.get("code_revision"), "code_revision"),
        config_digest=_require_string(item.get("config_digest"), "config_digest"),
        feature_version=_require_string(item.get("feature_version"), "feature_version"),
        strategy_version=_require_string(item.get("strategy_version"), "strategy_version"),
        risk_version=_require_string(item.get("risk_version"), "risk_version"),
        execution_config_version=_optional_string(
            item.get("execution_config_version"), "execution_config_version"
        ),
        fee_schedule_id=_optional_string(item.get("fee_schedule_id"), "fee_schedule_id"),
        replay_engine_version=_require_string(
            item.get("replay_engine_version"), "replay_engine_version"
        ),
        dataset_manifest_id=_optional_string(
            item.get("dataset_manifest_id"), "dataset_manifest_id"
        ),
        schema_version=_require_int(item.get("schema_version"), "schema_version"),
    )


def _record_digest(records: Sequence[object]) -> str:
    encoded = json.dumps(
        [repr(item) for item in records],
        sort_keys=False,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def replay_payload(
    manifest_path: str | Path,
    journal_path: str | Path,
) -> dict[str, object]:
    frozen_path = Path(manifest_path)
    manifest = _load_replay_manifest(frozen_path)
    source = JsonlReplaySource(frozen_path.parent)
    records = canonical_record_order(tuple(source.iter_records(manifest)))

    journal = JournalStore(journal_path)
    try:
        journal.record_manifest(manifest)
    finally:
        journal.close()

    return {
        "mode": "evidence_audit",
        "manifest_id": manifest.manifest_id,
        "evidence_class": manifest.evidence_class.value,
        "record_count": len(records),
        "data_gap_count": sum(
            record.record_kind is SourceRecordKind.DATA_GAP for record in records
        ),
        "record_digest": _record_digest(records),
        "journal": str(Path(journal_path)),
        "network_access": False,
    }


def inspect_journal_payload(
    journal_path: str | Path,
    trade_id: str,
) -> dict[str, object]:
    path = Path(journal_path)
    if not path.is_file():
        raise ValueError("journal must be an existing file")
    if not trade_id.strip():
        raise ValueError("trade_id must not be empty")
    connection = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    try:
        row = connection.execute(
            "SELECT payload_json FROM journal_trades WHERE trade_id = ?",
            (trade_id,),
        ).fetchone()
    except sqlite3.DatabaseError as exc:
        raise ValueError("journal is not a readable Phase 8 SQLite journal") from exc
    finally:
        connection.close()
    if row is None:
        raise ValueError(f"trade not found: {trade_id}")
    try:
        payload = json.loads(str(row[0]))
    except json.JSONDecodeError as exc:
        raise ValueError("stored trade payload is invalid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("stored trade payload must be an object")
    return {str(key): value for key, value in payload.items()}


def evaluate_payload(
    journal_path: str | Path,
    facts_path: str | Path,
    dataset_id: str,
    split_id: str,
    candidate_spec_path: str | Path,
    walkforward_spec_path: str | Path,
) -> dict[str, object]:
    result = run_evaluation(
        journal_path,
        facts_path,
        dataset_id,
        split_id,
        candidate_spec_path,
        walkforward_spec_path,
    )
    return evaluation_result_payload(result)


def _scan_limit(value: str) -> int:
    try:
        resolved = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("limit must be an integer") from exc
    if resolved <= 0 or resolved > MAX_SCAN_LIMIT:
        raise argparse.ArgumentTypeError(
            f"limit must be between 1 and {MAX_SCAN_LIMIT}"
        )
    return resolved


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cocomelon")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("status")
    subparsers.add_parser("markets")

    scan = subparsers.add_parser("scan-once")
    scan.add_argument("--limit", type=_scan_limit, default=DEFAULT_SCAN_LIMIT)

    smoke = subparsers.add_parser("stream-smoke")
    smoke.add_argument("--seconds", type=float, default=DEFAULT_SMOKE_SECONDS)
    smoke.add_argument("--market", action="append")

    record = subparsers.add_parser("record-mainnet-evidence")
    record.add_argument("--root", required=True, type=Path)
    record.add_argument("--seconds", required=True, type=int)
    record.add_argument("--deep-limit", type=int, default=20)

    validate = subparsers.add_parser("validate-recording")
    validate.add_argument("--root", required=True, type=Path)

    compact = subparsers.add_parser("compact-recording")
    compact.add_argument("--root", required=True, type=Path)
    compact.add_argument("--out", required=True, type=Path)

    replay = subparsers.add_parser("replay")
    replay.add_argument("--manifest", required=True, type=Path)
    replay.add_argument("--journal", required=True, type=Path)

    inspect = subparsers.add_parser("inspect-journal")
    inspect.add_argument("--journal", required=True, type=Path)
    inspect.add_argument("--trade-id", required=True)

    freeze_dataset = subparsers.add_parser("freeze-evaluation-dataset")
    freeze_dataset.add_argument("--journal", required=True, type=Path)
    freeze_dataset.add_argument("--facts", required=True, type=Path)
    freeze_dataset.add_argument("--run-id", required=True, action="append")

    freeze_splits = subparsers.add_parser("freeze-evaluation-splits")
    freeze_splits.add_argument("--facts", required=True, type=Path)
    freeze_splits.add_argument("--dataset-id", required=True)
    freeze_splits.add_argument("--spec", required=True, type=Path)

    evaluate = subparsers.add_parser("evaluate")
    evaluate.add_argument("--journal", required=True, type=Path)
    evaluate.add_argument("--facts", required=True, type=Path)
    evaluate.add_argument("--dataset-id", required=True)
    evaluate.add_argument("--split-id", required=True)
    evaluate.add_argument("--candidate-spec", required=True, type=Path)
    evaluate.add_argument("--walkforward-spec", required=True, type=Path)

    inspect_evaluation = subparsers.add_parser("inspect-evaluation")
    inspect_evaluation.add_argument("--facts", required=True, type=Path)
    inspect_evaluation.add_argument("--evaluation-id", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)

    if args.command == "validate-recording":
        payload: dict[str, object] = validate_recording_payload(args.root)
    elif args.command == "compact-recording":
        payload = compact_recording_payload(args.root, args.out)
    elif args.command == "replay":
        payload = replay_payload(args.manifest, args.journal)
    elif args.command == "inspect-journal":
        payload = inspect_journal_payload(args.journal, args.trade_id)
    elif args.command == "freeze-evaluation-dataset":
        payload = freeze_evaluation_dataset_payload(
            args.journal,
            args.facts,
            tuple(args.run_id),
        )
    elif args.command == "freeze-evaluation-splits":
        payload = freeze_evaluation_splits_payload(args.facts, args.dataset_id, args.spec)
    elif args.command == "evaluate":
        payload = evaluate_payload(
            args.journal,
            args.facts,
            args.dataset_id,
            args.split_id,
            args.candidate_spec,
            args.walkforward_spec,
        )
    elif args.command == "inspect-evaluation":
        payload = inspect_evaluation_payload(args.facts, args.evaluation_id)
    else:
        settings = Settings.from_env()
        if args.command == "status":
            payload = status_payload(settings)
        elif args.command == "markets":
            payload = markets_payload(settings)
        elif args.command == "scan-once":
            payload = scan_once_payload(settings, limit=args.limit)
        elif args.command == "record-mainnet-evidence":
            payload = record_mainnet_evidence_payload(
                settings,
                root=args.root,
                seconds=args.seconds,
                deep_limit=args.deep_limit,
            )
        else:
            markets = tuple(args.market) if args.market else DEFAULT_SMOKE_MARKETS
            payload = stream_smoke_payload(
                settings,
                seconds=args.seconds,
                markets=markets,
            )
    print(json.dumps(payload, indent=2, sort_keys=True))
