from __future__ import annotations

import json
from pathlib import Path

import pytest

from cocomelon.research.deferred_feed_gap_source_audit import (
    DeferredFeedGapSourceAuditError,
    assess_feed_gap_source_debt,
    write_deferred_feed_gap_source_audit,
)


def _charts() -> dict[str, object]:
    return {
        "definition": (
            "entire_closed_paper_journal_with_observed_in_position_mark_charts_v1"
        ),
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "total_journal_trades": 3,
        "trades_included_in_economics": 3,
        "trades": [{}, {}, {}],
        "complete_chart_paths": 1,
        "unresolved_gap_before_entry_affected_trades": 2,
        "clean_mark_cadence_but_unresolved_gap_trades": 1,
    }


def _checkpoint() -> dict[str, object]:
    return {
        "schema_version": 3,
        "execution_mode": "paper",
        "live_orders": False,
        "last_available_at_ms": 1000,
        "known_gap_intervals": [[100, None]],
        "known_gap_intervals_by_stream": {
            "l2Book:BTC": [[200, None], [300, 330]],
            "candle:ETH:1m": [[400, None]],
        },
        "known_global_gap_intervals_by_stream": {
            "allMids": [[500, None]],
            "l2Book:BTC:malformed:extra": [[600, None]],
        },
    }


def test_stream_scope_provenance_survives_without_recovering_legacy_gaps() -> None:
    report = assess_feed_gap_source_debt(_checkpoint(), _charts())
    assert report["checkpoint_schema_version"] == 3
    assert report["chart_total_journal_trades"] == 3
    assert report["chart_unresolved_pre_entry_gap_paths"] == 2
    assert report["chart_clean_mark_cadence_but_unresolved_gap_paths"] == 1
    assert report["open_gap_count_by_scope"] == {
        "legacy_unattributed": 1,
        "global_shared_or_unknown": 2,
        "market_specific": 2,
    }
    assert report["sources_with_unresolved_gaps"] == 5
    assert report["total_unresolved_source_gap_starts"] == 5
    named = {
        row["stream_id"]: row for row in report["by_source"]
    }
    assert named["l2Book:BTC"]["market"] == "BTC"
    assert named["l2Book:BTC"]["closed_gap_count"] == 1
    assert named["l2Book:BTC"]["closed_gap_duration_ms"] == 30
    assert named["allMids"]["market"] is None
    assert named["l2Book:BTC:malformed:extra"]["scope"] == (
        "global_shared_or_unknown"
    )
    assert named["<legacy_unattributed>"]["oldest_unresolved_gap_start_ms"] == 100
    assert report["current_checkpoint_not_retrospective_chart_recovery"] is True
    assert report["execution_authority"] is False
    assert report["promotion_authority"] is False


@pytest.mark.parametrize(
    ("schema", "scope_map", "scope_counts"),
    (
        (1, {}, {"legacy_unattributed": 1,
                 "global_shared_or_unknown": 0, "market_specific": 0}),
        (2, {"known_gap_intervals_by_stream": {"l2Book:ETH": [[80, None]]}},
         {"legacy_unattributed": 1,
          "global_shared_or_unknown": 0, "market_specific": 1}),
    ),
)
def test_legacy_checkpoints_do_not_fabricate_named_global_recovery(
    schema: int,
    scope_map: dict[str, object],
    scope_counts: dict[str, int],
) -> None:
    state = _checkpoint()
    state["schema_version"] = schema
    state.pop("known_gap_intervals_by_stream")
    state.pop("known_global_gap_intervals_by_stream")
    state.update(scope_map)
    report = assess_feed_gap_source_debt(state, _charts())
    assert report["open_gap_count_by_scope"] == scope_counts


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("known_gap_intervals", [[True, None]]),
        ("known_gap_intervals", [[100, 50]]),
        ("known_gap_intervals", [[100, 2000]]),
        ("known_gap_intervals", [[100, "200"]]),
        ("known_gap_intervals_by_stream", {"allMids": [[100, None]]}),
        ("known_global_gap_intervals_by_stream", {"l2Book:BTC": [[100, None]]}),
        ("known_global_gap_intervals_by_stream", {"": [[100, None]]}),
    ),
)
def test_invalid_source_witnesses_fail_closed(field: str, value: object) -> None:
    state = _checkpoint()
    state[field] = value
    with pytest.raises(DeferredFeedGapSourceAuditError):
        assess_feed_gap_source_debt(state, _charts())


def test_full_chart_population_and_authority_are_required() -> None:
    charts = _charts()
    charts["trades_included_in_economics"] = 2
    with pytest.raises(DeferredFeedGapSourceAuditError, match="omitted"):
        assess_feed_gap_source_debt(_checkpoint(), charts)

    charts = _charts()
    charts["promotion_authority"] = True
    with pytest.raises(DeferredFeedGapSourceAuditError, match="authority"):
        assess_feed_gap_source_debt(_checkpoint(), charts)


def test_named_global_ancestry_is_not_supported_by_v2() -> None:
    state = _checkpoint()
    state["schema_version"] = 2
    with pytest.raises(DeferredFeedGapSourceAuditError, match="v2 checkpoint"):
        assess_feed_gap_source_debt(state, _charts())


def test_post_handoff_writer_rejects_unfinished_session(
    tmp_path: Path,
) -> None:
    root = tmp_path
    (root / "runtime-state.json").write_text(
        json.dumps(_checkpoint()), encoding="utf-8"
    )
    (root / "all-paper-trade-chart-audit.json").write_text(
        json.dumps(_charts()), encoding="utf-8"
    )
    (root / "session-summary.json").write_text(
        json.dumps({"exit_reason": "running"}), encoding="utf-8"
    )
    with pytest.raises(
        DeferredFeedGapSourceAuditError, match="completed paper handoff"
    ):
        write_deferred_feed_gap_source_audit(root)
    assert not (root / "deferred-feed-gap-source-audit.json").exists()

    (root / "session-summary.json").write_text(
        json.dumps({"exit_reason": "upgrade_requested"}), encoding="utf-8"
    )
    dest = write_deferred_feed_gap_source_audit(root)
    report = json.loads(dest.read_text(encoding="utf-8"))
    assert report["sources_with_unresolved_gaps"] == 5
    assert report["research_only"] is True
