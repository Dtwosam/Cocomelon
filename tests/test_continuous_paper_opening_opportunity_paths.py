from __future__ import annotations

import asyncio
import threading
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


def test_forward_path_cooperative_observe_matches_durable_semantics(
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
    store.register(
        opportunity_id="opp-2",
        market="BTC",
        direction="short",
        opportunity_timestamp_ms=10_000,
    )

    recorded = asyncio.run(
        store.observe_cooperatively(
            market="BTC",
            observed_at_ms=10_100,
            mark_px=Decimal("101"),
            source="metaAndAssetCtxs",
        )
    )

    assert recorded == 2
    restored = ContinuousPaperOpeningOpportunityPathStore(
        tmp_path / "paths",
        max_path_age_ms=1_000,
        max_completion_lag_ms=200,
    )
    for opportunity_id in ("opp-1", "opp-2"):
        path = restored.load(opportunity_id)
        assert path is not None
        assert tuple(mark.observed_at_ms for mark in path.marks) == (
            10_100,
        )


def test_forward_path_cooperative_rebuild_runs_off_event_loop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
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
    caller_thread = threading.get_ident()
    rebuild_threads: list[int] = []
    original = store._updated_paths_for_mark_from_snapshot

    def capture_thread(*args: object, **kwargs: object):
        rebuild_threads.append(threading.get_ident())
        return original(*args, **kwargs)

    monkeypatch.setattr(
        store,
        "_updated_paths_for_mark_from_snapshot",
        capture_thread,
    )

    recorded = asyncio.run(
        store.observe_cooperatively(
            market="BTC",
            observed_at_ms=10_100,
            mark_px=Decimal("101"),
            source="metaAndAssetCtxs",
        )
    )

    assert recorded == 1
    assert rebuild_threads
    assert all(thread_id != caller_thread for thread_id in rebuild_threads)


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

def test_forward_path_observe_uses_market_index_not_full_scan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ContinuousPaperOpeningOpportunityPathStore(
        tmp_path / "paths",
        max_path_age_ms=1_000,
        max_completion_lag_ms=200,
    )
    store.register(
        opportunity_id="btc-1",
        market="BTC",
        direction="long",
        opportunity_timestamp_ms=10_000,
    )
    store.register(
        opportunity_id="eth-1",
        market="ETH",
        direction="short",
        opportunity_timestamp_ms=10_000,
    )

    def fail_full_scan() -> tuple[object, ...]:
        raise AssertionError("observe must not scan every persisted path")

    monkeypatch.setattr(store, "iter_paths", fail_full_scan)

    assert store.observe(
        market="BTC",
        observed_at_ms=10_100,
        mark_px=Decimal("101"),
        source="metaAndAssetCtxs",
    ) == 1

    btc = store.load("btc-1")
    eth = store.load("eth-1")
    assert btc is not None
    assert eth is not None
    assert tuple(mark.observed_at_ms for mark in btc.marks) == (10_100,)
    assert eth.marks == ()


def test_forward_path_restores_active_market_index(
    tmp_path: Path,
) -> None:
    root = tmp_path / "paths"
    first = ContinuousPaperOpeningOpportunityPathStore(
        root,
        max_path_age_ms=1_000,
        max_completion_lag_ms=200,
    )
    first.register(
        opportunity_id="btc-1",
        market="BTC",
        direction="long",
        opportunity_timestamp_ms=10_000,
    )

    restored = ContinuousPaperOpeningOpportunityPathStore(
        root,
        max_path_age_ms=1_000,
        max_completion_lag_ms=200,
    )
    assert restored.observe(
        market="BTC",
        observed_at_ms=10_200,
        mark_px=Decimal("102"),
        source="metaAndAssetCtxs",
    ) == 1
    path = restored.load("btc-1")
    assert path is not None
    assert tuple(mark.observed_at_ms for mark in path.marks) == (10_200,)


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

