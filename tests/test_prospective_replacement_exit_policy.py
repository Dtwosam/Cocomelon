from __future__ import annotations

from cocomelon.research.prospective_replacement_exit_policy import (
    EXIT_HORIZON_MS,
    ProspectiveReplacementExitPolicyError,
    ProspectiveReplacementExitPolicyState,
    prospective_replacement_exit_policy_summary,
)


def _realized_payload() -> dict[str, object]:
    def option(
        suffix: str,
        *,
        timestamp_ms: int,
        pnl: str | None,
        funding_boundaries: int,
        funding_evidence: int,
        reason: str | None,
    ) -> dict[str, object]:
        return {
            "option_id": f"option-{suffix}",
            "opportunity_id": f"opp-{suffix}",
            "opportunity_timestamp_ms": timestamp_ms,
            "opportunity_market": "BTC",
            "opportunity_direction": "long",
            "entry_quantity": "1",
            "entry_attempt_timestamp_ms": timestamp_ms,
            "exits": {
                str(EXIT_HORIZON_MS): {
                    "horizon_ms": EXIT_HORIZON_MS,
                    "status": "simulated",
                    "funding_boundary_count": funding_boundaries,
                    "funding_boundaries_ms": (
                        []
                        if funding_boundaries == 0
                        else [3_600_000]
                    ),
                    "funding_evidence_count": funding_evidence,
                    "missing_funding_boundaries_ms": (
                        []
                        if funding_evidence == funding_boundaries
                        else [3_600_000]
                    ),
                    "funding_cash_pnl": (
                        "0"
                        if funding_boundaries == 0
                        else (
                            "0.1"
                            if funding_evidence == funding_boundaries
                            else None
                        )
                    ),
                    "exact_realized_pnl": pnl,
                    "incomplete_reason": reason,
                    "complete_close": pnl is not None,
                }
            },
        }

    return {
        "funding_evidence_modeled": True,
        "cross_horizon_economics_aggregated": False,
        "horizons_ms": [300_000, 900_000, 3_600_000, 21_600_000],
        "option_results": [
            option(
                "old",
                timestamp_ms=900,
                pnl="99",
                funding_boundaries=0,
                funding_evidence=0,
                reason=None,
            ),
            option(
                "win",
                timestamp_ms=1_100,
                pnl="2",
                funding_boundaries=0,
                funding_evidence=0,
                reason=None,
            ),
            option(
                "loss",
                timestamp_ms=1_200,
                pnl="-1.5",
                funding_boundaries=1,
                funding_evidence=1,
                reason=None,
            ),
            option(
                "missing",
                timestamp_ms=1_300,
                pnl=None,
                funding_boundaries=1,
                funding_evidence=0,
                reason="funding_evidence_required",
            ),
        ],
    }


def test_state_round_trip_freezes_single_five_minute_exit() -> None:
    state = ProspectiveReplacementExitPolicyState(started_at_ms=1_000)

    restored = ProspectiveReplacementExitPolicyState.from_payload(
        state.payload()
    )

    assert restored == state
    assert restored.exit_horizon_ms == 300_000
    assert restored.payload()["rule"] == {
        "exit_horizon_ms": 300_000,
        "entry_policy": "candidate_caused_replacement_fill",
        "exit_policy": "real_l2_reduce_only_ioc_at_fixed_horizon",
        "funding_policy": "exact_captured_hourly_boundaries",
        "cross_horizon_selection": "frozen_single_horizon",
    }


def test_summary_excludes_discovery_cohort_and_counts_exact_future_pnl() -> None:
    result = prospective_replacement_exit_policy_summary(
        _realized_payload(),
        ProspectiveReplacementExitPolicyState(started_at_ms=1_000),
    )

    assert result["discovery_options_excluded"] == 1
    assert result["prospective_options"] == 3
    assert result["exact_realized_pnl_options"] == 2
    assert result["incomplete_options"] == 1
    assert result["wins"] == 1
    assert result["losses"] == 1
    assert result["breakeven"] == 0
    assert result["exact_realized_pnl"] == "0.5"
    assert result["mean_exact_realized_pnl"] == "0.25"
    assert result["zero_boundary_exact_options"] == 1
    assert result["funded_exact_options"] == 1
    assert result["incomplete_reason_counts"] == {
        "funding_evidence_required": 1
    }
    assert result["cross_horizon_selection_frozen"] is True
    assert result["execution_authority"] is False
    assert result["promotion_authority"] is False


def test_summary_rejects_cross_horizon_aggregation() -> None:
    payload = _realized_payload()
    payload["cross_horizon_economics_aggregated"] = True

    try:
        prospective_replacement_exit_policy_summary(
            payload,
            ProspectiveReplacementExitPolicyState(started_at_ms=1_000),
        )
    except ProspectiveReplacementExitPolicyError as exc:
        assert "economically separate" in str(exc)
    else:
        raise AssertionError("cross-horizon aggregation must fail closed")
