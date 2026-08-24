from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext

from cocomelon.domain.evaluation import TradeEvaluationSample

ZERO = Decimal("0")
ONE = Decimal("1")
AUTHORITATIVE_CONTEXT = Context(prec=28, rounding=ROUND_HALF_EVEN)


@dataclass(frozen=True, slots=True)
class CostStressProfile:
    profile_id: str
    fee_multiplier: Decimal
    adverse_slippage_multiplier: Decimal
    adverse_funding_multiplier: Decimal
    remove_favorable_slippage: bool
    remove_favorable_funding: bool

    def __post_init__(self) -> None:
        if not self.profile_id.strip():
            raise ValueError("profile_id must not be empty")
        for field in (
            "fee_multiplier",
            "adverse_slippage_multiplier",
            "adverse_funding_multiplier",
        ):
            value = getattr(self, field)
            if not value.is_finite() or value < ONE:
                raise ValueError(f"{field} must be finite and at least 1")


def predeclared_cost_stress_profiles() -> tuple[CostStressProfile, ...]:
    return (
        CostStressProfile(
            profile_id="base",
            fee_multiplier=ONE,
            adverse_slippage_multiplier=ONE,
            adverse_funding_multiplier=ONE,
            remove_favorable_slippage=False,
            remove_favorable_funding=False,
        ),
        CostStressProfile(
            profile_id="fees_1_25x",
            fee_multiplier=Decimal("1.25"),
            adverse_slippage_multiplier=ONE,
            adverse_funding_multiplier=ONE,
            remove_favorable_slippage=False,
            remove_favorable_funding=False,
        ),
        CostStressProfile(
            profile_id="adverse_slippage_1_50x",
            fee_multiplier=ONE,
            adverse_slippage_multiplier=Decimal("1.50"),
            adverse_funding_multiplier=ONE,
            remove_favorable_slippage=True,
            remove_favorable_funding=False,
        ),
        CostStressProfile(
            profile_id="adverse_funding_1_50x",
            fee_multiplier=ONE,
            adverse_slippage_multiplier=ONE,
            adverse_funding_multiplier=Decimal("1.50"),
            remove_favorable_slippage=False,
            remove_favorable_funding=True,
        ),
        CostStressProfile(
            profile_id="combined_stress",
            fee_multiplier=Decimal("1.25"),
            adverse_slippage_multiplier=Decimal("1.50"),
            adverse_funding_multiplier=Decimal("1.50"),
            remove_favorable_slippage=True,
            remove_favorable_funding=True,
        ),
    )


def _stressed_slippage_leg(amount: Decimal, profile: CostStressProfile) -> Decimal:
    if amount > ZERO:
        return amount * profile.adverse_slippage_multiplier
    if amount < ZERO and profile.remove_favorable_slippage:
        return ZERO
    return amount


def _stressed_funding(amount: Decimal, profile: CostStressProfile) -> Decimal:
    if amount < ZERO:
        return amount * profile.adverse_funding_multiplier
    if amount > ZERO and profile.remove_favorable_funding:
        return ZERO
    return amount


def apply_cost_stress(
    sample: TradeEvaluationSample,
    profile: CostStressProfile,
) -> Decimal:
    with localcontext(AUTHORITATIVE_CONTEXT):
        reference_gross = (
            sample.gross_realized_pnl
            + sample.entry_slippage_amount
            + sample.exit_slippage_amount
        )
        stressed_fees = (sample.entry_fees + sample.exit_fees) * profile.fee_multiplier
        stressed_slippage = _stressed_slippage_leg(
            sample.entry_slippage_amount,
            profile,
        ) + _stressed_slippage_leg(sample.exit_slippage_amount, profile)
        stressed_funding = _stressed_funding(sample.funding_cash_pnl, profile)
        return reference_gross - stressed_fees - stressed_slippage + stressed_funding
