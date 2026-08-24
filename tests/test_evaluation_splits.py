from decimal import Decimal

from cocomelon.domain.evaluation import (
    EvaluationDatasetManifest,
    EvaluationPolicy,
    ReplayEvaluationSource,
    SplitName,
    TimePartition,
    TradeEvaluationSample,
)
from cocomelon.domain.features import TrendRegime, VolatilityRegime
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import EvidenceClass
from cocomelon.domain.strategy import Direction
from cocomelon.evaluation.splits import (
    freeze_split_manifest,
    split_exclusion_reason,
    split_samples,
)

MARKET = MarketId("", "SOL")


def dataset() -> EvaluationDatasetManifest:
    return EvaluationDatasetManifest(
        sources=(
            ReplayEvaluationSource(
                run_id="run-1",
                manifest_id="manifest-1",
                result_digest="a" * 64,
                evidence_class=EvidenceClass.MICROSTRUCTURE,
                start_ms=0,
                end_ms=30_000,
                data_complete=True,
            ),
        ),
        trade_ids=(),
        decision_fact_ids=(),
        equity_fact_ids=(),
        start_ms=0,
        end_ms=30_000,
        code_revision="phase9-test",
        data_complete=True,
        gap_refs=(),
        mixed_evidence_diagnostic=False,
    )


def policy(*, embargo_ms: int = 1_000) -> EvaluationPolicy:
    return EvaluationPolicy(split_embargo_ms=embargo_ms)


def frozen(*, embargo_ms: int = 1_000):
    return freeze_split_manifest(
        dataset(),
        train=TimePartition(SplitName.TRAIN, 0, 10_000),
        validation=TimePartition(SplitName.VALIDATION, 10_000, 20_000),
        test=TimePartition(SplitName.TEST, 20_000, 30_000),
        policy=policy(embargo_ms=embargo_ms),
    )


def sample(
    suffix: str,
    *,
    opened_at_ms: int,
    closed_at_ms: int,
) -> TradeEvaluationSample:
    return TradeEvaluationSample(
        trade_id=f"trade-{suffix}",
        replay_run_id="run-1",
        strategy_decision_id=f"strategy-{suffix}",
        market=MARKET,
        direction=Direction.LONG,
        decision_timestamp_ms=max(0, opened_at_ms - 100),
        opened_at_ms=opened_at_ms,
        closed_at_ms=closed_at_ms,
        score=Decimal("70"),
        lead_strategy="trend",
        trend_regime=TrendRegime.UP,
        volatility_regime=VolatilityRegime.NORMAL,
        evidence_class=EvidenceClass.MICROSTRUCTURE,
        gross_realized_pnl=Decimal("10"),
        entry_fees=Decimal("0.5"),
        exit_fees=Decimal("0.5"),
        funding_cash_pnl=Decimal("0"),
        net_pnl=Decimal("9"),
        entry_slippage_amount=Decimal("0"),
        exit_slippage_amount=Decimal("0"),
        net_r=Decimal("0.36"),
        equity_before=Decimal("10000"),
        equity_after=Decimal("10009"),
        holding_duration_ms=closed_at_ms - opened_at_ms,
        reason_codes=("TREND_UP",),
    )


def test_freeze_split_uses_dataset_and_policy_identity() -> None:
    split = frozen()

    assert split.dataset_manifest_id == dataset().manifest_id
    assert split.policy_id == policy().policy_id
    assert split.embargo_ms == 1_000


def test_half_open_windows_require_full_lifecycle_containment() -> None:
    split = frozen(embargo_ms=0)
    train = sample("train", opened_at_ms=1_000, closed_at_ms=9_999)
    validation = sample("validation", opened_at_ms=10_000, closed_at_ms=19_999)
    test = sample("test", opened_at_ms=20_000, closed_at_ms=29_999)
    crossing = sample("cross", opened_at_ms=9_500, closed_at_ms=10_500)
    ending_at_boundary = sample("end", opened_at_ms=9_000, closed_at_ms=10_000)

    parts = split_samples((test, crossing, train, ending_at_boundary, validation), split)

    assert parts[SplitName.TRAIN] == (train,)
    assert parts[SplitName.VALIDATION] == (validation,)
    assert parts[SplitName.TEST] == (test,)
    assert split_exclusion_reason(crossing, split) == "CROSSES_SPLIT_BOUNDARY"
    assert split_exclusion_reason(ending_at_boundary, split) == "CROSSES_SPLIT_BOUNDARY"


def test_embargo_purges_neighboring_trades_even_when_lifecycle_is_contained() -> None:
    split = frozen(embargo_ms=1_000)
    safe_train = sample("safe-train", opened_at_ms=2_000, closed_at_ms=8_999)
    near_train = sample("near-train", opened_at_ms=8_500, closed_at_ms=9_500)
    near_validation = sample("near-validation", opened_at_ms=10_100, closed_at_ms=10_500)
    safe_validation = sample("safe-validation", opened_at_ms=11_000, closed_at_ms=18_999)

    parts = split_samples(
        (near_validation, safe_validation, near_train, safe_train),
        split,
    )

    assert parts[SplitName.TRAIN] == (safe_train,)
    assert parts[SplitName.VALIDATION] == (safe_validation,)
    assert split_exclusion_reason(near_train, split) == "SPLIT_EMBARGO"
    assert split_exclusion_reason(near_validation, split) == "SPLIT_EMBARGO"


def test_long_position_crossing_boundary_is_purged_even_beyond_embargo() -> None:
    split = frozen(embargo_ms=100)
    long_cross = sample("long-cross", opened_at_ms=5_000, closed_at_ms=15_000)

    parts = split_samples((long_cross,), split)

    assert all(long_cross not in values for values in parts.values())
    assert split_exclusion_reason(long_cross, split) == "CROSSES_SPLIT_BOUNDARY"
