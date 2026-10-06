from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest

from cocomelon.research import prospective_correlation_bucket_priority as audit
from cocomelon.research.continuous_paper_learning import (
    ContinuousPaperOpeningLineage,
    ContinuousPaperRuntimeIdentity,
)
from cocomelon.research.continuous_paper_opening_rank import (
    ContinuousPaperOpeningRankEvidence,
)
from cocomelon.research.prospective_capacity_reflow_opportunities import (
    CapacityReleaseOpportunityOption,
)


def _lineage(plan_id: str, market: str, opened_at_ms: int) -> ContinuousPaperOpeningLineage:
    return ContinuousPaperOpeningLineage(
        opening_plan_id=plan_id,
        feature_snapshot_id=f"feature-{plan_id}",
        market=market,
        opened_at_ms=opened_at_ms,
        runtime=ContinuousPaperRuntimeIdentity(
            worker_run_id=1,
            worker_run_attempt=1,
            worker_head_sha="a" * 40,
        ),
    )


def _rank(
    plan_id: str,
    market: str,
    opened_at_ms: int,
    ordinal: int,
    score: str,
) -> ContinuousPaperOpeningRankEvidence:
    return ContinuousPaperOpeningRankEvidence(
        opening_plan_id=plan_id,
        market=market,
        opened_at_ms=opened_at_ms,
        rank_observed_at_ms=opened_at_ms - 100,
        rank_age_ms=100,
        ordinal=ordinal,
        score=Decimal(score),
        rank_pool_size=20,
        reason_codes=("ranked",),
    )


def _evidence(
    opportunity_id: str,
    *,
    timestamp_ms: int,
    market: str,
    ordinal: int,
    score: str,
) -> SimpleNamespace:
    return SimpleNamespace(
        opportunity_id=opportunity_id,
        opportunity_timestamp_ms=timestamp_ms,
        market=market,
        direction="short",
        lead_strategy="mean_reversion",
        rank_ordinal=ordinal,
        rank_score=Decimal(score),
        rank_observed_at_ms=timestamp_ms - 100,
        rank_pool_size=20,
    )


def _row(
    opportunity_id: str,
    *,
    timestamp_ms: int,
    market: str,
    stack_decision: str = "ADMIT",
    reason: str = "correlation_bucket_exhausted",
    return_15m: str = "0.01",
) -> dict[str, object]:
    return {
        "opportunity_id": opportunity_id,
        "timestamp_ms": timestamp_ms,
        "market": market,
        "direction": "short",
        "stack_decision": stack_decision,
        "baseline_risk_reason_codes": (reason,),
        "markouts": {
            "300000": {
                "status": "settled",
                "directional_return": "0.001",
            },
            "900000": {
                "status": "settled",
                "directional_return": return_15m,
            },
            "3600000": {
                "status": "pending",
                "directional_return": None,
            },
        },
    }


def test_priority_audit_separates_better_and_worse_newcomers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opportunities = (
        _evidence(
            "opp-better",
            timestamp_ms=10_000,
            market="MON",
            ordinal=2,
            score="0.90",
        ),
        _evidence(
            "opp-worse",
            timestamp_ms=20_000,
            market="ONDO",
            ordinal=8,
            score="0.55",
        ),
    )
    releases = {
        "opp-better": (
            CapacityReleaseOpportunityOption(
                opportunity_id="opp-better",
                opportunity_timestamp_ms=10_000,
                opportunity_market="MON",
                release_market="BTC",
                release_correlation_bucket="majors",
            ),
        ),
        "opp-worse": (
            CapacityReleaseOpportunityOption(
                opportunity_id="opp-worse",
                opportunity_timestamp_ms=20_000,
                opportunity_market="ONDO",
                release_market="ETH",
                release_correlation_bucket="majors",
            ),
        ),
    }
    monkeypatch.setattr(
        audit,
        "single_position_capacity_release_options",
        lambda evidence: releases[evidence.opportunity_id],
    )

    lineages = (
        _lineage("plan-btc", "BTC", 5_000),
        _lineage("plan-eth", "ETH", 15_000),
    )
    ranks = {
        "plan-btc": _rank("plan-btc", "BTC", 5_000, 9, "0.40"),
        "plan-eth": _rank("plan-eth", "ETH", 15_000, 2, "0.92"),
    }
    forward = {
        "execution_authority": False,
        "risk_rejected_rows": [
            _row(
                "opp-better",
                timestamp_ms=10_000,
                market="MON",
                return_15m="0.02",
            ),
            _row(
                "opp-worse",
                timestamp_ms=20_000,
                market="ONDO",
                return_15m="-0.01",
            ),
            _row(
                "ignored-block",
                timestamp_ms=30_000,
                market="PONS",
                stack_decision="BLOCK",
            ),
        ],
    }

    result = audit.prospective_correlation_bucket_priority_summary(
        forward,
        opportunities,
        lineages,
        (),
        rank_loader=ranks.get,
    )

    assert result["stack_admitted_correlation_rejections"] == 2
    assert result["releasable_holder_options"] == 2
    assert result["opportunities_outranking_any_releasable_holder"] == 1
    rows = result["opportunities"]
    assert isinstance(rows, tuple)
    assert rows[0]["market"] == "MON"
    assert rows[0]["newcomer_outranks_any_releasable_holder"] is True
    assert rows[0]["releasable_holders"][0]["newcomer_rank_advantage"] == 7
    assert rows[1]["newcomer_outranks_any_releasable_holder"] is False

    horizon = result["by_horizon"]["900000"]
    assert horizon["priority_improves"]["settled"] == 1
    assert horizon["priority_improves"]["mean_directional_return"] == "0.02"
    assert horizon["priority_not_improved"]["settled"] == 1
    assert (
        horizon["priority_not_improved"]["mean_directional_return"]
        == "-0.01"
    )
    assert result["execution_authority"] is False
    assert result["changes_risk_limits"] is False
    assert result["changes_entry_priority"] is False
    assert result["replacement_execution_modeled"] is False


def test_priority_audit_ignores_other_risk_reasons(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        audit,
        "single_position_capacity_release_options",
        lambda _evidence: (),
    )
    evidence = _evidence(
        "cooldown",
        timestamp_ms=10_000,
        market="MON",
        ordinal=1,
        score="0.9",
    )

    result = audit.prospective_correlation_bucket_priority_summary(
        {
            "execution_authority": False,
            "risk_rejected_rows": [
                _row(
                    "cooldown",
                    timestamp_ms=10_000,
                    market="MON",
                    reason="consecutive_loss_cooldown",
                )
            ],
        },
        (evidence,),
        (),
        (),
        rank_loader=lambda _plan_id: None,
    )

    assert result["stack_admitted_correlation_rejections"] == 0


def test_priority_audit_fails_closed_on_missing_holder_rank(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence = _evidence(
        "opp",
        timestamp_ms=10_000,
        market="MON",
        ordinal=2,
        score="0.9",
    )
    monkeypatch.setattr(
        audit,
        "single_position_capacity_release_options",
        lambda _evidence: (
            CapacityReleaseOpportunityOption(
                opportunity_id="opp",
                opportunity_timestamp_ms=10_000,
                opportunity_market="MON",
                release_market="BTC",
                release_correlation_bucket="majors",
            ),
        ),
    )

    with pytest.raises(
        audit.ProspectiveCorrelationBucketPriorityError,
        match="opening rank is missing",
    ):
        audit.prospective_correlation_bucket_priority_summary(
            {
                "execution_authority": False,
                "risk_rejected_rows": [
                    _row(
                        "opp",
                        timestamp_ms=10_000,
                        market="MON",
                    )
                ],
            },
            (evidence,),
            (_lineage("plan-btc", "BTC", 5_000),),
            (),
            rank_loader=lambda _plan_id: None,
        )
