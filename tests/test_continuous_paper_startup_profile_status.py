"""Surface bounded real PAPER startup delay before profitability judgments."""
from __future__ import annotations

from scripts.render_continuous_paper_live_status import (
    _startup_profile_line,
    render_live_status,
)


def test_real_startup_profile_shows_pre_monitor_total_and_slowest_causes() -> None:
    line = _startup_profile_line({
        "pre_monitor_total": 1_745_234,
        "execution_restore": 700,
        "journal_open": 450,
        "feature_store": 22_500,
        "opening_lineage_store": 1_600_000,
        "facts_open": 580,
        "account_read": 22_500,
        "checkpoint_load": 230,
    })
    assert line == (
        "- PAPER startup pre-monitor / slowest components (non-PnL): "
        "`1745234ms / opening_lineage_store=1600000ms, "
        "account_read=22500ms, feature_store=22500ms, "
        "execution_restore=700ms, facts_open=580ms`"
    )


def test_profile_is_bounded_and_not_controlled_by_untrusted_keys() -> None:
    line = _startup_profile_line({
        "pre_monitor_total": True,
        "secret=abc": 4000000,
        "private/path": 4000000,
        "long" * 40: 4000000,
        "counter": 0,
        "regress": -5,
        "too_huge": 36_000_001,
        "booleans": False,
    })
    assert line.endswith("`unknown / counter=0ms`")
    for secret in ("secret", "private", "longlong", "regress", "too_huge", "booleans"):
        assert secret not in line
    assert _startup_profile_line(None).endswith("`unavailable`")
    assert _startup_profile_line([]).endswith("`unavailable`")


def test_operational_status_exposes_profile_without_promoting_paper() -> None:
    rendered = render_live_status(
        {
            "heartbeat_scope": "operational",
            "timestamp_ms": 1_792_330_000_000,
            "positions": [],
            "recent_closed_trades": [],
            # Minimal synthetic account fixture required by status rendering.
            # No numbers here describe an actual PAPER trade or edge.
            "equity": "10000",
            "cash": "10000",
            "unrealized_pnl": "0",
            "realized_gross_pnl": "0",
            "cumulative_fees": "0",
            "cumulative_funding": "0",
            "closed_trades": 0,
            "execution_healthy": True,
            "selected_market_count": 0,
            "processed_records": 0,
            "journal_observations": 0,
            "startup_component_ms": {
                "pre_monitor_total": 1_500_000,
                "opening_lineage_store": 1_400_000,
                "journal_open": 300,
            },
        },
        run_id="39120486505", head_sha="a" * 40,
        predecessor_run_id="39103876679",
    )
    assert (
        "PAPER startup pre-monitor / slowest components (non-PnL): "
        "`1500000ms / opening_lineage_store=1400000ms, journal_open=300ms`"
    ) in rendered
    assert "PAPER" in rendered
    assert "execution_authority: true" not in rendered
