from __future__ import annotations

from copy import deepcopy

import pytest

from cocomelon.research.prospective_full_stack_reflow_exact_ledger import (
    ProspectiveFullStackReflowExactLedgerError,
    update_full_stack_reflow_exact_ledger,
    validate_full_stack_reflow_exact_ledger,
)

HORIZONS = (300_000, 900_000, 3_600_000)


def _digest(char: str) -> str:
    return "sha256:" + char * 64


def _exit(
    horizon_ms: int,
    *,
    exact_pnl: str | None,
    funding_cash: str = "0",
) -> dict[str, object]:
    if exact_pnl is None:
        return {
            "horizon_ms": horizon_ms,
            "status": "missing_exit_result",
            "funding_boundary_count": None,
            "funding_boundaries_ms": [],
            "funding_evidence_count": 0,
            "missing_funding_boundaries_ms": [],
            "funding_cash_pnl": None,
            "exact_realized_pnl": None,
            "incomplete_reason": "missing_exit_result",
        }
    return {
        "horizon_ms": horizon_ms,
        "status": "simulated",
        "funding_boundary_count": 0,
        "funding_boundaries_ms": [],
        "funding_evidence_count": 0,
        "missing_funding_boundaries_ms": [],
        "funding_cash_pnl": funding_cash,
        "exact_realized_pnl": exact_pnl,
        "incomplete_reason": None,
        "complete_close": True,
    }


def _option(
    suffix: str,
    *,
    direction: str = "long",
    market: str = "SOL",
    exact_horizons: tuple[int, ...] = HORIZONS,
    pnl: str = "2",
) -> dict[str, object]:
    timestamp = 20_000_000 + int(suffix)
    return {
        "option_id": f"option-{suffix}",
        "opportunity_id": f"opportunity-{suffix}",
        "opportunity_timestamp_ms": timestamp,
        "opportunity_market": market,
        "opportunity_direction": direction,
        "entry_quantity": "2",
        "entry_attempt_timestamp_ms": timestamp + 1_000,
        "exits": {
            str(horizon): _exit(
                horizon,
                exact_pnl=(pnl if horizon in exact_horizons else None),
            )
            for horizon in HORIZONS
        },
    }


def _summary(
    options: list[dict[str, object]],
    *,
    overlap_started_at_ms: int = 10_000_000,
    horizons: tuple[int, ...] = HORIZONS,
) -> dict[str, object]:
    exact_count = sum(
        1
        for option in options
        for exit_row in option["exits"].values()
        if isinstance(exit_row, dict)
        and exit_row.get("exact_realized_pnl") is not None
    )
    return {
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "portfolio_counterfactual": False,
        "cross_horizon_economics_aggregated": False,
        "strategy_level_realized_pnl_claimed": False,
        "overlap_started_at_ms": overlap_started_at_ms,
        "realized_pnl": {
            "research_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "horizons_ms": list(horizons),
            "option_results": options,
            "exact_realized_pnl_option_horizons": exact_count,
            "cross_horizon_economics_aggregated": False,
            "strategy_level_realized_pnl_claimed": False,
        },
    }


def test_exact_ledger_freezes_only_exact_option_horizons() -> None:
    first_option = _option(
        "1",
        exact_horizons=(300_000,),
        pnl="3",
    )
    first = update_full_stack_reflow_exact_ledger(
        _summary([first_option]),
        previous=None,
        source_paper_run_id=10,
        source_paper_run_attempt=1,
        source_artifact_name="learning-10-1",
        source_artifact_digest=_digest("a"),
    )

    assert first["row_count"] == 1
    assert first["new_row_count"] == 1
    assert first["pending_option_horizons"] == 2
    rows = first["rows"]
    assert isinstance(rows, tuple)
    assert rows[0]["horizon_ms"] == 300_000
    assert rows[0]["exact_realized_pnl"] == "3"

    matured = _option(
        "1",
        exact_horizons=HORIZONS,
        pnl="3",
    )
    second = update_full_stack_reflow_exact_ledger(
        _summary([matured]),
        previous=first,
        source_paper_run_id=11,
        source_paper_run_attempt=1,
        source_artifact_name="learning-11-1",
        source_artifact_digest=_digest("b"),
    )

    assert second["previous_row_count"] == 1
    assert second["new_row_count"] == 2
    assert second["row_count"] == 3
    assert second["pending_option_horizons"] == 0
    second_rows = second["rows"]
    assert isinstance(second_rows, tuple)
    assert second_rows[0] == rows[0]
    validate_full_stack_reflow_exact_ledger(second)


def test_exact_ledger_rejects_changed_published_economics() -> None:
    option = _option("1", exact_horizons=(300_000,), pnl="3")
    first = update_full_stack_reflow_exact_ledger(
        _summary([option]),
        previous=None,
        source_paper_run_id=20,
        source_paper_run_attempt=1,
        source_artifact_name="learning-20-1",
        source_artifact_digest=_digest("c"),
    )

    changed = deepcopy(option)
    exits = changed["exits"]
    assert isinstance(exits, dict)
    row = exits["300000"]
    assert isinstance(row, dict)
    row["exact_realized_pnl"] = "9"

    with pytest.raises(
        ProspectiveFullStackReflowExactLedgerError,
        match="previous exact option-horizon row changed",
    ):
        update_full_stack_reflow_exact_ledger(
            _summary([changed]),
            previous=first,
            source_paper_run_id=21,
            source_paper_run_attempt=1,
            source_artifact_name="learning-21-1",
            source_artifact_digest=_digest("d"),
        )


def test_exact_ledger_rejects_campaign_start_or_horizon_drift() -> None:
    option = _option("1")
    first = update_full_stack_reflow_exact_ledger(
        _summary([option]),
        previous=None,
        source_paper_run_id=30,
        source_paper_run_attempt=1,
        source_artifact_name="learning-30-1",
        source_artifact_digest=_digest("e"),
    )

    with pytest.raises(
        ProspectiveFullStackReflowExactLedgerError,
        match="campaign start drift",
    ):
        update_full_stack_reflow_exact_ledger(
            _summary(
                [option],
                overlap_started_at_ms=10_000_001,
            ),
            previous=first,
            source_paper_run_id=31,
            source_paper_run_attempt=1,
            source_artifact_name="learning-31-1",
            source_artifact_digest=_digest("f"),
        )

    with pytest.raises(
        ProspectiveFullStackReflowExactLedgerError,
        match="horizon set drift",
    ):
        update_full_stack_reflow_exact_ledger(
            _summary(
                [option],
                horizons=(300_000, 900_000),
            ),
            previous=first,
            source_paper_run_id=32,
            source_paper_run_attempt=1,
            source_artifact_name="learning-32-1",
            source_artifact_digest=_digest("1"),
        )


def test_exact_ledger_is_idempotent_for_same_source() -> None:
    source = _summary([_option("1")])
    first = update_full_stack_reflow_exact_ledger(
        source,
        previous=None,
        source_paper_run_id=40,
        source_paper_run_attempt=1,
        source_artifact_name="learning-40-1",
        source_artifact_digest=_digest("2"),
    )
    repeated = update_full_stack_reflow_exact_ledger(
        source,
        previous=first,
        source_paper_run_id=40,
        source_paper_run_attempt=1,
        source_artifact_name="learning-40-1",
        source_artifact_digest=_digest("2"),
    )

    assert repeated == validate_full_stack_reflow_exact_ledger(first)


def test_exact_ledger_rejects_duplicate_source_artifact_drift() -> None:
    source = _summary([_option("1")])
    first = update_full_stack_reflow_exact_ledger(
        source,
        previous=None,
        source_paper_run_id=50,
        source_paper_run_attempt=1,
        source_artifact_name="learning-50-1",
        source_artifact_digest=_digest("3"),
    )

    with pytest.raises(
        ProspectiveFullStackReflowExactLedgerError,
        match="duplicate source artifact identity drift",
    ):
        update_full_stack_reflow_exact_ledger(
            source,
            previous=first,
            source_paper_run_id=50,
            source_paper_run_attempt=1,
            source_artifact_name="learning-50-1",
            source_artifact_digest=_digest("4"),
        )


def test_exact_ledger_keeps_horizon_economics_separate_and_robust() -> None:
    markets = ("BTC", "ETH", "SOL", "ENA")
    options = [
        _option(
            str(index),
            direction="long" if index % 2 == 0 else "short",
            market=markets[index % len(markets)],
            pnl="2",
        )
        for index in range(20)
    ]
    ledger = update_full_stack_reflow_exact_ledger(
        _summary(options),
        previous=None,
        source_paper_run_id=60,
        source_paper_run_attempt=1,
        source_artifact_name="learning-60-1",
        source_artifact_digest=_digest("5"),
    )

    assert ledger["row_count"] == 60
    summary = ledger["summary"]
    assert isinstance(summary, dict)
    assert summary["cross_horizon_economics_aggregated"] is False
    by_horizon = summary["by_horizon"]
    assert isinstance(by_horizon, dict)
    for horizon in HORIZONS:
        item = by_horizon[str(horizon)]
        assert item["exact_option_horizons"] == 20
        assert item["long_exact_options"] == 10
        assert item["short_exact_options"] == 10
        assert item["market_count"] == 4
        assert item["total_exact_realized_pnl"] == "40"
        assert item["leave_one_option_out_min_pnl"] == "38"
        assert item["leave_one_market_out_min_pnl"] == "30"
        readiness = item["review_readiness"]
        assert readiness["sample_complete"] is True
        assert readiness["economics_positive"] is True
        assert readiness["single_option_robust"] is True
        assert readiness["single_market_robust"] is True
        assert readiness["ready_for_evidence_review"] is True
        assert readiness["changes_execution"] is False
        assert readiness["changes_readiness_gate"] is False
