from cocomelon.domain.journal import canonical_json
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import EvidenceClass, ReplayEvidence, SourceCoordinate
from cocomelon.replay.engine import EvidenceBoundaryError, ReplayEngine

MARKET = MarketId(dex="", coin="SOL")


def row(
    *,
    receive_time_ms: int,
    path: str,
    segment: int,
    line: int,
    kind: str = "trade",
    evidence_class: EvidenceClass = EvidenceClass.MICROSTRUCTURE,
    exchange_time_ms: int | None = None,
) -> ReplayEvidence:
    return ReplayEvidence(
        evidence_class=evidence_class,
        receive_time_ms=receive_time_ms,
        exchange_time_ms=exchange_time_ms,
        record_type="normalized_event",
        source="hyperliquid-mainnet-ws",
        coordinate=SourceCoordinate(path, segment, line),
        payload_json=canonical_json({"kind": kind, "line": line}),
        market=MARKET,
        event_kind=kind,
        event_key=f"{kind}:{line}",
    )


def test_replay_orders_by_receive_time_then_stable_source_coordinate() -> None:
    later_exchange_earlier_receive = row(
        receive_time_ms=1_000,
        exchange_time_ms=9_000,
        path="events/b/segment-000002.jsonl",
        segment=2,
        line=1,
    )
    earlier_exchange_later_receive = row(
        receive_time_ms=2_000,
        exchange_time_ms=100,
        path="events/a/segment-000001.jsonl",
        segment=1,
        line=1,
    )
    tied_b = row(
        receive_time_ms=3_000,
        path="events/b/segment-000001.jsonl",
        segment=1,
        line=1,
    )
    tied_a = row(
        receive_time_ms=3_000,
        path="events/a/segment-000002.jsonl",
        segment=2,
        line=2,
    )

    engine = ReplayEngine(
        EvidenceClass.MICROSTRUCTURE,
        [tied_b, earlier_exchange_later_receive, tied_a, later_exchange_earlier_receive],
    )

    assert engine.peek_time() == 1_000
    emitted = [engine.next_event() for _ in range(4)]
    assert emitted == [
        later_exchange_earlier_receive,
        earlier_exchange_later_receive,
        tied_a,
        tied_b,
    ]
    assert engine.current_receive_time_ms == 3_000
    assert engine.peek_time() is None
    assert engine.next_event() is None
    assert engine.completion_digest is not None


def test_replay_digest_is_identical_for_different_input_enumeration_order() -> None:
    rows = [
        row(receive_time_ms=2_000, path="events/b/segment-000001.jsonl", segment=1, line=2),
        row(receive_time_ms=1_000, path="events/a/segment-000001.jsonl", segment=1, line=1),
    ]
    first = ReplayEngine(EvidenceClass.MICROSTRUCTURE, rows)
    second = ReplayEngine(EvidenceClass.MICROSTRUCTURE, list(reversed(rows)))

    assert tuple(first) == tuple(second)
    assert first.completion_digest == second.completion_digest


def test_candle_context_rejects_microstructure_event_kinds() -> None:
    micro = row(
        receive_time_ms=1_000,
        path="events/a/segment-000001.jsonl",
        segment=1,
        line=1,
        kind="l2_book",
        evidence_class=EvidenceClass.CANDLE_CONTEXT,
    )

    try:
        ReplayEngine(EvidenceClass.CANDLE_CONTEXT, [micro])
    except EvidenceBoundaryError as exc:
        assert "l2_book" in str(exc)
    else:
        raise AssertionError("candle/context replay accepted L2 evidence")


def test_engine_rejects_rows_labeled_for_a_different_evidence_class() -> None:
    candle = row(
        receive_time_ms=1_000,
        path="events/a/segment-000001.jsonl",
        segment=1,
        line=1,
        kind="candle",
        evidence_class=EvidenceClass.CANDLE_CONTEXT,
    )

    try:
        ReplayEngine(EvidenceClass.MICROSTRUCTURE, [candle])
    except EvidenceBoundaryError as exc:
        assert "evidence_class" in str(exc)
    else:
        raise AssertionError("replay accepted a mismatched evidence class")


def test_completion_digest_is_unavailable_until_replay_is_exhausted() -> None:
    engine = ReplayEngine(
        EvidenceClass.MICROSTRUCTURE,
        [row(receive_time_ms=1_000, path="events/a/segment-000001.jsonl", segment=1, line=1)],
    )

    assert engine.completion_digest is None
    assert engine.next_event() is not None
    assert engine.completion_digest is not None
