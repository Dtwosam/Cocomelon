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


def assess_feed_gap_source_debt(
    checkpoint: object,
    charts: object,
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
            })
    by_source.sort(
        key=lambda item: (
            -cast(int, item["open_gap_count"]),
            str(item["scope"]), str(item["stream_id"]),
        )
    )
    unresolved_count = sum(
        cast(int, row["open_gap_count"]) for row in by_source
    )
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
        "current_checkpoint_not_retrospective_chart_recovery": True,
        "caution": (
            "Checkpoint source gaps describe unresolved sources at handoff. "
            "They do not certify any earlier closed trade chart and cannot "
            "clear missing source evidence without authentic recovery events."
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
