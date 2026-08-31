from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from cocomelon.domain.evaluation import TradeEvaluationSample
from cocomelon.domain.features import TrendRegime, VolatilityRegime
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import EvidenceClass
from cocomelon.domain.strategy import Direction
from cocomelon.research.contracts import (
    ResearchCandidateManifest,
    ResearchCandidateState,
    TimeInterval,
)
from cocomelon.research.evaluator import ResearchBatch, evaluate_research_checkpoint
from cocomelon.research.registry import ResearchRegistry, ResearchRegistryError


def _emit(payload: dict[str, object], *, stream: Any = sys.stdout) -> None:
    print(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ),
        file=stream,
    )


def _mapping(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError(f"{field} must be an object")
    return value


def _array(value: object, field: str) -> list[object]:
    if not isinstance(value, list):
        raise ValueError(f"{field} must be an array")
    return value


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be an integer")
    return value


def _decimal(value: object, field: str) -> Decimal:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a decimal string")
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"{field} must be a decimal string") from exc
    if not result.is_finite():
        raise ValueError(f"{field} must be finite")
    return result


def _string_tuple(value: object, field: str) -> tuple[str, ...]:
    values = _array(value, field)
    if not all(isinstance(item, str) and item.strip() for item in values):
        raise ValueError(f"{field} must contain non-empty strings")
    return tuple(values)


def _market(value: object) -> MarketId:
    canonical = _string(value, "market")
    if ":" not in canonical:
        return MarketId.from_wire_name("", canonical)
    dex = canonical.split(":", 1)[0]
    return MarketId.from_wire_name(dex, canonical)


def _research_batch(value: object) -> ResearchBatch:
    payload = _mapping(value, "batch")
    return ResearchBatch(
        batch_id=_string(payload.get("batch_id"), "batch_id"),
        source_id=_string(payload.get("source_id"), "source_id"),
        replay_run_id=_string(payload.get("replay_run_id"), "replay_run_id"),
        interval=TimeInterval(
            _integer(payload.get("start_ms"), "start_ms"),
            _integer(payload.get("end_ms"), "end_ms"),
        ),
    )


def _trade_sample(value: object) -> TradeEvaluationSample:
    payload = _mapping(value, "sample")
    try:
        return TradeEvaluationSample(
            trade_id=_string(payload.get("trade_id"), "trade_id"),
            replay_run_id=_string(payload.get("replay_run_id"), "replay_run_id"),
            strategy_decision_id=_string(
                payload.get("strategy_decision_id"),
                "strategy_decision_id",
            ),
            market=_market(payload.get("market")),
            direction=Direction(_string(payload.get("direction"), "direction")),
            decision_timestamp_ms=_integer(
                payload.get("decision_timestamp_ms"),
                "decision_timestamp_ms",
            ),
            opened_at_ms=_integer(payload.get("opened_at_ms"), "opened_at_ms"),
            closed_at_ms=_integer(payload.get("closed_at_ms"), "closed_at_ms"),
            score=_decimal(payload.get("score"), "score"),
            lead_strategy=_string(payload.get("lead_strategy"), "lead_strategy"),
            trend_regime=TrendRegime(
                _string(payload.get("trend_regime"), "trend_regime")
            ),
            volatility_regime=VolatilityRegime(
                _string(payload.get("volatility_regime"), "volatility_regime")
            ),
            evidence_class=EvidenceClass(
                _string(payload.get("evidence_class"), "evidence_class")
            ),
            gross_realized_pnl=_decimal(
                payload.get("gross_realized_pnl"),
                "gross_realized_pnl",
            ),
            entry_fees=_decimal(payload.get("entry_fees"), "entry_fees"),
            exit_fees=_decimal(payload.get("exit_fees"), "exit_fees"),
            funding_cash_pnl=_decimal(
                payload.get("funding_cash_pnl"),
                "funding_cash_pnl",
            ),
            net_pnl=_decimal(payload.get("net_pnl"), "net_pnl"),
            entry_slippage_amount=_decimal(
                payload.get("entry_slippage_amount"),
                "entry_slippage_amount",
            ),
            exit_slippage_amount=_decimal(
                payload.get("exit_slippage_amount"),
                "exit_slippage_amount",
            ),
            net_r=_decimal(payload.get("net_r"), "net_r"),
            equity_before=_decimal(payload.get("equity_before"), "equity_before"),
            equity_after=_decimal(payload.get("equity_after"), "equity_after"),
            holding_duration_ms=_integer(
                payload.get("holding_duration_ms"),
                "holding_duration_ms",
            ),
            reason_codes=_string_tuple(payload.get("reason_codes"), "reason_codes"),
            schema_version=_integer(payload.get("schema_version", 1), "schema_version"),
        )
    except ValueError as exc:
        raise ValueError(f"invalid research trade sample: {exc}") from exc


def _add_registry_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--registry", required=True, type=Path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cocomelon-research",
        description="Isolated touched-data research control surface",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init-registry")
    _add_registry_argument(init_parser)

    v4_parser = subparsers.add_parser("register-v4-interval")
    _add_registry_argument(v4_parser)
    v4_parser.add_argument("--run-id", required=True)
    v4_parser.add_argument("--start-ms", required=True, type=int)
    v4_parser.add_argument("--end-ms", required=True, type=int)
    v4_parser.add_argument("--disposition", required=True)

    candidate_parser = subparsers.add_parser("create-candidate")
    _add_registry_argument(candidate_parser)
    candidate_parser.add_argument("--candidate-id", required=True)
    candidate_parser.add_argument("--family-id", required=True)
    candidate_parser.add_argument("--parent-candidate-id")
    candidate_parser.add_argument("--config-digest", required=True)
    candidate_parser.add_argument("--code-revision", required=True)

    batch_parser = subparsers.add_parser("record-batch")
    _add_registry_argument(batch_parser)
    batch_parser.add_argument("--candidate-id", required=True)
    batch_parser.add_argument("--batch-id", required=True)
    batch_parser.add_argument("--source-id", required=True)
    batch_parser.add_argument("--replay-run-id", required=True)
    batch_parser.add_argument("--start-ms", required=True, type=int)
    batch_parser.add_argument("--end-ms", required=True, type=int)

    checkpoint_parser = subparsers.add_parser("checkpoint")
    _add_registry_argument(checkpoint_parser)
    checkpoint_parser.add_argument("--candidate-id", required=True)
    checkpoint_parser.add_argument("--dataset", required=True, type=Path)

    freeze_parser = subparsers.add_parser("freeze-candidate")
    _add_registry_argument(freeze_parser)
    freeze_parser.add_argument("--candidate-id", required=True)
    freeze_parser.add_argument("--freeze-ms", required=True, type=int)

    cutover_parser = subparsers.add_parser("validate-cutover")
    _add_registry_argument(cutover_parser)
    cutover_parser.add_argument("--candidate-id", required=True)
    cutover_parser.add_argument("--validation-start-ms", required=True, type=int)

    return parser


def _create_candidate(registry: ResearchRegistry, args: argparse.Namespace) -> dict[str, object]:
    parent_id = args.parent_candidate_id
    ancestors: tuple[str, ...] = ()
    if parent_id is not None:
        parent = registry.load_candidate(parent_id)
        ancestors = parent.ancestor_candidate_ids + (parent.candidate_id,)
    manifest = ResearchCandidateManifest(
        candidate_id=args.candidate_id,
        family_id=args.family_id,
        parent_candidate_id=parent_id,
        ancestor_candidate_ids=ancestors,
        config_digest=args.config_digest,
        code_revision=args.code_revision,
        state=ResearchCandidateState.DRAFT,
    )
    registry.create_candidate(manifest)
    return {
        "candidate_id": manifest.candidate_id,
        "command": "create-candidate",
        "family_id": manifest.family_id,
        "state": manifest.state.value,
    }


def _load_checkpoint_dataset(path: Path) -> tuple[tuple[ResearchBatch, ...], tuple[TradeEvaluationSample, ...]]:
    payload = _mapping(json.loads(path.read_text(encoding="utf-8")), "dataset")
    batches = tuple(_research_batch(item) for item in _array(payload.get("batches"), "batches"))
    samples = tuple(_trade_sample(item) for item in _array(payload.get("samples"), "samples"))
    return batches, samples


def _execute(args: argparse.Namespace) -> dict[str, object]:
    registry = ResearchRegistry(args.registry)
    try:
        if args.command == "init-registry":
            return {"command": "init-registry", "registry": str(args.registry)}
        if args.command == "register-v4-interval":
            interval = TimeInterval(args.start_ms, args.end_ms)
            registry.record_v4_interval(
                run_id=args.run_id,
                interval=interval,
                disposition=args.disposition,
            )
            return {
                "command": "register-v4-interval",
                "disposition": args.disposition,
                "end_ms": interval.end_ms,
                "run_id": args.run_id,
                "start_ms": interval.start_ms,
            }
        if args.command == "create-candidate":
            return _create_candidate(registry, args)
        if args.command == "record-batch":
            interval = TimeInterval(args.start_ms, args.end_ms)
            registry.record_batch(
                candidate_id=args.candidate_id,
                batch_id=args.batch_id,
                source_id=args.source_id,
                replay_run_id=args.replay_run_id,
                interval=interval,
            )
            return {
                "batch_id": args.batch_id,
                "candidate_id": args.candidate_id,
                "command": "record-batch",
                "end_ms": interval.end_ms,
                "replay_run_id": args.replay_run_id,
                "source_id": args.source_id,
                "start_ms": interval.start_ms,
            }
        if args.command == "checkpoint":
            batches, samples = _load_checkpoint_dataset(args.dataset)
            for batch in batches:
                registry.record_batch(
                    candidate_id=args.candidate_id,
                    batch_id=batch.batch_id,
                    source_id=batch.source_id,
                    replay_run_id=batch.replay_run_id,
                    interval=batch.interval,
                )
            return evaluate_research_checkpoint(
                registry=registry,
                candidate_id=args.candidate_id,
                batches=batches,
                samples=samples,
            ).to_dict()
        if args.command == "freeze-candidate":
            registry.freeze_candidate(args.candidate_id, freeze_ms=args.freeze_ms)
            candidate = registry.load_candidate(args.candidate_id)
            return {
                "candidate_id": args.candidate_id,
                "command": "freeze-candidate",
                "freeze_ms": args.freeze_ms,
                "state": candidate.state.value,
            }
        if args.command == "validate-cutover":
            registry.assert_validation_cutover(
                args.candidate_id,
                validation_start_ms=args.validation_start_ms,
            )
            return {
                "allowed": True,
                "candidate_id": args.candidate_id,
                "command": "validate-cutover",
                "validation_start_ms": args.validation_start_ms,
            }
        raise ResearchRegistryError(f"unknown research command: {args.command}")
    finally:
        registry.close()


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        payload = _execute(args)
    except (OSError, ValueError, ResearchRegistryError, json.JSONDecodeError) as exc:
        _emit(
            {"error": str(exc), "error_type": type(exc).__name__},
            stream=sys.stderr,
        )
        return 2
    _emit(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
