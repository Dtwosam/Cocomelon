from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Final, cast

from cocomelon.evidence.lifecycle import _market_wire_name_for_gap_stream

OUTPUT_NAME: Final = "deferred-feed-gap-source-audit.json"
CHART_NAME: Final = "all-paper-trade-chart-audit.json"
CHECKPOINT_NAME: Final = "runtime-state.json"
SESSION_NAME: Final = "session-summary.json"
WITNESS_NAME: Final = "named-gap-recovery-witnesses.jsonl"
_HANDOFF_REASONS: Final = {"duration_elapsed", "upgrade_requested"}


class DeferredFeedGapSourceAuditError(RuntimeError):
    pass


def _object(raw: object, field: str) -> dict[str, object]:
    if not isinstance(raw, dict) or not all(isinstance(k, str) for k in raw):
        raise DeferredFeedGapSourceAuditError(f"{field} must be an object")
    return cast(dict[str, object], raw)


def _integer(raw: object, field: str) -> int:
    if type(raw) is not int or raw < 0:
        raise DeferredFeedGapSourceAuditError(
            f"{field} must be a non-negative integer"
        )
    return raw


def _intervals(
    raw: object,
    field: str,
    *,
    latest_ms: int,
) -> list[tuple[int, int | None]]:
    if not isinstance(raw, list):
        raise DeferredFeedGapSourceAuditError(f"{field} must be an array")
    selected: list[tuple[int, int | None]] = []
    for item in raw:
        if not isinstance(item, list) or len(item) != 2:
            raise DeferredFeedGapSourceAuditError(f"{field} invalid interval")
        start = _integer(item[0], f"{field}.start")
        end = (
            None if item[1] is None
            else _integer(item[1], f"{field}.end")
        )
        if (end is not None and end < start) or start > latest_ms or (
            end is not None and end > latest_ms
        ):
            raise DeferredFeedGapSourceAuditError(
                f"{field} interval exceeds known event chronology"
            )
        selected.append((start, end))
    return selected


def _scoped(
    raw: object,
    field: str,
    *,
    latest_ms: int,
    expect_market: bool,
) -> dict[str, list[tuple[int, int | None]]]:
    streams = _object(raw, field)
    result: dict[str, list[tuple[int, int | None]]] = {}
    for stream_id, records in streams.items():
        if not stream_id.strip() or stream_id.strip() != stream_id:
            raise DeferredFeedGapSourceAuditError(
                f"{field} contains invalid source identity"
            )
        is_market = _market_wire_name_for_gap_stream(stream_id) is not None
        if is_market != expect_market:
            raise DeferredFeedGapSourceAuditError(
                f"{field} source scope contradicts feed topic"
            )
        result[stream_id] = _intervals(
            records, f"{field}[{stream_id}]", latest_ms=latest_ms
        )
    return result



def _chart_trade_witnesses(
    trades: list[object],
) -> tuple[tuple[str, int, int, bool], ...]:
    """Validate original chart identities without treating marks as fills."""
    witnesses: list[tuple[str, int, int, bool]] = []
    trade_ids: set[str] = set()
    for raw in trades:
        row = _object(raw, "closed chart trade")
        trade_id = row.get("trade_id")
        market = row.get("market")
        if (
            not isinstance(trade_id, str) or not trade_id.strip()
            or trade_id in trade_ids
            or not isinstance(market, str) or not market.strip()
        ):
            raise DeferredFeedGapSourceAuditError(
                "closed chart trade identity missing or duplicated"
            )
        opened = _integer(row.get("opened_at_ms"), "chart opening")
        closed = _integer(row.get("closed_at_ms"), "chart close")
        if closed < opened:
            raise DeferredFeedGapSourceAuditError(
                "closed chart trade chronology invalid"
            )
        coverage = row.get("chart_coverage_complete")
        if type(coverage) is not bool:
            raise DeferredFeedGapSourceAuditError(
                "closed chart coverage witness must be boolean"
            )
        trade_ids.add(trade_id)
        witnesses.append((market, opened, closed, coverage))
    return tuple(witnesses)


def _overlap(
    intervals: list[tuple[int, int | None]],
    opened_ms: int,
    closed_ms: int,
    *,
    unresolved_only: bool,
) -> bool:
    """Closed trade intersects a real nonzero time span of source outage."""
    return any(
        start < closed_ms
        and (end is None or end > opened_ms)
        and (not unresolved_only or end is None)
        for start, end in intervals
    )


def _source_trade_exposure(
    intervals: list[tuple[int, int | None]],
    *,
    market: str | None,
    trades: tuple[tuple[str, int, int, bool], ...],
) -> dict[str, int]:
    """Potential chart exposure, NEVER a counterfactual execution count.

    Each source may affect the same closed trade; counts are not additive
    across streams. Market-specific outages cannot contaminate other coins.
    """
    possible = [
        (opened, closed, complete)
        for trade_market, opened, closed, complete in trades
        if market is None or trade_market == market
    ]
    overlapping = [
        (opened, closed, complete)
        for opened, closed, complete in possible
        if _overlap(intervals, opened, closed, unresolved_only=False)
    ]
    unresolved = [
        (opened, closed, complete)
        for opened, closed, complete in possible
        if _overlap(intervals, opened, closed, unresolved_only=True)
    ]
    return {
        "possible_market_trades": len(possible),
        "original_trades_overlapping_any_source_gap": len(overlapping),
        "original_trades_overlapping_unresolved_source_gap": len(unresolved),
        "incomplete_charts_overlapping_unresolved_source_gap": sum(
            not complete for _, _, complete in unresolved
        ),
    }


def _confirmed_named_recovery_witnesses(
    raw: object,
    *,
    named_gaps: dict[str, list[tuple[int, int | None]]],
    latest_ms: int,
) -> dict[str, object]:
    """Validate event witnesses against the *persisted* closed checkpoint.

    The ledger only claims a real accepted market event; every successfully
    audited recovery must independently intersect a saved named closed gap.
    Compacted intervals may absorb several older starts, so this is source
    coverage confirmation, not an exact per-trade or price reconstruction.
    """
    if raw is None:
        return {
            "named_recovery_witness_ledger_present": False,
            "named_recovery_witness_records": 0,
            "named_recovery_checkpoint_confirmed": 0,
            "named_recovery_witness_sources": 0,
        }
    if not isinstance(raw, list):
        raise DeferredFeedGapSourceAuditError(
            "named recovery witness ledger must be an array"
        )
    fields = {
        "definition", "checkpoint_last_available_at_ms", "stream_id",
        "gap_start_ms", "witness_receive_ms", "witness_exchange_ms",
        "witness_event_key", "witness_event_source",
        "observed_event_before_gap_closure",
        "independently_verified_checkpoint_closure",
        "historical_price_reconstruction", "research_only",
    }
    unique: set[tuple[str, int, int, str]] = set()
    sources: set[str] = set()
    for row in raw:
        witness = _object(row, "named recovery witness")
        if set(witness) != fields or (
            witness.get("definition")
            != "post_handoff_named_ws_recovery_witness_v1"
            or witness.get("witness_event_source") != "hyperliquid-mainnet-ws"
            or witness.get("observed_event_before_gap_closure") is not True
            or witness.get("independently_verified_checkpoint_closure") is not False
            or witness.get("historical_price_reconstruction") is not False
            or witness.get("research_only") is not True
        ):
            raise DeferredFeedGapSourceAuditError(
                "named recovery witness identity or authority mismatch"
            )
        stream_id = witness.get("stream_id")
        event_key = witness.get("witness_event_key")
        if (
            not isinstance(stream_id, str) or not stream_id.strip()
            or not isinstance(event_key, str) or not event_key.strip()
            or stream_id not in named_gaps
        ):
            raise DeferredFeedGapSourceAuditError(
                "named recovery witness has no known source identity"
            )
        source_start = _integer(witness.get("gap_start_ms"), "witness gap start")
        checkpoint_ms = _integer(
            witness.get("checkpoint_last_available_at_ms"),
            "witness predecessor timestamp",
        )
        received_ms = _integer(
            witness.get("witness_receive_ms"), "witness receive time"
        )
        exchange_raw = witness.get("witness_exchange_ms")
        if exchange_raw is not None:
            exchange_ms = _integer(exchange_raw, "witness exchange time")
            if exchange_ms > received_ms:
                raise DeferredFeedGapSourceAuditError(
                    "named recovery source arrived before exchange event"
                )
        elif stream_id.startswith("l2Book:"):
            raise DeferredFeedGapSourceAuditError(
                "L2 named recovery witness lacks exchange event time"
            )
        if not (
            source_start <= checkpoint_ms < received_ms <= latest_ms
        ):
            raise DeferredFeedGapSourceAuditError(
                "named recovery witness exceeds handoff chronology"
            )
        # A witness is not itself a recovery. It must be covered by a
        # checkpoint interval that is genuinely closed for this exact source.
        if not any(
            end is not None
            and start <= source_start
            and end >= received_ms
            for start, end in named_gaps[stream_id]
        ):
            raise DeferredFeedGapSourceAuditError(
                "named recovery witness lacks matching closed checkpoint gap"
            )
        unique.add((stream_id, source_start, received_ms, event_key))
        sources.add(stream_id)
    return {
        "named_recovery_witness_ledger_present": True,
        "named_recovery_witness_records": len(raw),
        "named_recovery_checkpoint_confirmed": len(unique),
        "named_recovery_witness_sources": len(sources),
    }


def assess_feed_gap_source_debt(
    checkpoint: object,
    charts: object,
    witnesses: object | None = None,
) -> dict[str, object]:
    """Diagnose current unresolved feed sources, not historical price recovery."""
    state = _object(checkpoint, "paper runtime checkpoint")
    chart = _object(charts, "authenticated full trade chart")
    version = _integer(state.get("schema_version"), "checkpoint schema")
    if version not in {1, 2, 3}:
        raise DeferredFeedGapSourceAuditError("unrecognized checkpoint schema")
    if state.get("execution_mode") != "paper":
        raise DeferredFeedGapSourceAuditError("checkpoint is not paper only")
    latest_ms = _integer(
        state.get("last_available_at_ms"), "checkpoint last available time"
    )
    if chart.get("definition") != (
        "entire_closed_paper_journal_with_observed_in_position_mark_charts_v1"
    ) or chart.get("research_only") is not True or any(
        chart.get(k) is not False
        for k in ("execution_authority", "promotion_authority")
    ):
        raise DeferredFeedGapSourceAuditError("chart provenance/authority mismatch")
    trades = chart.get("trades")
    if not isinstance(trades, list):
        raise DeferredFeedGapSourceAuditError("full chart journal absent")
    count = _integer(chart.get("total_journal_trades"), "chart journal count")
    if (
        len(trades) != count
        or _integer(chart.get("trades_included_in_economics"),
                    "chart economic count") != count
    ):
        raise DeferredFeedGapSourceAuditError("chart source omitted closed trades")
    trade_witnesses = _chart_trade_witnesses(trades)

    legacy = _intervals(
        state.get("known_gap_intervals", []),
        "legacy unscoped gaps",
        latest_ms=latest_ms,
    )
    if version == 1:
        if "known_gap_intervals_by_stream" in state or (
            "known_global_gap_intervals_by_stream" in state
        ):
            raise DeferredFeedGapSourceAuditError(
                "v1 checkpoint cannot claim later source lineage"
            )
        market_streams: dict[str, list[tuple[int, int | None]]] = {}
        global_streams: dict[str, list[tuple[int, int | None]]] = {}
    else:
        market_streams = _scoped(
            state.get("known_gap_intervals_by_stream"),
            "market scoped gaps", latest_ms=latest_ms, expect_market=True,
        )
        if version == 2:
            if "known_global_gap_intervals_by_stream" in state:
                raise DeferredFeedGapSourceAuditError(
                    "v2 checkpoint cannot claim named global lineage"
                )
            global_streams = {}
        else:
            global_streams = _scoped(
                state.get("known_global_gap_intervals_by_stream"),
                "named global gaps", latest_ms=latest_ms,
                expect_market=False,
            )

    by_source: list[dict[str, object]] = []
    for scope, streams in (
        ("legacy_unattributed", {"<legacy_unattributed>": legacy}),
        ("global_shared_or_unknown", global_streams),
        ("market_specific", market_streams),
    ):
        for stream_id, intervals in sorted(streams.items()):
            open_starts = [start for start, end in intervals if end is None]
            closed_durations = sum(
                end - start for start, end in intervals if end is not None
            )
            by_source.append({
                "scope": scope,
                "stream_id": stream_id,
                "source_identity_identifiable": scope != "legacy_unattributed",
                "market": (
                    _market_wire_name_for_gap_stream(stream_id)
                    if scope == "market_specific" else None
                ),
                "interval_count": len(intervals),
                "open_gap_count": len(open_starts),
                "closed_gap_count": len(intervals) - len(open_starts),
                "oldest_unresolved_gap_start_ms": min(open_starts, default=None),
                "newest_unresolved_gap_start_ms": max(open_starts, default=None),
                "closed_gap_duration_ms": closed_durations,
                **_source_trade_exposure(
                    intervals,
                    market=(
                        _market_wire_name_for_gap_stream(stream_id)
                        if scope == "market_specific" else None
                    ),
                    trades=trade_witnesses,
                ),
            })
    by_source.sort(
        key=lambda item: (
            -cast(
                int, item["incomplete_charts_overlapping_unresolved_source_gap"]
            ),
            -cast(int, item["original_trades_overlapping_unresolved_source_gap"]),
            -cast(int, item["open_gap_count"]),
            str(item["scope"]), str(item["stream_id"]),
        )
    )
    unresolved_count = sum(
        cast(int, row["open_gap_count"]) for row in by_source
    )
    unknown_legacy = next(
        row for row in by_source if row["scope"] == "legacy_unattributed"
    )
    named_repair_priority = [
        row for row in by_source
        if row["source_identity_identifiable"] is True
        and cast(int, row["open_gap_count"]) > 0
    ]
    return {
        "definition": "post_handoff_paper_feed_gap_source_debt_v1",
        "checkpoint_schema_version": version,
        "checkpoint_last_available_at_ms": latest_ms,
        "chart_total_journal_trades": count,
        "chart_complete_paths": _integer(
            chart.get("complete_chart_paths"), "complete charts"
        ),
        "chart_unresolved_pre_entry_gap_paths": _integer(
            chart.get("unresolved_gap_before_entry_affected_trades"),
            "preentry uncertain charts",
        ),
        "chart_clean_mark_cadence_but_unresolved_gap_paths": _integer(
            chart.get("clean_mark_cadence_but_unresolved_gap_trades"),
            "dense marks still uncertain",
        ),
        "open_gap_count_by_scope": {
            scope: sum(
                cast(int, row["open_gap_count"])
                for row in by_source if row["scope"] == scope
            )
            for scope in (
                "legacy_unattributed",
                "global_shared_or_unknown",
                "market_specific",
            )
        },
        "total_unresolved_source_gap_starts": unresolved_count,
        "sources_with_unresolved_gaps": sum(
            cast(int, row["open_gap_count"]) > 0 for row in by_source
        ),
        "by_source": by_source,
        "legacy_unattributable_open_gap_count": (
            unknown_legacy["open_gap_count"]
        ),
        "legacy_unattributable_affected_incomplete_charts": (
            unknown_legacy["incomplete_charts_overlapping_unresolved_source_gap"]
        ),
        "legacy_lineage_blocks_chart_source_certification": (
            cast(
                int, unknown_legacy[
                    "incomplete_charts_overlapping_unresolved_source_gap"
                ]
            ) > 0
        ),
        "named_unresolved_source_count": len(named_repair_priority),
        "named_source_repair_priority": named_repair_priority,
        "source_priority_definition": (
            "Named sources with unresolved histories are separately ranked "
            "for operational investigation. Anonymous legacy outages remain "
            "unattributable even if they affect more charts. Overlap counts "
            "are not additive, causal proof, or executable exit prices."
        ),
        "current_checkpoint_not_retrospective_chart_recovery": True,
        "caution": (
            "Checkpoint source gaps describe unresolved sources at handoff. "
            "These potential source/trade intersections overlap across "
            "topics, are not causal attribution, and cannot certify any "
            "previously closed chart without authentic recovery evidence."
        ),
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "changes_strategy": False,
        "changes_risk_limits": False,
        "changes_positions": False,
    }


def write_deferred_feed_gap_source_audit(root: str | Path) -> Path:
    state_root = Path(root)
    try:
        session = _object(
            json.loads((state_root / SESSION_NAME).read_text(encoding="utf-8")),
            "completed paper session",
        )
        state = json.loads((state_root / CHECKPOINT_NAME).read_text(encoding="utf-8"))
        chart = json.loads((state_root / CHART_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise DeferredFeedGapSourceAuditError(
            "missing or invalid post-handoff paper source"
        ) from exc
    if session.get("exit_reason") not in _HANDOFF_REASONS:
        raise DeferredFeedGapSourceAuditError(
            "feed source diagnosis requires completed paper handoff"
        )
    report = assess_feed_gap_source_debt(state, chart)
    destination = state_root / OUTPUT_NAME
    tmp = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(
            json.dumps(report, sort_keys=True, separators=(",", ":"),
                       allow_nan=False) + "\n",
            encoding="utf-8",
        )
        os.replace(tmp, destination)
    finally:
        tmp.unlink(missing_ok=True)
    return destination
