"""Chunk optional opportunity-path research without altering original mark evidence."""
from __future__ import annotations

import asyncio
import threading
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from cocomelon.research.continuous_paper_opening_opportunity_paths import (
    COOPERATIVE_MARK_BATCH_SIZE,
    ContinuousPaperOpeningOpportunityPathError,
    ContinuousPaperOpeningOpportunityPathMark,
    ContinuousPaperOpeningOpportunityPathStore,
)

SOURCE = "metaAndAssetCtxs"


def _store(root: Path) -> ContinuousPaperOpeningOpportunityPathStore:
    return ContinuousPaperOpeningOpportunityPathStore(
        root, max_path_age_ms=1000, max_completion_lag_ms=200,
    )


def _register(store: ContinuousPaperOpeningOpportunityPathStore) -> None:
    for i in range(73):
        store.register(
            opportunity_id=f"opp-{i:03}",
            market="BTC" if i < 68 else "ETH",
            direction="long" if i % 2 == 0 else "short",
            opportunity_timestamp_ms=10_000,
        )


def test_large_market_snapshot_yields_bounded_exact_offloaded_batches(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert COOPERATIVE_MARK_BATCH_SIZE == 32
    sync = _store(tmp_path / "sync")
    async_store = _store(tmp_path / "async")
    _register(sync)
    _register(async_store)
    captured_sizes: list[int] = []
    threads: list[int] = []
    original = async_store._updated_paths_for_mark_from_snapshot

    def record_batch(paths: tuple[object, ...], **kwargs: object):
        captured_sizes.append(len(paths))
        threads.append(threading.get_ident())
        return original(paths, **kwargs)

    monkeypatch.setattr(
        async_store, "_updated_paths_for_mark_from_snapshot",
        record_batch,
    )
    main_thread = threading.get_ident()

    async def run() -> tuple[int, int, int]:
        heartbeat_ticks = 0
        task = asyncio.create_task(async_store.observe_cooperatively(
            market="BTC", observed_at_ms=10_100,
            mark_px=Decimal("101"), source=SOURCE,
        ))
        while not task.done():
            heartbeat_ticks += 1
            await asyncio.sleep(0)
        return await task, heartbeat_ticks, await async_store.observe_cooperatively(
            market="ETH", observed_at_ms=10_100,
            mark_px=Decimal("101"), source=SOURCE,
        )

    btc_count, ticks, eth_count = asyncio.run(run())
    assert (btc_count, eth_count) == (68, 5)
    assert captured_sizes == [32, 32, 4, 5]
    assert all(size <= COOPERATIVE_MARK_BATCH_SIZE for size in captured_sizes)
    assert all(worker != main_thread for worker in threads)
    assert ticks > 1
    assert sync.observe(
        market="BTC", observed_at_ms=10_100,
        mark_px=Decimal("101"), source=SOURCE,
    ) == 68
    assert sync.observe(
        market="ETH", observed_at_ms=10_100,
        mark_px=Decimal("101"), source=SOURCE,
    ) == 5
    assert async_store.iter_paths() == sync.iter_paths()
    # The exact durable records must also reconcile after independent reopen.
    assert _store(tmp_path / "async").iter_paths() == sync.iter_paths()


def test_late_conflict_does_not_partially_commit_earlier_valid_batches(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path / "strict")
    for i in range(70):
        store.register(
            opportunity_id=f"opp-{i:03}",
            market="BTC",
            direction="long",
            opportunity_timestamp_ms=10_000,
        )
    # The last sorted path has a pre-existing valid original mark while
    # 69 earlier paths remain unobserved. A conflicting same-time mark at
    # the final chunk must reject BEFORE writing any of the first chunks.
    tail = store._paths_by_id["opp-069"]
    original_mark = ContinuousPaperOpeningOpportunityPathMark(
        observed_at_ms=10_100, mark_px=Decimal("101"), source=SOURCE,
    )
    marked_tail = replace(tail, marks=(original_mark,))
    store._write(marked_tail)
    store._index_path(marked_tail)
    before = store.iter_paths()
    with pytest.raises(
        ContinuousPaperOpeningOpportunityPathError,
        match="OPENING_OPPORTUNITY_PATH_MARK_CONFLICT",
    ):
        asyncio.run(store.observe_cooperatively(
            market="BTC", observed_at_ms=10_100,
            mark_px=Decimal("102"), source=SOURCE,
        ))
    assert store.iter_paths() == before
    assert _store(tmp_path / "strict").iter_paths() == before
    assert tail.opportunity_id == "opp-069"


def test_expired_empty_batches_do_not_create_synthetic_marks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path / "inactive")
    _register(store)
    calls: list[int] = []
    original = store._updated_paths_for_mark_from_snapshot

    def count(paths: tuple[object, ...], **kwargs: object):
        calls.append(len(paths))
        return original(paths, **kwargs)

    monkeypatch.setattr(store, "_updated_paths_for_mark_from_snapshot", count)
    assert asyncio.run(store.observe_cooperatively(
        market="BTC", observed_at_ms=11_201,
        mark_px=Decimal("101"), source=SOURCE,
    )) == 0
    assert calls == [32, 32, 4]
    assert store.record_count == 73
    assert all(not path.marks for path in store.iter_paths())


def test_after_horizon_original_mark_in_one_batch_keeps_exact_completion(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path / "horizon")
    _register(store)
    assert asyncio.run(store.observe_cooperatively(
        market="BTC", observed_at_ms=11_100,
        mark_px=Decimal("100"), source=SOURCE,
    )) == 68
    paths = store.iter_paths()
    assert sum(path.complete for path in paths) == 68
    assert all(
        len(path.marks) == 1 and path.marks[0].observed_at_ms == 11_100
        for path in paths if path.market == "BTC"
    )
