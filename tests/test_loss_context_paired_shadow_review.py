from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from cocomelon.research.historical_discovery_freeze import (
    MIN_PROSPECTIVE_EMBARGO_MS,
)
from cocomelon.research.loss_context_paired_shadow_review import (
    LossContextPairedShadowReviewError,
    append_review_checkpoint,
    build_paired_shadow_review,
    verify_review_ledger,
)
from cocomelon.research.loss_context_portfolio_shadow_candidate import (
    LossContextPortfolioShadowFreeze,
)

FROZEN_AT_MS = 1_000
PROSPECTIVE_MS = FROZEN_AT_MS + MIN_PROSPECTIVE_EMBARGO_MS
NINE_HOURS_MS = 9 * 60 * 60 * 1000


def _freeze() -> LossContextPortfolioShadowFreeze:
    return LossContextPortfolioShadowFreeze(
        loss_context_candidate_id="a" * 64,
        source_composition_digest="b" * 64,
        source_max_timestamp_ms=900,
        source_paper_run_id=123,
        source_paper_run_attempt=1,
        source_paper_head_sha="c" * 40,
        dimensions=("lead_strategy", "trend_regime"),
        values=("mean_reversion", "down"),
        horizons_ms=(300_000, 900_000),
        frozen_at_ms=FROZEN_AT_MS,
        prospective_not_before_ms=PROSPECTIVE_MS,
    )


def _checkpoint(
    freeze: LossContextPortfolioShadowFreeze,
    *,
    index: int,
    candidate_profitable: bool = True,
    concentrated: bool = False,
) -> dict[str, object]:
    matching = 4 * index
    if concentrated:
        blocked = {
            "AAA": 3 * index,
            "BBB": index,
        }
    else:
        blocked = {
            "AAA": index,
            "BBB": index,
            "CCC": index,
            "DDD": index,
        }

    baseline_total = -2 * index
    baseline_realized = -2 * index
    if candidate_profitable:
        candidate_total = 3 * index
        candidate_realized = 2 * index
    else:
        candidate_total = -index
        candidate_realized = -index

    return {
        "portfolio_shadow_candidate_id": freeze.candidate_id,
        "loss_context_candidate_id": freeze.loss_context_candidate_id,
        "prospective_not_before_ms": freeze.prospective_not_before_ms,
        "end_ms": PROSPECTIVE_MS + index * NINE_HOURS_MS,
        "record_count": index * 1_000,
        "data_gap_closed_count": 0,
        "data_gap_closed_duration_ms": 0,
        "data_gap_open_count": 0,
        "last_record_available_at_ms": (
            PROSPECTIVE_MS + index * NINE_HOURS_MS
        ),
        "baseline": {
            "closed_trade_count": 4 * index,
            "equity": str(10_000 + baseline_total),
            "total_account_pnl": str(baseline_total),
            "realized_net_pnl": str(baseline_realized),
            "max_drawdown_fraction": "0.04",
        },
        "candidate": {
            "closed_trade_count": 4 * index,
            "equity": str(10_000 + candidate_total),
            "total_account_pnl": str(candidate_total),
            "realized_net_pnl": str(candidate_realized),
            "max_drawdown_fraction": "0.02",
        },
        "candidate_minus_baseline_equity": str(
            candidate_total - baseline_total
        ),
        "candidate_minus_baseline_total_account_pnl": str(
            candidate_total - baseline_total
        ),
        "candidate_minus_baseline_realized_net_pnl": str(
            candidate_realized - baseline_realized
        ),
        "candidate_minus_baseline_max_drawdown_fraction": "-0.02",
        "baseline_admission": {
            "matching_context_blocked": 0,
            "matching_context_blocked_by_market": {},
        },
        "candidate_admission": {
            "matching_context_blocked": matching,
            "matching_context_blocked_by_market": blocked,
        },
        "research_only": True,
        "shadow_only": True,
        "changes_strategy": False,
        "changes_risk_limits": False,
        "changes_positions": False,
        "promotion_authority": False,
        "execution_authority": False,
    }


def _write_campaign(
    path: Path,
    freeze: LossContextPortfolioShadowFreeze,
    *,
    candidate_profitable: bool = True,
    concentrated: bool = False,
) -> None:
    for index in range(1, 10):
        append_review_checkpoint(
            path,
            _checkpoint(
                freeze,
                index=index,
                candidate_profitable=candidate_profitable,
                concentrated=concentrated,
            ),
        )


def test_paired_shadow_review_requires_real_profit_and_three_clean_blocks(
    tmp_path: Path,
) -> None:
    freeze = _freeze()
    ledger = tmp_path / "review.jsonl"
    _write_campaign(ledger, freeze)

    report = build_paired_shadow_review(freeze, ledger)

    assert report["ready_for_review"] is True
    assert report["readiness_failures"] == ()
    assert report["eligible_checkpoint_count"] == 9
    assert report["evidence_checkpoint_count"] == 8
    assert report["review_anchor_end_ms"] == (
        PROSPECTIVE_MS + NINE_HOURS_MS
    )
    assert report["matching_context_blocks"] == 32
    assert report["blocked_market_count"] == 4
    assert report["candidate_closed_trade_count"] == 32
    assert report["baseline_closed_trade_count"] == 32
    assert report["candidate_total_account_pnl"] == "27"
    assert report["candidate_realized_net_pnl"] == "18"
    blocks = report["chronological_blocks"]
    assert isinstance(blocks, tuple)
    assert len(blocks) == 3
    assert all(block["passes"] is True for block in blocks)
    assert report["changes_strategy"] is False
    assert report["promotion_authority"] is False
    assert report["execution_authority"] is False


def test_paired_shadow_review_rejects_candidate_that_is_only_less_bad(
    tmp_path: Path,
) -> None:
    freeze = _freeze()
    ledger = tmp_path / "review.jsonl"
    _write_campaign(
        ledger,
        freeze,
        candidate_profitable=False,
    )

    report = build_paired_shadow_review(freeze, ledger)

    failures = report["readiness_failures"]
    assert isinstance(failures, tuple)
    assert "candidate_total_account_pnl_not_positive" in failures
    assert "candidate_realized_net_pnl_not_positive" in failures
    assert report["ready_for_review"] is False


def test_paired_shadow_review_rejects_one_market_concentration(
    tmp_path: Path,
) -> None:
    freeze = _freeze()
    ledger = tmp_path / "review.jsonl"
    _write_campaign(
        ledger,
        freeze,
        concentrated=True,
    )

    report = build_paired_shadow_review(freeze, ledger)

    failures = report["readiness_failures"]
    assert isinstance(failures, tuple)
    assert "blocked_context_market_concentration_too_high" in failures
    assert report["ready_for_review"] is False


def test_paired_shadow_review_ledger_detects_tampering(
    tmp_path: Path,
) -> None:
    freeze = _freeze()
    ledger = tmp_path / "review.jsonl"
    _write_campaign(ledger, freeze)

    lines = ledger.read_text(encoding="utf-8").splitlines()
    row = json.loads(lines[3])
    row["candidate_minus_baseline_total_account_pnl"] = "999"
    lines[3] = json.dumps(row, sort_keys=True, separators=(",", ":"))
    ledger.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(
        LossContextPairedShadowReviewError,
        match="row digest mismatch",
    ):
        verify_review_ledger(
            ledger,
            candidate_id=freeze.candidate_id,
        )


@pytest.mark.parametrize(
    "field",
    (
        "candidate_minus_baseline_equity",
        "candidate_minus_baseline_total_account_pnl",
        "candidate_minus_baseline_realized_net_pnl",
        "candidate_minus_baseline_max_drawdown_fraction",
    ),
)
def test_paired_shadow_review_rejects_invented_account_advantage(
    tmp_path: Path,
    field: str,
) -> None:
    freeze = _freeze()
    row = _checkpoint(freeze, index=1)
    row[field] = "999"
    ledger = tmp_path / "review.jsonl"

    with pytest.raises(
        LossContextPairedShadowReviewError,
        match="review ledger account delta mismatch",
    ):
        append_review_checkpoint(ledger, row)
    assert not ledger.exists()


@pytest.mark.parametrize(
    ("blocked", "unattributed"),
    ((3, 0), (4, 2)),
)
def test_paired_shadow_review_rejects_inconsistent_market_attribution(
    tmp_path: Path,
    blocked: int,
    unattributed: int,
) -> None:
    freeze = _freeze()
    row = _checkpoint(freeze, index=1)
    admission = row["candidate_admission"]
    assert isinstance(admission, dict)
    admission["matching_context_blocked"] = blocked
    admission["matching_context_blocked_unattributed"] = unattributed
    ledger = tmp_path / "review.jsonl"

    with pytest.raises(
        LossContextPairedShadowReviewError,
        match="matching-context block totals do not reconcile",
    ):
        append_review_checkpoint(ledger, row)
    assert not ledger.exists()


def test_paired_shadow_review_rejects_changed_freeze_lineage(
    tmp_path: Path,
) -> None:
    freeze = _freeze()
    ledger = tmp_path / "review.jsonl"
    append_review_checkpoint(ledger, _checkpoint(freeze, index=1))
    original = ledger.read_bytes()
    second = _checkpoint(freeze, index=2)
    second["loss_context_candidate_id"] = "d" * 64

    with pytest.raises(
        LossContextPairedShadowReviewError,
        match="review ledger frozen candidate lineage changed",
    ):
        append_review_checkpoint(ledger, second)
    assert ledger.read_bytes() == original


def test_paired_shadow_review_rejects_record_counter_regression(
    tmp_path: Path,
) -> None:
    freeze = _freeze()
    ledger = tmp_path / "review.jsonl"
    append_review_checkpoint(ledger, _checkpoint(freeze, index=1))
    original = ledger.read_bytes()
    second = _checkpoint(freeze, index=2)
    second["record_count"] = 999

    with pytest.raises(
        LossContextPairedShadowReviewError,
        match="review ledger record count moved backward",
    ):
        append_review_checkpoint(ledger, second)
    assert ledger.read_bytes() == original


def test_paired_review_rejects_forward_market_gaps_above_one_percent(
    tmp_path: Path,
) -> None:
    freeze = _freeze()
    ledger = tmp_path / "review.jsonl"
    for index in range(1, 10):
        row = _checkpoint(freeze, index=index)
        row["data_gap_closed_count"] = 10 * index
        row["data_gap_closed_duration_ms"] = 2_000_000 * index
        append_review_checkpoint(ledger, row)
    report = build_paired_shadow_review(freeze, ledger)
    assert report["ready_for_review"] is False
    assert "excessive_forward_market_data_gaps" in report["readiness_failures"]
    assert report["forward_market_data_gap_duration_ms"] == 16_000_000
    assert Decimal(report["forward_market_data_gap_fraction"]) > Decimal("0.01")


def test_paired_review_refuses_missing_prospective_gap_evidence(
    tmp_path: Path,
) -> None:
    freeze = _freeze()
    ledger = tmp_path / "review.jsonl"
    for index in range(1, 10):
        row = _checkpoint(freeze, index=index)
        if index == 1:
            for key in (
                "data_gap_closed_count",
                "data_gap_closed_duration_ms",
                "data_gap_open_count",
            ):
                row.pop(key)
        append_review_checkpoint(ledger, row)
    report = build_paired_shadow_review(freeze, ledger)
    assert report["ready_for_review"] is False
    assert "missing_forward_market_data_gap_evidence" in report["readiness_failures"]


def test_paired_review_refuses_open_gap_at_final_checkpoint(
    tmp_path: Path,
) -> None:
    freeze = _freeze()
    ledger = tmp_path / "review.jsonl"
    for index in range(1, 10):
        row = _checkpoint(freeze, index=index)
        if index == 9:
            row["data_gap_open_count"] = 1
        append_review_checkpoint(ledger, row)
    report = build_paired_shadow_review(freeze, ledger)
    assert report["ready_for_review"] is False
    assert "market_data_gap_still_open" in report["readiness_failures"]


def test_paired_review_rejects_partial_gap_evidence(
    tmp_path: Path,
) -> None:
    freeze = _freeze()
    ledger = tmp_path / "review.jsonl"
    row = _checkpoint(freeze, index=1)
    row.pop("data_gap_open_count")
    with pytest.raises(
        LossContextPairedShadowReviewError,
        match="partial market-data gap evidence",
    ):
        append_review_checkpoint(ledger, row)
    assert not ledger.exists()


def test_paired_review_rejects_gap_counter_regression(
    tmp_path: Path,
) -> None:
    freeze = _freeze()
    ledger = tmp_path / "review.jsonl"
    first = _checkpoint(freeze, index=1)
    first["data_gap_closed_duration_ms"] = 1000
    append_review_checkpoint(ledger, first)
    second = _checkpoint(freeze, index=2)
    second["data_gap_closed_duration_ms"] = 999
    with pytest.raises(
        LossContextPairedShadowReviewError,
        match="market-data closed gap duration",
    ):
        append_review_checkpoint(ledger, second)
