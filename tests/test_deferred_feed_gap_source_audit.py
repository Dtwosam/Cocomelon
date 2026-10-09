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
        "trades": [
            {
                "trade_id": "btc-early", "market": "BTC",
                "opened_at_ms": 150, "closed_at_ms": 250,
                "chart_coverage_complete": False,
            },
            {
                "trade_id": "eth-middle", "market": "ETH",
                "opened_at_ms": 450, "closed_at_ms": 700,
                "chart_coverage_complete": False,
            },
            {
                "trade_id": "sol-late", "market": "SOL",
                "opened_at_ms": 750, "closed_at_ms": 900,
                "chart_coverage_complete": True,
            },
        ],
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
    assert report["legacy_unattributable_open_gap_count"] == 1
    assert report["legacy_unattributable_affected_incomplete_charts"] == 2
    assert report["legacy_lineage_blocks_chart_source_certification"] is True
    assert report["named_unresolved_source_count"] == 4
    assert all(
        item["source_identity_identifiable"] is True
        and item["scope"] != "legacy_unattributed"
        for item in report["named_source_repair_priority"]
    )
    assert report["named_source_repair_priority"][0]["stream_id"] in {
        "allMids", "l2Book:BTC:malformed:extra"
    }
    named = {
        row["stream_id"]: row for row in report["by_source"]
    }
    assert named["l2Book:BTC"]["market"] == "BTC"
    assert named["l2Book:BTC"]["closed_gap_count"] == 1
    assert named["l2Book:BTC"][
        "original_trades_overlapping_unresolved_source_gap"
    ] == 1
    assert named["l2Book:BTC"][
        "incomplete_charts_overlapping_unresolved_source_gap"
    ] == 1
    assert named["candle:ETH:1m"][
        "original_trades_overlapping_unresolved_source_gap"
    ] == 1
    assert named["allMids"][
        "original_trades_overlapping_unresolved_source_gap"
    ] == 2
    assert named["allMids"][
        "incomplete_charts_overlapping_unresolved_source_gap"
    ] == 1
    assert named["<legacy_unattributed>"][
        "incomplete_charts_overlapping_unresolved_source_gap"
    ] == 2
    assert named["<legacy_unattributed>"][
        "original_trades_overlapping_unresolved_source_gap"
    ] == 3
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


def test_resolved_gaps_and_unrelated_coin_never_count_as_open_source_debt() -> None:
    state = _checkpoint()
    state["known_gap_intervals_by_stream"] = {
        "l2Book:BTC": [[300, 330]],  # historical gap, no active BTC overlap
        "l2Book:DOGE": [[100, None]],  # no DOGE original positions
    }
    state["known_gap_intervals"] = []
    state["known_global_gap_intervals_by_stream"] = {}
    report = assess_feed_gap_source_debt(state, _charts())
    by_source = {row["stream_id"]: row for row in report["by_source"]}
    assert by_source["l2Book:BTC"][
        "original_trades_overlapping_any_source_gap"
    ] == 0
    assert by_source["l2Book:BTC"][
        "original_trades_overlapping_unresolved_source_gap"
    ] == 0
    assert by_source["l2Book:DOGE"]["possible_market_trades"] == 0
    assert by_source["l2Book:DOGE"][
        "incomplete_charts_overlapping_unresolved_source_gap"
    ] == 0
    assert report["sources_with_unresolved_gaps"] == 1


@pytest.mark.parametrize(
    ("invalid_key", "replacement"),
    (
        ("trade_id", "btc-early"),
        ("market", ""),
        ("opened_at_ms", True),
        ("closed_at_ms", 100),
        ("chart_coverage_complete", "yes"),
    ),
)
def test_source_priority_rejects_invalid_original_trade_witness(
    invalid_key: str, replacement: object,
) -> None:
    charts = _charts()
    rows = charts["trades"]
    assert isinstance(rows, list)
    rows[1][invalid_key] = replacement
    with pytest.raises(DeferredFeedGapSourceAuditError):
        assess_feed_gap_source_debt(_checkpoint(), charts)


def test_open_source_priority_is_non_additive_and_no_price_execution_claim() -> None:
    report = assess_feed_gap_source_debt(_checkpoint(), _charts())
    by_source = report["by_source"]
    assert isinstance(by_source, list)
    assert by_source[0]["stream_id"] == "<legacy_unattributed>"
    # The same ETH/SOL original is present for multiple overlapping streams.
    assert sum(
        item["original_trades_overlapping_unresolved_source_gap"]
        for item in by_source
    ) > report["chart_total_journal_trades"]
    assert "not additive" in report["source_priority_definition"]
    assert report["current_checkpoint_not_retrospective_chart_recovery"] is True
    assert report["promotion_authority"] is False


def test_named_repair_priority_never_erases_anonymous_legacy_debt() -> None:
    state = _checkpoint()
    state["known_gap_intervals"] = [[100, None], [120, None]]
    state["known_gap_intervals_by_stream"] = {}
    state["known_global_gap_intervals_by_stream"] = {}
    report = assess_feed_gap_source_debt(state, _charts())
    assert report["legacy_unattributable_open_gap_count"] == 2
    assert report["legacy_unattributable_affected_incomplete_charts"] == 2
    assert report["legacy_lineage_blocks_chart_source_certification"] is True
    assert report["named_unresolved_source_count"] == 0
    assert report["named_source_repair_priority"] == []


def test_named_repair_priority_can_exist_with_no_legacy_uncertainty() -> None:
    state = _checkpoint()
    state["known_gap_intervals"] = []
    report = assess_feed_gap_source_debt(state, _charts())
    assert report["legacy_unattributable_open_gap_count"] == 0
    assert report["legacy_lineage_blocks_chart_source_certification"] is False
    assert report["named_unresolved_source_count"] == 4
    assert all(
        item["source_identity_identifiable"]
        for item in report["named_source_repair_priority"]
    )


def _fresh_named_witness() -> dict[str, object]:
    return {
        "definition": "post_handoff_named_ws_recovery_witness_v1",
        "checkpoint_last_available_at_ms": 500,
        "stream_id": "l2Book:BTC",
        "gap_start_ms": 200,
        "witness_receive_ms": 650,
        "witness_exchange_ms": 640,
        "witness_event_key": "l2Book:BTC:650",
        "witness_event_source": "hyperliquid-mainnet-ws",
        "observed_event_before_gap_closure": True,
        "independently_verified_checkpoint_closure": False,
        "historical_price_reconstruction": False,
        "research_only": True,
    }


def test_post_handoff_named_witness_needs_persisted_closed_gap() -> None:
    state = _checkpoint()
    state["known_gap_intervals_by_stream"] = {
        "l2Book:BTC": [[200, 650]],
        "candle:ETH:1m": [[400, None]],
    }
    report = assess_feed_gap_source_debt(
        state, _charts(), [_fresh_named_witness()]
    )
    assert report["named_recovery_witness_ledger_present"] is True
    assert report["named_recovery_witness_records"] == 1
    assert report["named_recovery_checkpoint_confirmed"] == 1
    assert report["named_recovery_witness_sources"] == 1
    assert report["legacy_unattributable_open_gap_count"] == 1
    assert report["current_checkpoint_not_retrospective_chart_recovery"]

    # A live witness alone cannot close a still-open interval.
    unclosed = _checkpoint()
    with pytest.raises(
        DeferredFeedGapSourceAuditError, match="original gap remains unresolved"
    ):
        assess_feed_gap_source_debt(
            unclosed, _charts(), [_fresh_named_witness()]
        )


def test_overlapping_old_closed_interval_cannot_hide_unresolved_start() -> None:
    state = _checkpoint()
    # An old closed outage spans the new witness, but the original exact
    # checkpoint gap start is still unresolved. This is no recovery.
    state["known_gap_intervals_by_stream"] = {
        "l2Book:BTC": [[100, 700], [200, None]]
    }
    with pytest.raises(
        DeferredFeedGapSourceAuditError, match="original gap remains unresolved"
    ):
        assess_feed_gap_source_debt(
            state, _charts(), [_fresh_named_witness()]
        )


@pytest.mark.parametrize(
    ("field", "invalid"),
    [
        ("stream_id", "l2Book:SOL"),
        ("witness_event_source", "hyperliquid-mainnet-rest"),
        ("witness_receive_ms", 1001),
        ("witness_exchange_ms", None),
        ("checkpoint_last_available_at_ms", 700),
        ("gap_start_ms", 100),
        ("historical_price_reconstruction", True),
        ("independently_verified_checkpoint_closure", True),
    ],
)
def test_forged_or_uncertified_named_recovery_receipts_fail_closed(
    field: str, invalid: object,
) -> None:
    state = _checkpoint()
    state["known_gap_intervals_by_stream"] = {
        "l2Book:BTC": [[200, 650]],
    }
    witness = _fresh_named_witness()
    witness[field] = invalid
    with pytest.raises(DeferredFeedGapSourceAuditError):
        assess_feed_gap_source_debt(state, _charts(), [witness])


def test_writer_requires_complete_fsynced_witness_rows(
    tmp_path: Path,
) -> None:
    root = tmp_path
    state = _checkpoint()
    state["known_gap_intervals_by_stream"] = {
        "l2Book:BTC": [[200, 650]]
    }
    (root / "runtime-state.json").write_text(
        json.dumps(state), encoding="utf-8"
    )
    (root / "all-paper-trade-chart-audit.json").write_text(
        json.dumps(_charts()), encoding="utf-8"
    )
    (root / "session-summary.json").write_text(
        json.dumps({"exit_reason": "upgrade_requested"}), encoding="utf-8"
    )
    witness_path = root / "named-gap-recovery-witnesses.jsonl"
    witness_path.write_text(
        json.dumps(_fresh_named_witness()) + "\n", encoding="utf-8"
    )
    report_path = write_deferred_feed_gap_source_audit(root)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["named_recovery_checkpoint_confirmed"] == 1

    witness_path.write_text(
        json.dumps(_fresh_named_witness()), encoding="utf-8"
    )
    with pytest.raises(
        DeferredFeedGapSourceAuditError, match="incomplete trailing row"
    ):
        write_deferred_feed_gap_source_audit(root)


def test_named_debt_separates_selected_from_unselected_handoff_markets() -> None:
    checkpoint = _checkpoint()
    checkpoint["selected_markets"] = ["BTC"]
    report = assess_feed_gap_source_debt(
        checkpoint, _charts(), selected_markets=["BTC"]
    )
    assert report["market_selection_checkpoint_attested"] is True
    assert report["market_selection_available_at_handoff"] is True
    assert report["selected_market_count_at_handoff"] == 1
    assert report["named_open_starts_in_selected_markets"] == 1
    assert report["named_open_starts_in_unselected_markets"] == 1
    assert report["named_open_starts_in_shared_feeds"] == 2
    assert [row["stream_id"] for row in report["selected_named_repair_priority"]] == [
        "l2Book:BTC"
    ]
    assert [row["stream_id"] for row in report["unselected_named_repair_priority"]] == [
        "candle:ETH:1m"
    ]
    assert len(report["shared_named_repair_priority"]) == 2
    by_source = {row["stream_id"]: row for row in report["by_source"]}
    assert by_source["l2Book:BTC"]["selected_market_at_handoff"] is True
    assert by_source["candle:ETH:1m"]["selected_market_at_handoff"] is False
    assert by_source["allMids"]["selected_market_at_handoff"] is None
    assert by_source["<legacy_unattributed>"]["selected_market_at_handoff"] is None
    # All original records remain. Classification is not chart repair.
    assert report["total_unresolved_source_gap_starts"] == 5
    assert report["legacy_unattributable_open_gap_count"] == 1
    assert report["current_checkpoint_not_retrospective_chart_recovery"]


def test_without_trusted_watchlist_no_unselected_market_inference() -> None:
    report = assess_feed_gap_source_debt(_checkpoint(), _charts())
    assert report["market_selection_available_at_handoff"] is False
    assert report["market_selection_checkpoint_attested"] is None
    assert report["selected_market_count_at_handoff"] is None
    assert report["named_open_starts_in_selected_markets"] == 0
    assert report["named_open_starts_in_unselected_markets"] == 0
    assert report["named_open_starts_in_shared_feeds"] == 2
    assert report["named_unresolved_source_count"] == 4
    assert all(
        row["selected_market_at_handoff"] is None
        for row in report["by_source"]
    )


@pytest.mark.parametrize("selected", (
    "BTC", [None], [" BTC"], ["BTC", "BTC"], ["BTC:"],
    ["BTC:ETH:INVALID"], [3], {"BTC": True},
))
def test_untrusted_handoff_watchlist_cannot_label_sources(
    selected: object,
) -> None:
    with pytest.raises(DeferredFeedGapSourceAuditError, match="selected market"):
        assess_feed_gap_source_debt(
            _checkpoint(), _charts(), selected_markets=selected
        )


def test_completed_handoff_writer_uses_real_selected_snapshot(
    tmp_path: Path,
) -> None:
    checkpoint = _checkpoint()
    checkpoint["selected_markets"] = ["BTC"]
    (tmp_path / "runtime-state.json").write_text(
        json.dumps(checkpoint), encoding="utf-8"
    )
    (tmp_path / "all-paper-trade-chart-audit.json").write_text(
        json.dumps(_charts()), encoding="utf-8"
    )
    (tmp_path / "session-summary.json").write_text(
        json.dumps({
            "exit_reason": "upgrade_requested",
            "selected_markets": ["BTC"],
        }), encoding="utf-8"
    )
    destination = write_deferred_feed_gap_source_audit(tmp_path)
    report = json.loads(destination.read_text(encoding="utf-8"))
    assert report["market_selection_checkpoint_attested"] is True
    assert report["market_selection_available_at_handoff"] is True
    assert report["selected_market_count_at_handoff"] == 1
    assert report["named_open_starts_in_selected_markets"] == 1
    assert report["named_open_starts_in_unselected_markets"] == 1
    assert report["legacy_unattributable_open_gap_count"] == 1


@pytest.mark.parametrize(
    "checkpoint_selection",
    (["ETH"], ["BTC", "ETH"], [], "BTC", ["BTC", "BTC"]),
)
def test_v3_checkpoint_watchlist_disagreement_fails_closed(
    checkpoint_selection: object,
) -> None:
    state = _checkpoint()
    state["selected_markets"] = checkpoint_selection
    with pytest.raises(
        DeferredFeedGapSourceAuditError,
        match="checkpoint and session selected markets disagree",
    ):
        assess_feed_gap_source_debt(
            state, _charts(), selected_markets=["BTC"]
        )


def test_v3_missing_checkpoint_watchlist_fails_closed() -> None:
    with pytest.raises(
        DeferredFeedGapSourceAuditError,
        match="v3 checkpoint is missing handoff selected markets",
    ):
        assess_feed_gap_source_debt(
            _checkpoint(), _charts(), selected_markets=["BTC"]
        )


def test_legacy_checkpoint_absent_watchlist_is_not_attested() -> None:
    state = _checkpoint()
    state["schema_version"] = 1
    state.pop("known_gap_intervals_by_stream")
    state.pop("known_global_gap_intervals_by_stream")
    report = assess_feed_gap_source_debt(
        state, _charts(), selected_markets=["BTC"]
    )
    assert report["market_selection_available_at_handoff"] is True
    assert report["market_selection_checkpoint_attested"] is None
    assert report["named_unresolved_source_count"] == 0
    assert report["legacy_unattributable_open_gap_count"] == 1


def test_checkpoint_adjacent_gap_burst_is_not_erased_or_called_recovered() -> None:
    state = _checkpoint()
    state["last_available_at_ms"] = 10_000
    state["known_gap_intervals_by_stream"] = {
        "l2Book:BTC": [
            [200, None], [4_999, None], [5_000, None], [9_999, None],
        ],
        "candle:ETH:1m": [[400, None]],
    }
    state["known_global_gap_intervals_by_stream"] = {
        "allMids": [[500, None], [9_999, None]]
    }
    report = assess_feed_gap_source_debt(state, _charts())
    assert report["checkpoint_adjacent_window_ms"] == 5_000
    assert report["checkpoint_adjacent_open_gaps_by_scope"] == {
        "legacy_unattributed": 0,
        "global_shared_or_unknown": 1,
        "market_specific": 2,
    }
    assert report["older_open_gaps_by_scope"] == {
        "legacy_unattributed": 1,
        "global_shared_or_unknown": 1,
        "market_specific": 3,
    }
    assert report["checkpoint_adjacent_named_source_count"] == 2
    assert report["open_gap_count_by_scope"] == {
        "legacy_unattributed": 1,
        "global_shared_or_unknown": 2,
        "market_specific": 5,
    }
    assert report["total_unresolved_source_gap_starts"] == 8
    by_stream = {r["stream_id"]: r for r in report["by_source"]}
    assert by_stream["l2Book:BTC"]["checkpoint_adjacent_open_gap_starts"] == 2
    assert by_stream["l2Book:BTC"]["older_open_gap_starts"] == 2
    assert by_stream["allMids"]["checkpoint_adjacent_open_gap_starts"] == 1
    assert by_stream["<legacy_unattributed>"]["older_open_gap_starts"] == 1
    assert report["current_checkpoint_not_retrospective_chart_recovery"] is True
    assert report["promotion_authority"] is False
    assert report["execution_authority"] is False


def test_all_old_gaps_still_count_when_far_before_checkpoint() -> None:
    state = _checkpoint()
    state["last_available_at_ms"] = 2_000_000
    report = assess_feed_gap_source_debt(state, _charts())
    assert all(
        count == 0
        for count in report["checkpoint_adjacent_open_gaps_by_scope"].values()
    )
    assert report["older_open_gaps_by_scope"] == report["open_gap_count_by_scope"]
    assert report["named_unresolved_source_count"] == 4
