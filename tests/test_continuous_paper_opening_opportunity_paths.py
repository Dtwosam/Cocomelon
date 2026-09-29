from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from cocomelon.research.continuous_paper_opening_opportunity_paths import (
    ContinuousPaperOpeningOpportunityPathError,
    ContinuousPaperOpeningOpportunityPathStore,
)


def test_forward_path_store_is_durable_and_market_scoped(tmp_path: Path) -> None:
    store = ContinuousPaperOpeningOpportunityPathStore(
        tmp_path / "paths",
        max_path_age_ms=1_000,
        max_completion_lag_ms=200,
    )
    assert store.register(
        opportunity_id="opp-1",
        market="BTC",
        direction="long",
        opportunity_timestamp_ms=10_000,
    ) is True
    assert store.register(
        opportunity_id="opp-1",
        market="BTC",
        direction="long",
        opportunity_timestamp_ms=10_000,
    ) is False

    assert store.observe(
        market="ETH",
        observed_at_ms=10_100,
        mark_px=Decimal("2000"),
        source="metaAndAssetCtxs",
    ) == 0
    assert store.observe(
        market="BTC",
        observed_at_ms=9_999,
        mark_px=Decimal("100"),
        source="metaAndAssetCtxs",
    ) == 0
    assert store.observe(
        market="BTC",
        observed_at_ms=10_100,
        mark_px=Decimal("101"),
        source="metaAndAssetCtxs",
    ) == 1
    assert store.observe(
        market="BTC",
        observed_at_ms=10_100,
        mark_px=Decimal("101"),
        source="metaAndAssetCtxs",
    ) == 0

    restored = ContinuousPaperOpeningOpportunityPathStore(
        tmp_path / "paths",
        max_path_age_ms=1_000,
        max_completion_lag_ms=200,
    )
    path = restored.load("opp-1")
    assert path is not None
    assert path.market == "BTC"
    assert path.direction == "long"
    assert path.opportunity_timestamp_ms == 10_000
    assert path.expires_at_ms == 11_000
    assert tuple(mark.observed_at_ms for mark in path.marks) == (10_100,)
    assert tuple(mark.mark_px for mark in path.marks) == (Decimal("101"),)
    assert restored.record_count == 1
    assert restored.complete_count == 0
    assert len(restored.state_digest) == 64


def test_forward_path_completes_on_first_mark_at_or_after_horizon(
    tmp_path: Path,
) -> None:
    store = ContinuousPaperOpeningOpportunityPathStore(
        tmp_path / "paths",
        max_path_age_ms=1_000,
        max_completion_lag_ms=200,
    )
    store.register(
        opportunity_id="opp-1",
        market="BTC",
        direction="short",
        opportunity_timestamp_ms=10_000,
    )
    assert store.observe(
        market="BTC",
        observed_at_ms=10_900,
        mark_px=Decimal("99"),
        source="metaAndAssetCtxs",
    ) == 1
    assert store.observe(
        market="BTC",
        observed_at_ms=11_050,
        mark_px=Decimal("98"),
        source="metaAndAssetCtxs",
    ) == 1
    assert store.observe(
        market="BTC",
        observed_at_ms=11_100,
        mark_px=Decimal("97"),
        source="metaAndAssetCtxs",
    ) == 0

    path = store.load("opp-1")
    assert path is not None
    assert path.complete is True
    assert tuple(mark.observed_at_ms for mark in path.marks) == (
        10_900,
        11_050,
    )
    assert store.complete_count == 1


def test_forward_path_rejects_conflicting_same_timestamp_mark(
    tmp_path: Path,
) -> None:
    store = ContinuousPaperOpeningOpportunityPathStore(
        tmp_path / "paths",
        max_path_age_ms=1_000,
        max_completion_lag_ms=200,
    )
    store.register(
        opportunity_id="opp-1",
        market="BTC",
        direction="long",
        opportunity_timestamp_ms=10_000,
    )
    store.observe(
        market="BTC",
        observed_at_ms=10_100,
        mark_px=Decimal("101"),
        source="metaAndAssetCtxs",
    )

    with pytest.raises(
        ContinuousPaperOpeningOpportunityPathError,
        match="OPENING_OPPORTUNITY_PATH_MARK_CONFLICT",
    ):
        store.observe(
            market="BTC",
            observed_at_ms=10_100,
            mark_px=Decimal("102"),
            source="metaAndAssetCtxs",
        )

def test_forward_path_does_not_impute_after_completion_deadline(
    tmp_path: Path,
) -> None:
    store = ContinuousPaperOpeningOpportunityPathStore(
        tmp_path / "paths",
        max_path_age_ms=1_000,
        max_completion_lag_ms=200,
    )
    store.register(
        opportunity_id="opp-1",
        market="BTC",
        direction="long",
        opportunity_timestamp_ms=10_000,
    )

    assert store.observe(
        market="BTC",
        observed_at_ms=11_201,
        mark_px=Decimal("103"),
        source="metaAndAssetCtxs",
    ) == 0

    path = store.load("opp-1")
    assert path is not None
    assert path.complete is False
    assert path.marks == ()

