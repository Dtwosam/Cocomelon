"""Forward v5 market-window accounting must keep actual losses and open marks."""
from __future__ import annotations

from decimal import Decimal

import pytest

from scripts import compare_signed_v5_market_windows as windows


def _report(
    count: int,
    baseline: dict[str, str],
    candidate: dict[str, str],
    *,
    fees: str = "1",
) -> dict[str, object]:
    def lane(values: dict[str, str], prefix: str) -> dict[str, object]:
        pnl = sum((Decimal(v) for v in values.values()), Decimal("0"))
        return {
            "account_state_id": f"{prefix}-{count}",
            "signed_total_account_pnl": str(pnl),
            "signed_equity": str(Decimal("10000") + pnl),
            "fill_fees": fees,
            "funding": "0",
            "markets": values,
        }

    b, c = lane(baseline, "baseline"), lane(candidate, "candidate")
    markets = set(baseline) | set(candidate)
    return {
        "schema_version": 1,
        "kind": windows.KIND,
        "economic_scope": windows.SCOPE,
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "causal_block_credit": False,
        "source_candidate_id": "original-frozen-v5",
        "source_state_digest": f"{count:x}".zfill(64),
        "source_latest_review_row_digest": f"{count + 100:x}".zfill(64),
        "source_record_count": count,
        "baseline": b,
        "candidate": c,
        "candidate_minus_baseline_total_account_pnl": str(
            Decimal(c["signed_total_account_pnl"])
            - Decimal(b["signed_total_account_pnl"])
        ),
        "by_market": {
            market: {
                "baseline_account_pnl": baseline.get(market, "0"),
                "candidate_account_pnl": candidate.get(market, "0"),
                "candidate_minus_baseline": str(
                    Decimal(candidate.get(market, "0"))
                    - Decimal(baseline.get(market, "0"))
                ),
            }
            for market in markets
        },
    }


def test_actual_market_window_counts_displaced_winner_and_recovering_mark() -> None:
    first = _report(
        10,
        {"PONS": "7", "NEAR": "-10"},
        {"ZK": "-2", "NEAR": "-10", "PUMP": "-10"},
        fees="1",
    )
    second = _report(
        20,
        {"PONS": "16", "NEAR": "-10"},
        {"ZK": "8", "NEAR": "-10", "PUMP": "-10"},
        fees="2",
    )
    result = windows.compare(first, second)
    assert result["baseline"]["marked_account_pnl_change"] == "9"
    assert result["candidate"]["marked_account_pnl_change"] == "10"
    assert result["candidate_minus_baseline_window_pnl"] == "1"
    assert result["by_market"]["PONS"]["candidate_minus_baseline_window_pnl"] == "-9"
    assert result["by_market"]["ZK"]["candidate_minus_baseline_window_pnl"] == "10"
    assert result["largest_candidate_disadvantages"] == ["PONS"]
    assert result["baseline"]["paid_fees_in_window"] == "1"
    assert result["verified_review_ledger_contiguity"] is False
    assert result["not_frozen_anchor_review"] is True
    assert result["promotion_authority"] is False


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    (
        ("source_candidate_id", "different-freeze", "frozen candidate changed"),
        ("source_record_count", 9, "out of order"),
        ("source_state_digest", "0" * 64, "repeated source state"),
        ("research_only", False, "invalid research_only"),
        ("source_latest_review_row_digest", "broken", "invalid source_latest"),
    ),
)
def test_reject_forged_or_nonforward_signed_reference(
    field: str, value: object, reason: str,
) -> None:
    first = _report(10, {"PONS": "7"}, {"ZK": "-2"})
    second = _report(20, {"PONS": "16"}, {"ZK": "8"})
    second[field] = first[field] if field == "source_state_digest" else value
    with pytest.raises(windows.V5WindowComparisonError, match=reason):
        windows.compare(first, second)


def test_market_or_lane_inconsistency_fails_closed() -> None:
    first = _report(10, {"PONS": "7"}, {"ZK": "-2"})
    second = _report(20, {"PONS": "16"}, {"ZK": "8"})
    second["by_market"]["ZK"]["candidate_minus_baseline"] = "999"
    with pytest.raises(windows.V5WindowComparisonError, match="does not reconcile"):
        windows.compare(first, second)

    second = _report(20, {"PONS": "16"}, {"ZK": "8"})
    second["candidate"]["signed_total_account_pnl"] = "900"
    with pytest.raises(windows.V5WindowComparisonError, match="market PnL"):
        windows.compare(first, second)

    second = _report(20, {"PONS": "16"}, {"ZK": "8"})
    second["candidate"]["markets"]["ZK"] = "NaN"
    with pytest.raises(windows.V5WindowComparisonError, match="nonfinite"):
        windows.compare(first, second)


def test_cannot_hide_fee_growth_or_account_reset() -> None:
    first = _report(10, {"PONS": "7"}, {"ZK": "-2"}, fees="2")
    second = _report(20, {"PONS": "16"}, {"ZK": "8"}, fees="1")
    with pytest.raises(windows.V5WindowComparisonError, match="fees decreased"):
        windows.compare(first, second)

    second = _report(20, {"PONS": "16"}, {"ZK": "8"}, fees="3")
    second["candidate"]["signed_equity"] = "1"
    with pytest.raises(windows.V5WindowComparisonError, match="starting cash"):
        windows.compare(first, second)


def test_actual_candidate_gain_smaller_than_baseline_is_not_an_edge() -> None:
    first = _report(5, {"PONS": "0"}, {"ZK": "0"}, fees="0")
    second = _report(10, {"PONS": "20"}, {"ZK": "8"}, fees="2")
    result = windows.compare(first, second)
    assert result["candidate_minus_baseline_window_pnl"] == "-12"
    assert result["candidate_minus_baseline_cumulative_pnl_at_end"] == "-12"
    assert "hypothetical_saved_pnl" not in result
    assert result["execution_authority"] is False
