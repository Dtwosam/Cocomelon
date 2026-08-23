from cocomelon.domain.replay import (
    EvidenceClass,
    ReplayManifest,
    ReplayRecord,
    ReplayResult,
    SourceRecordKind,
    SourceSegment,
)


def source_segment(path: str, *, digest: str) -> SourceSegment:
    return SourceSegment(
        relative_path=path,
        partition="events/2026-08-23/l2_book/SOL",
        sha256=digest,
        byte_count=100,
        row_count=2,
        schema_version=1,
        first_available_at_ms=1_000,
        last_available_at_ms=2_000,
    )


def manifest(segments: tuple[SourceSegment, ...]) -> ReplayManifest:
    return ReplayManifest(
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        start_ms=1_000,
        end_ms=2_000,
        segments=segments,
        gap_refs=("gap-2", "gap-1", "gap-2"),
        code_revision="abc123",
        config_digest="c" * 64,
        feature_version="phase4-v1",
        strategy_version="phase5-v1",
        risk_version="phase6-v1",
        execution_config_version="phase7-v1",
        fee_schedule_id="fees-v1",
        replay_engine_version="phase8-v1",
        dataset_manifest_id=None,
    )


def test_manifest_source_order_is_canonical() -> None:
    a = source_segment("events/a.jsonl", digest="a" * 64)
    b = source_segment("events/b.jsonl", digest="b" * 64)

    first = manifest((b, a))
    second = manifest((a, b))

    assert first.segments == (a, b)
    assert first.gap_refs == ("gap-1", "gap-2")
    assert first.manifest_id == second.manifest_id


def test_manifest_id_changes_for_semantic_version_or_evidence_change() -> None:
    base = manifest((source_segment("events/a.jsonl", digest="a" * 64),))
    changed = ReplayManifest(
        evidence_class=EvidenceClass.CANDLE_CONTEXT,
        start_ms=base.start_ms,
        end_ms=base.end_ms,
        segments=base.segments,
        gap_refs=base.gap_refs,
        code_revision=base.code_revision,
        config_digest=base.config_digest,
        feature_version=base.feature_version,
        strategy_version=base.strategy_version,
        risk_version=base.risk_version,
        execution_config_version=None,
        fee_schedule_id=None,
        replay_engine_version=base.replay_engine_version,
        dataset_manifest_id=None,
    )

    assert base.manifest_id != changed.manifest_id


def test_source_segment_validates_sha_and_availability_bounds() -> None:
    try:
        source_segment("events/a.jsonl", digest="bad")
    except ValueError as exc:
        assert "sha256" in str(exc)
    else:
        raise AssertionError("invalid sha256 must reject")


def test_replay_record_uses_canonical_payload_json() -> None:
    record = ReplayRecord(
        record_kind=SourceRecordKind.NORMALIZED_EVENT,
        available_at_ms=1_500,
        source="hyperliquid-mainnet-ws",
        schema_version=1,
        market="SOL",
        exchange_time_ms=1_400,
        event_key="l2:SOL:1400",
        payload_json='{"asks":[],"bids":[]}',
    )

    assert record.payload == {"asks": [], "bids": []}
    assert record.sort_key[0] == 1_500


def test_replay_result_digest_is_deterministic_and_semantic() -> None:
    kwargs = dict(
        manifest_id="manifest-1",
        run_id="run-1",
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        start_ms=1_000,
        end_ms=2_000,
        processed_events=10,
        processed_gaps=1,
        strategy_decisions=2,
        risk_approvals=1,
        risk_rejections=1,
        execution_attempts=1,
        fills=2,
        opened_positions=1,
        closed_positions=1,
        journal_observations=8,
        closed_trade_ids=("trade-2", "trade-1"),
        final_account_state_id="account-final",
        data_complete=True,
    )
    first = ReplayResult(**kwargs)
    second = ReplayResult(**kwargs)

    assert first.closed_trade_ids == ("trade-1", "trade-2")
    assert first.result_digest == second.result_digest
    assert len(first.result_digest) == 64
