"""Conservative same-reader quota screen for an optional REST depth observer.

This is a LOCAL historical peak projection only, never a certificate of
public-IP headroom, future request rates, feed quality or trading authority.
"""
from __future__ import annotations

from dataclasses import dataclass

# Frozen three markets, one 2-weight read/second each for a 60-second window.
THREE_MARKET_SHADOW_WEIGHT = 360


@dataclass(frozen=True)
class LocalRestShadowScreen:
    permitted: bool
    reason: str
    projected_peak_weight: int | None = None
    local_limit: int | None = None


def screen_local_rest_shadow_headroom(raw: object) -> LocalRestShadowScreen:
    """Reject a shadow startup unless measured same-reader peaks leave reserve.

    The dynamic request admission ledger still protects the real worker after
    startup. A passing local screen does NOT establish IP-wide quota safety.
    """
    if not isinstance(raw, dict):
        return LocalRestShadowScreen(False, "missing_local_reader_snapshot")
    if (
        raw.get("external_process_ip_weight_verified") is not False
        or raw.get("source_or_execution_authority") is not False
    ):
        return LocalRestShadowScreen(False, "unsupported_authority_claim")

    keys = (
        "rolling_window_seconds", "rolling_weight_limit",
        "total_rolling_weight", "required_rolling_weight",
        "shadow_rolling_weight", "other_rolling_weight",
        "peak_total_rolling_weight", "peak_required_rolling_weight",
        "peak_shadow_rolling_weight", "shadow_priority_reserve_weight",
    )
    if any(type(raw.get(k)) is not int or raw[k] < 0 for k in keys):
        return LocalRestShadowScreen(False, "invalid_local_counters")
    window = raw["rolling_window_seconds"]
    limit = raw["rolling_weight_limit"]
    total = raw["total_rolling_weight"]
    required = raw["required_rolling_weight"]
    shadow = raw["shadow_rolling_weight"]
    other = raw["other_rolling_weight"]
    peak = raw["peak_total_rolling_weight"]
    required_peak = raw["peak_required_rolling_weight"]
    shadow_peak = raw["peak_shadow_rolling_weight"]
    reserve = raw["shadow_priority_reserve_weight"]
    if (
        window != 60 or not 0 < limit <= 1000
        or reserve != min(300, limit // 3)
        or total != required + shadow + other
        or total > peak or peak > limit
        or required > required_peak or required_peak > peak
        or shadow > shadow_peak or shadow_peak > peak
    ):
        return LocalRestShadowScreen(False, "inconsistent_or_unsafe_local_budget")
    if required_peak == 0:
        return LocalRestShadowScreen(False, "no_mandatory_request_baseline")
    if shadow_peak != 0:
        return LocalRestShadowScreen(False, "not_a_shadow_free_baseline")
    projected = peak + THREE_MARKET_SHADOW_WEIGHT + reserve
    if projected > limit:
        return LocalRestShadowScreen(
            False, "insufficient_peak_headroom", projected, limit
        )
    return LocalRestShadowScreen(
        True, "local_screen_only_ip_unverified", projected, limit
    )
