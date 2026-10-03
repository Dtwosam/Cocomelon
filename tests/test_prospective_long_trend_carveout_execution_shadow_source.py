from __future__ import annotations

from dataclasses import dataclass

import pytest

from cocomelon.domain.execution import PaperExecutionConfig
from cocomelon.research.prospective_long_trend_carveout_execution_shadow_source import (
    ProspectiveLongTrendExecutionShadowSourceError,
    prospective_long_trend_execution_shadow_source,
)


@dataclass(frozen=True)
class _Evidence:
    opportunity_id: str
    opportunity_timestamp_ms: int = 1_000_000
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
        }


@dataclass(frozen=True)
class _Path:
    opportunity_id: str
    market: str = "SOL"
    direction: str = "long"
    opportunity_timestamp_ms: int = 1_000_000

    def to_dict(self) -> dict[str, object]:
        return {
            "opportunity_id": self.opportunity_id,
            "market": self.market,
            "direction": self.direction,
            "opportunity_timestamp_ms": self.opportunity_timestamp_ms,
            "marks": [],
        }


def _summary(*, reason: str = "long_trend") -> dict[str, object]:
    return {
        "enabled": True,
        "error": None,
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "changes_readiness_gate": False,
        "changes_closed_trade_readiness_gate": False,
        "overlap_started_at_ms": 900_000,
        "risk_rejected_rows": [
            {
                "opportunity_id": "op-1",
                "timestamp_ms": 1_000_000,
                "market": "SOL",
                "direction": "long",
                "lead_strategy": "trend",
                "rank_ordinal": 3,
                "rank_age_ms": 100,
                "baseline_risk_reason_codes": [
                    "weekly_drawdown_lockout"
                ],
                "combined_block_reason": reason,
                "two_strike_prior_strikes": 0,
                "stack_decision": "BLOCK",
                "block_layer": "combined",
                "long_trend_carveout_candidate_id": (
                    "prospective-top10-two-strike-momentum-no-long-trend-v1"
                ),
                "long_trend_carveout_decision": "ADMIT",
                "long_trend_carveout_block_layer": "none",
                "long_trend_carveout_momentum_decision": "ADMIT",
                "long_trend_carveout_momentum_reason": "momentum_band_admit",
            }
        ],
    }


def test_source_exports_only_reopened_weekly_long_trend() -> None:
    payload = prospective_long_trend_execution_shadow_source(
        _summary(),
        (_Evidence("op-1"),),  # type: ignore[arg-type]
        (_Path("op-1"),),  # type: ignore[arg-type]
        PaperExecutionConfig(),
    )

    assert payload["schema_version"] == 2
    assert payload["kind"].endswith("-v2")
    assert payload["execution_config"]["config_version"] == "phase7-v1"
    assert isinstance(payload["execution_config_sha256"], str)
    assert payload["source_opportunity_count"] == 1
    assert payload["missing_opportunity_evidence"] == 0
    assert payload["missing_forward_paths"] == 0
    assert payload["execution_authority"] is False
    assert payload["changes_execution"] is False
    assert payload["changes_risk_limits"] is False
    rows = payload["opportunities"]
    assert isinstance(rows, list)
    assert rows[0]["opportunity_id"] == "op-1"
    assert rows[0]["path"] is not None
    assert isinstance(payload["source_sha256"], str)


def test_source_skips_non_pure_long_trend_blocks() -> None:
    payload = prospective_long_trend_execution_shadow_source(
        _summary(reason="long_trend_and_rank_above_10"),
        (_Evidence("op-1"),),  # type: ignore[arg-type]
        (_Path("op-1"),),  # type: ignore[arg-type]
        PaperExecutionConfig(),
    )

    assert payload["source_opportunity_count"] == 0


def test_source_rejects_non_weekly_lineage() -> None:
    summary = _summary()
    rows = summary["risk_rejected_rows"]
    assert isinstance(rows, list)
    rows[0]["baseline_risk_reason_codes"] = ["daily_loss_lockout"]

    payload = prospective_long_trend_execution_shadow_source(
        summary,
        (_Evidence("op-1"),),  # type: ignore[arg-type]
        (_Path("op-1"),),  # type: ignore[arg-type]
        PaperExecutionConfig(),
    )

    assert payload["source_opportunity_count"] == 0


def test_source_fails_closed_on_opportunity_lineage_drift() -> None:
    with pytest.raises(
        ProspectiveLongTrendExecutionShadowSourceError,
        match="opportunity lineage mismatch",
    ):
        prospective_long_trend_execution_shadow_source(
            _summary(),
            (
                _Evidence(
                    "op-1",
                    direction="short",
                ),
            ),  # type: ignore[arg-type]
            (),  # type: ignore[arg-type]
            PaperExecutionConfig(),
        )


def test_source_fails_closed_when_reopened_opportunity_is_missing() -> None:
    with pytest.raises(
        ProspectiveLongTrendExecutionShadowSourceError,
        match="opportunity evidence is missing",
    ):
        prospective_long_trend_execution_shadow_source(
            _summary(),
            (),  # type: ignore[arg-type]
            (),  # type: ignore[arg-type]
            PaperExecutionConfig(),
        )
