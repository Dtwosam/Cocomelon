import importlib
from decimal import Decimal

from cocomelon.config import Settings
from cocomelon.domain.market import MarketId


def _module():
    return importlib.import_module("cocomelon.risk.policy")


def test_all_unclassified_crypto_markets_default_to_shared_crypto_beta_bucket() -> None:
    policy = _module()

    assert policy.default_correlation_bucket(MarketId("", "BTC")) == "crypto_beta"
    assert policy.default_correlation_bucket(MarketId("", "ETH")) == "crypto_beta"
    assert policy.default_correlation_bucket(MarketId("xyz", "NVDA")) == "crypto_beta"


def test_explicit_override_is_separate_from_default_policy() -> None:
    policy = _module()
    market = MarketId("", "BTC")

    assert policy.correlation_bucket(market, {"BTC": "btc_specific"}) == "btc_specific"
    assert policy.default_correlation_bucket(market) == "crypto_beta"


def test_limits_from_settings_preserves_exact_decimal_values() -> None:
    policy = _module()
    settings = Settings(
        risk_per_trade=Decimal("0.0017"),
        max_open_risk=Decimal("0.0061"),
        daily_loss_limit=Decimal("0.009"),
        weekly_drawdown_limit=Decimal("0.027"),
        consecutive_loss_cooldown=4,
        cooldown_ms=2_700_000,
        correlation_bucket_risk_limit=Decimal("0.0042"),
        max_gross_leverage=Decimal("2.5"),
        max_available_margin_fraction=Decimal("0.40"),
        max_visible_depth_fraction=Decimal("0.08"),
        min_liquidation_stop_multiple=Decimal("2.25"),
        max_state_age_ms=4_000,
    )

    limits = policy.limits_from_settings(settings)

    assert limits.risk_per_trade == Decimal("0.0017")
    assert limits.max_open_risk == Decimal("0.0061")
    assert limits.daily_loss_limit == Decimal("0.009")
    assert limits.weekly_drawdown_limit == Decimal("0.027")
    assert limits.consecutive_loss_cooldown == 4
    assert limits.cooldown_ms == 2_700_000
    assert limits.correlation_bucket_risk_limit == Decimal("0.0042")
    assert limits.max_gross_leverage == Decimal("2.5")
    assert limits.max_available_margin_fraction == Decimal("0.40")
    assert limits.max_visible_depth_fraction == Decimal("0.08")
    assert limits.min_liquidation_stop_multiple == Decimal("2.25")
    assert limits.max_state_age_ms == 4_000


def test_limits_adapter_never_converts_decimals_through_float() -> None:
    policy = _module()
    unusual = Decimal("0.001234567890123456789")
    limits = policy.limits_from_settings(Settings(risk_per_trade=unusual))

    assert limits.risk_per_trade == unusual
