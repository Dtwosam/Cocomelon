from decimal import Decimal

import pytest

from cocomelon.domain.execution import PaperExecutionConfig
from cocomelon.domain.replay import EvidenceClass, SourceSegment
from cocomelon.replay.manifest import build_replay_manifest


def segment(name: str, digest: str) -> SourceSegment:
    return SourceSegment(
        relative_path=f"events/{name}.jsonl",
        partition="events/2026-08-23/candle/SOL",
        sha256=digest,
        byte_count=10,
        row_count=1,
        schema_version=1,
        first_available_at_ms=1_000,
        last_available_at_ms=2_000,
    )


def build(*, config: dict[str, object], code_revision: str = "abc123"):
    return build_replay_manifest(
        (segment("b", "b" * 64), segment("a", "a" * 64)),
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        start_ms=1_000,
        end_ms=2_000,
        code_revision=code_revision,
        config_snapshot=config,
        feature_version="phase4-v1",
        strategy_version="phase5-v1",
        risk_version="phase6-v1",
        execution_config=PaperExecutionConfig(),
    )


def test_same_semantic_config_has_same_manifest_id_independent_of_key_order() -> None:
    first = build(config={"risk": {"pct": Decimal("0.0025"), "enabled": True}, "mode": "paper"})
    second = build(config={"mode": "paper", "risk": {"enabled": True, "pct": Decimal("0.0025")}})

    assert first.manifest_id == second.manifest_id
    assert first.segments[0].relative_path.endswith("a.jsonl")


def test_manifest_id_changes_when_code_or_config_changes() -> None:
    base = build(config={"mode": "paper"})
    changed_code = build(config={"mode": "paper"}, code_revision="def456")
    changed_config = build(config={"mode": "paper", "latency_ms": 251})

    assert base.manifest_id != changed_code.manifest_id
    assert base.manifest_id != changed_config.manifest_id


def test_microstructure_manifest_requires_execution_configuration() -> None:
    with pytest.raises(ValueError, match="execution_config"):
        build_replay_manifest(
            (segment("a", "a" * 64),),
            evidence_class=EvidenceClass.MICROSTRUCTURE,
            start_ms=1_000,
            end_ms=2_000,
            code_revision="abc123",
            config_snapshot={"mode": "paper"},
            feature_version="phase4-v1",
            strategy_version="phase5-v1",
            risk_version="phase6-v1",
            execution_config=None,
        )


def test_candle_context_manifest_does_not_claim_execution_config() -> None:
    result = build_replay_manifest(
        (segment("a", "a" * 64),),
        evidence_class=EvidenceClass.CANDLE_CONTEXT,
        start_ms=1_000,
        end_ms=2_000,
        code_revision="abc123",
        config_snapshot={"mode": "paper"},
        feature_version="phase4-v1",
        strategy_version="phase5-v1",
        risk_version="phase6-v1",
        execution_config=None,
    )

    assert result.execution_config_version is None
    assert result.fee_schedule_id is None
