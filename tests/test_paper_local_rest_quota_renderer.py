from __future__ import annotations

from scripts.render_continuous_paper_live_status import _local_rest_budget_lines


def test_read_only_paper_status_formats_required_shadow_and_other_rest_weight() -> None:
    rows = _local_rest_budget_lines({
        "rolling_weight_limit": 1000,
        "total_rolling_weight": 126,
        "required_rolling_weight": 120,
        "shadow_rolling_weight": 6,
        "other_rolling_weight": 0,
        "peak_total_rolling_weight": 180,
        "shadow_priority_reserve_weight": 300,
        "shadow_denied_lifetime": 2,
        "external_process_ip_weight_verified": False,
        "source_or_execution_authority": False,
    })
    text = "\n".join(rows)
    assert "126 / 1000" in text
    assert "120 / 6 / 0" in text
    assert "180 / 300" in text
    assert "since startup: `2`" in text
    assert "NOT A SHARED-IP CERTIFICATE" in text
    assert "unverified" in text
    assert "not authorized" in text


def test_prior_worker_without_rest_snapshot_is_labeled_unknown() -> None:
    text = "\n".join(_local_rest_budget_lines(None))
    assert "not yet reported by this worker" in text
    assert "unverified" in text
    assert "0 / 1000" not in text


def test_forged_ip_certification_is_rejected_before_display() -> None:
    text = "\n".join(_local_rest_budget_lines({
        "external_process_ip_weight_verified": True,
        "source_or_execution_authority": False,
    }))
    assert "INVALID: unsupported authority claim" in text
    assert "unverified" in text


def test_malformed_or_nonadditive_local_counters_are_invalid() -> None:
    base: dict[str, object] = {
        "rolling_weight_limit": 1000,
        "total_rolling_weight": 50,
        "required_rolling_weight": 40,
        "shadow_rolling_weight": 0,
        "other_rolling_weight": 0,
        "peak_total_rolling_weight": 50,
        "shadow_priority_reserve_weight": 300,
        "shadow_denied_lifetime": 0,
        "external_process_ip_weight_verified": False,
        "source_or_execution_authority": False,
    }
    text = "\n".join(_local_rest_budget_lines(base))
    assert "INVALID: inconsistent local counters" in text
    corrected = {**base, "total_rolling_weight": True}
    text2 = "\n".join(_local_rest_budget_lines(corrected))
    assert "INVALID: missing or malformed counters" in text2


def test_rest_quota_renderer_blocks_shadow_when_historical_peak_is_full() -> None:
    rows = _local_rest_budget_lines({
        "rolling_window_seconds": 60,
        "rolling_weight_limit": 1000,
        "total_rolling_weight": 400,
        "required_rolling_weight": 400,
        "shadow_rolling_weight": 0,
        "other_rolling_weight": 0,
        "peak_total_rolling_weight": 987,
        "peak_required_rolling_weight": 987,
        "peak_shadow_rolling_weight": 0,
        "shadow_priority_reserve_weight": 300,
        "shadow_denied_lifetime": 0,
        "external_process_ip_weight_verified": False,
        "source_or_execution_authority": False,
    })
    text = "\\n".join(rows)
    assert "new 3-market observer startup: `BLOCKED`" in text
    assert "insufficient_peak_headroom" in text
    assert "1647 / 1000" in text
    assert "other processes behind public IP: `unverified`" in text
