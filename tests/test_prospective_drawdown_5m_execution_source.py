from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from cocomelon.domain.execution import PaperExecutionConfig
from cocomelon.research.prospective_drawdown_5m_execution_source import (
    CANDIDATE_ID,
    EXIT_HORIZON_MS,
    ProspectiveDrawdown5mExecutionState,
    prospective_drawdown_5m_execution_source,
)


@dataclass(frozen=True)
class _Opportunity:
    opportunity_id: str
    opportunity_timestamp_ms: int
    market: str = "SOL"
    direction: str = "long"
    lead_strategy: str = "trend"
    baseline_risk_approved: bool = False
    baseline_risk_reason_codes: tuple[str, ...] = (
        "weekly_drawdown_lockout",
    )

    def to_dict(self) -> dict[str, object]:
        return {
            "opportunity_id": self.opportunity_id,
            "opportunity_timestamp_ms": self.opportunity_timestamp_ms,
            "market": self.market,
            "direction": self.direction,
            "lead_strategy": self.lead_strategy,
            "baseline_risk_approved": self.baseline_risk_approved,
            "baseline_risk_reason_codes": list(
                self.baseline_risk_reason_codes
            ),
            "risk_request": {"fixture": True},
            "book": {"fixture": True},
            "instrument": {"fixture": True},
        }


@dataclass(frozen=True)
class _ExitBook:
    opportunity_id: str
    opportunity_timestamp_ms: int
    market: str = "SOL"
    direction: str = "long"
    horizon_ms: int = EXIT_HORIZON_MS
    target_at_ms: int = 0
    observed_at_ms: int = 0

    def to_dict(self) -> dict[str, object]:
        return {
            "opportunity_id": self.opportunity_id,
            "opportunity_timestamp_ms": self.opportunity_timestamp_ms,
            "market": self.market,
            "direction": self.direction,
            "horizon_ms": self.horizon_ms,
            "target_at_ms": self.target_at_ms,
            "observed_at_ms": self.observed_at_ms,
            "observation_lag_ms": self.observed_at_ms - self.target_at_ms,
            "book": {"fixture": True},
            "instrument": {"fixture": True},
            "schema_version": 1,
        }


@dataclass(frozen=True)
class _Funding:
    market: str
    boundary_ms: int

    def to_dict(self) -> dict[str, object]:
        return {
            "market": self.market,
            "boundary_ms": self.boundary_ms,
            "oracle_px": "100",
            "oracle_observed_at_ms": self.boundary_ms,
            "oracle_age_ms": 0,
            "oracle_source": "fixture",
            "oracle_schema_version": 1,
            "funding_rate": "0.0001",
            "premium": "0",
            "funding_time_ms": self.boundary_ms,
            "funding_received_at_ms": self.boundary_ms,
            "funding_source": "fixture",
            "funding_schema_version": 1,
        }


def _row(
    opportunity_id: str,
    timestamp_ms: int,
    *,
    decision: str = "ADMIT",
    reasons: tuple[str, ...] = ("weekly_drawdown_lockout",),
) -> dict[str, object]:
    return {
        "opportunity_id": opportunity_id,
        "timestamp_ms": timestamp_ms,
        "market": "SOL",
        "direction": "long",
        "lead_strategy": "trend",
        "rank_ordinal": 3,
        "rank_age_ms": 100,
        "baseline_risk_approved": False,
        "baseline_risk_reason_codes": list(reasons),
        "stack_decision": decision,
        "block_layer": "none" if decision == "ADMIT" else "momentum",
    }


def _summary(rows: list[dict[str, object]]) -> dict[str, object]:
    return {
        "enabled": True,
        "error": None,
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "changes_readiness_gate": False,
        "changes_closed_trade_readiness_gate": False,
        "overlap_started_at_ms": 500,
        "risk_rejected_rows": rows,
    }


def test_state_round_trip_freezes_five_minute_drawdown_candidate() -> None:
    state = ProspectiveDrawdown5mExecutionState(started_at_ms=1_000)

    restored = ProspectiveDrawdown5mExecutionState.from_payload(
        state.payload()
    )

    assert restored == state
    assert restored.candidate_id == CANDIDATE_ID
    assert restored.exit_horizon_ms == 300_000
    assert restored.payload()["rule"] == {
        "baseline_risk_reason": "weekly_drawdown_lockout",
        "entry_policy": "frozen_full_stack_admit",
        "risk_policy": "neutralize_weekly_drawdown_only",
        "exit_policy": "real_l2_reduce_only_ioc_at_fixed_5m",
        "funding_policy": "exact_captured_hourly_boundaries",
    }


def test_source_exports_only_post_freeze_weekly_stack_admits() -> None:
    state = ProspectiveDrawdown5mExecutionState(started_at_ms=1_000)
    opportunities = (
        _Opportunity("old", 900),
        _Opportunity("candidate", 1_100),
        _Opportunity("blocked", 1_200),
        _Opportunity(
            "other-risk",
            1_300,
            baseline_risk_reason_codes=("stale_market_data",),
        ),
    )
    exit_books = (
        _ExitBook(
            "candidate",
            1_100,
            target_at_ms=301_100,
            observed_at_ms=301_150,
        ),
    )
    funding = (
        _Funding("SOL", 3_600_000),
        _Funding("BTC", 3_600_000),
    )

    payload = prospective_drawdown_5m_execution_source(
        _summary(
            [
                _row("old", 900),
                _row("candidate", 1_100),
                _row("blocked", 1_200, decision="BLOCK"),
                _row(
                    "other-risk",
                    1_300,
                    reasons=("stale_market_data",),
                ),
            ]
        ),
        opportunities,  # type: ignore[arg-type]
        exit_books,  # type: ignore[arg-type]
        funding,  # type: ignore[arg-type]
        PaperExecutionConfig(),
        state,
    )

    assert payload["candidate_id"] == CANDIDATE_ID
    assert payload["started_at_ms"] == 1_000
    assert payload["exit_horizon_ms"] == EXIT_HORIZON_MS
    assert payload["source_opportunity_count"] == 1
    assert payload["discovery_rows_excluded"] == 1
    assert payload["execution_authority"] is False
    assert payload["promotion_authority"] is False
    assert payload["changes_risk_limits"] is False
    rows = payload["opportunities"]
    assert isinstance(rows, list)
    assert rows[0]["opportunity_id"] == "candidate"
    assert rows[0]["exit_book"] is not None
    assert isinstance(payload["source_sha256"], str)


def test_source_rejects_missing_post_freeze_opening_evidence() -> None:
    state = ProspectiveDrawdown5mExecutionState(started_at_ms=1_000)

    try:
        prospective_drawdown_5m_execution_source(
            _summary([_row("candidate", 1_100)]),
            (),
            (),
            (),
            PaperExecutionConfig(),
            state,
        )
    except RuntimeError as exc:
        assert "opening opportunity evidence is missing" in str(exc)
    else:
        raise AssertionError("missing opening evidence must fail closed")
