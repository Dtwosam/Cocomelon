from __future__ import annotations

from collections.abc import Mapping

from cocomelon.config import Settings
from cocomelon.domain.market import MarketId
from cocomelon.domain.risk import RiskLimits

DEFAULT_CRYPTO_BUCKET = "crypto_beta"


def default_correlation_bucket(_: MarketId) -> str:
    return DEFAULT_CRYPTO_BUCKET


def correlation_bucket(
    market: MarketId,
    overrides: Mapping[str, str] | None = None,
) -> str:
    if overrides is not None and market.canonical in overrides:
        value = overrides[market.canonical].strip()
        if not value:
            raise ValueError("correlation bucket override must not be empty")
        return value
    return default_correlation_bucket(market)


def limits_from_settings(settings: Settings) -> RiskLimits:
    return RiskLimits(
        risk_per_trade=settings.risk_per_trade,
        max_open_risk=settings.max_open_risk,
        daily_loss_limit=settings.daily_loss_limit,
        weekly_drawdown_limit=settings.weekly_drawdown_limit,
        consecutive_loss_cooldown=settings.consecutive_loss_cooldown,
        cooldown_ms=settings.cooldown_ms,
        correlation_bucket_risk_limit=settings.correlation_bucket_risk_limit,
        max_gross_leverage=settings.max_gross_leverage,
        max_available_margin_fraction=settings.max_available_margin_fraction,
        max_visible_depth_fraction=settings.max_visible_depth_fraction,
        min_liquidation_stop_multiple=settings.min_liquidation_stop_multiple,
        max_state_age_ms=settings.max_state_age_ms,
    )
