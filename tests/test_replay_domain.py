from datetime import UTC, datetime
from decimal import Decimal, getcontext

import pytest
from cocomelon.domain.replay import (
    EvidenceClass,
    InputArtifact,
    JournalRecord,
    JournalRecordType,
    ReplayManifest,
    canonical_json_bytes,
    sha256_hex,
)


def artifact(path: str, digest: str) -> InputArtifact:
    return InputArtifact(
        relative_path=path,
        sha256=digest,
        byte_size=123,
        partition_id="events/2026-08-23/l2_book/BTC",
    )


def test_evidence_classes_are_explicit_and_non_interchangeable() -> None:
    assert EvidenceClass.CANDLE_CONTEXT.value == "candle_context"
    assert EvidenceClass.MICROSTRUCTURE.value == "microstructure"
    assert tuple(item.value for item in EvidenceClass) == (
        "candle_context",
        "microstructure",
    )


def test_canonical_json_is_mapping_order_independent_and_decimal_exact() -> None:
    first = {"b": Decimal("1.2300"), "a": {"y": 2, "x": Decimal("0.10")}}
    second = {"a": {"x": Decimal("0.10"), "y": 2}, "b": Decimal("1.2300")}

    assert canonical_json_bytes(first) == canonical_json_bytes(second)
    assert canonical_json_bytes(first) == b'{"a":{"x":"0.10","y":2},"b":"1.2300"}'
    assert sha256_hex(first) == sha256_hex(second)


def test_hashing_is_independent_of_ambient_decimal_context() -> None:
    previous = getcontext().prec
    try:
        getcontext().prec = 6
        first = sha256_hex({"value": Decimal("123456789.123456789")})
        getcontext().prec = 50
        second = sha256_hex({"value": Decimal("123456789.123456789")})
    finally:
        getcontext().prec = previous

    assert first == second


def test_manifest_canonicalizes_input_order_for_replay_identity() -> None:
    a = artifact("events/a.jsonl", "a" * 64)
    b = artifact("events/b.jsonl", "b" * 64)

    first = ReplayManifest(
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        inputs=(b, a),
        start_receive_ms=1_000,
        end_receive_ms=2_000,
        code_version="abc123",
        config_version="phase8-test",
        strategy_version="phase5-v1",
        risk_version="phase6-v1",
        execution_version="phase7-v1",
        recorder_schema_versions=(1,),
    )
    second = ReplayManifest(
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        inputs=(a, b),
        start_receive_ms=1_000,
        end_receive_ms=2_000,
        code_version="abc123",
        config_version="phase8-test",
        strategy_version="phase5-v1",
        risk_version="phase6-v1",
        execution_version="phase7-v1",
        recorder_schema_versions=(1,),
    )

    assert tuple(item.relative_path for item in first.inputs) == (
        "events/a.jsonl",
        "events/b.jsonl",
    )
    assert first.replay_id == second.replay_id


def test_journal_id_ignores_recorded_at_but_captures_logical_content() -> None:
    base = dict(
        record_type=JournalRecordType.STRATEGY_DECISION,
        occurred_at_ms=1_000,
        market="BTC",
        code_version="abc123",
        config_version="phase8-test",
        payload={"direction": "NO_TRADE", "reason_codes": ["NO_EDGE"]},
        decision_id="decision-1",
    )
    early = JournalRecord(recorded_at_ms=1_010, **base)
    late = JournalRecord(recorded_at_ms=9_999, **base)
    changed = JournalRecord(
        recorded_at_ms=1_010,
        **{**base, "payload": {"direction": "LONG", "reason_codes": ["TREND"]}},
    )

    assert early.journal_id == late.journal_id
    assert early.journal_id != changed.journal_id


def test_canonical_serialization_rejects_nonfinite_decimal_and_naive_datetime() -> None:
    with pytest.raises(ValueError, match="finite"):
        canonical_json_bytes({"value": Decimal("NaN")})

    with pytest.raises(ValueError, match="timezone-aware"):
        canonical_json_bytes({"when": datetime(2026, 8, 23)})

    aware = canonical_json_bytes({"when": datetime(2026, 8, 23, tzinfo=UTC)})
    assert aware == b'{"when":"2026-08-23T00:00:00Z"}'


def test_replay_manifest_rejects_bad_bounds_hashes_and_paths() -> None:
    with pytest.raises(ValueError, match="end_receive_ms"):
        ReplayManifest(
            evidence_class=EvidenceClass.CANDLE_CONTEXT,
            inputs=(artifact("events/a.jsonl", "a" * 64),),
            start_receive_ms=2_000,
            end_receive_ms=1_000,
            code_version="abc",
            config_version="cfg",
            strategy_version="s",
            risk_version="r",
            execution_version="e",
            recorder_schema_versions=(1,),
        )

    with pytest.raises(ValueError, match="sha256"):
        artifact("events/a.jsonl", "not-a-hash")

    with pytest.raises(ValueError, match="relative"):
        artifact("/absolute/segment.jsonl", "a" * 64)
