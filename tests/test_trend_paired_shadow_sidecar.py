from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from cocomelon.domain.market import MarketId
from cocomelon.research.prospective_both_side_trend_paired_freeze import (
    both_side_trend_matched_shadow_freeze,
)
from cocomelon.research.trend_paired_shadow_sidecar import (
    TREND_PAIR_FREEZE_FILE,
    TREND_PAIR_STATE_ROOT,
    TREND_PAIR_SUMMARY_FILE,
    PairedShadowTrendSidecar,
    prepare_trend_pair_freeze,
)

BTC = MarketId("", "BTC")
ETH = MarketId("", "ETH")


class FakeActor:
    def __init__(
        self, candidate_id: str, held: tuple[MarketId, ...] = (),
        *, bad_checkpoint: bool = False, bad_census: bool = False,
    ) -> None:
        self.candidate_id = candidate_id
        self.held = held
        self.bad_checkpoint = bad_checkpoint
        self.bad_census = bad_census
        self.events: list[tuple[object, ...]] = []
        self.failures: list[str] = []

    def status_payload(self) -> dict[str, object]:
        return {"candidate_id": self.candidate_id, "failed": bool(self.failures)}

    def submit_record(
        self, record: Any, *, now_ms: int, evaluate_decisions: bool,
    ) -> bool:
        self.events.append(("record", record, now_ms, evaluate_decisions))
        return True

    def submit_rank_snapshot(
        self, ranks: Any, *, observed_at_ms: int,
    ) -> bool:
        self.events.append(("rank", tuple(ranks), observed_at_ms))
        return True

    def submit_reconcile(self, markets: Any) -> bool:
        self.events.append(("reconcile", tuple(markets)))
        return True

    def submit_restore_warmup_complete(self) -> bool:
        self.events.append(("warmup",))
        return True

    async def protected_open_markets(
        self, *, timeout_seconds: float,
    ) -> tuple[MarketId, ...]:
        self.events.append(("held", timeout_seconds))
        if self.bad_census:
            raise RuntimeError("missing shadow-held book")
        return self.held

    def fail_closed(self, reason: str) -> None:
        self.failures.append(reason)

    async def checkpoint(self, *, end_ms: int) -> dict[str, object]:
        self.events.append(("checkpoint", end_ms))
        if self.bad_checkpoint or self.failures:
            raise RuntimeError("unsafe handoff")
        return {"candidate_id": self.candidate_id, "end_ms": end_ms}

    async def close(self) -> None:
        self.events.append(("close",))


def _pair(
    tmp_path: Path, *, bad_trend: bool = False, bad_primary: bool = False,
    bad_census: bool = False,
) -> tuple[PairedShadowTrendSidecar, FakeActor, FakeActor]:
    original = FakeActor("old", (BTC,), bad_checkpoint=bad_primary)
    trend = FakeActor(
        "new", (BTC, ETH), bad_checkpoint=bad_trend,
        bad_census=bad_census,
    )
    # Real fanout is duck-typed; stub isolates the actor scheduling contract.
    from typing import cast

    from cocomelon.research.loss_context_paired_shadow_runtime import (
        LossContextPairedShadowRuntime,
    )

    duo = PairedShadowTrendSidecar(
        cast(LossContextPairedShadowRuntime, original),
        cast(LossContextPairedShadowRuntime, trend),
        summary_path=tmp_path / TREND_PAIR_SUMMARY_FILE,
        startup_timestamp_ms=both_side_trend_matched_shadow_freeze().frozen_at_ms,
    )
    return duo, original, trend


def test_isolated_paired_trial_freeze_write_once(tmp_path: Path) -> None:
    path = prepare_trend_pair_freeze(
        tmp_path, legacy_shadow_root_name="loss-context-paired-v5",
    )
    assert path.name == TREND_PAIR_FREEZE_FILE
    assert path.is_file()
    old = path.read_bytes()
    assert prepare_trend_pair_freeze(
        tmp_path, legacy_shadow_root_name="loss-context-paired-v5",
    ) == path
    assert path.read_bytes() == old
    altered = json.loads(path.read_text())
    altered["candidate_id"] = "f" * 64
    path.write_text(json.dumps(altered))
    with pytest.raises((RuntimeError, ValueError)):
        prepare_trend_pair_freeze(
            tmp_path, legacy_shadow_root_name="loss-context-paired-v5",
        )


def test_unfrozen_state_is_never_adopted(tmp_path: Path) -> None:
    root = tmp_path / TREND_PAIR_STATE_ROOT
    root.mkdir()
    (root / "baseline-execution.sqlite3").write_bytes(b"historic-data")
    with pytest.raises(RuntimeError, match="without its freeze"):
        prepare_trend_pair_freeze(
            tmp_path, legacy_shadow_root_name="loss-context-paired-v5",
        )
    assert not (tmp_path / TREND_PAIR_FREEZE_FILE).exists()
    with pytest.raises(ValueError, match="must not reuse"):
        prepare_trend_pair_freeze(
            tmp_path, legacy_shadow_root_name=TREND_PAIR_STATE_ROOT,
        )


def test_fanout_preserves_old_lane_and_reconciles_protected_markets(
    tmp_path: Path,
) -> None:
    duo, old, trend = _pair(tmp_path)
    assert duo.candidate_id == "old"
    assert duo.status_payload()["candidate_id"] == "old"
    status = duo.trend_status_payload()
    assert status["candidate_id"] == "new"
    assert status["trial_id"].endswith("capital-matched-shadow-v1")
    assert status["forward_not_before_ms"] == (
        both_side_trend_matched_shadow_freeze().prospective_not_before_ms
    )
    assert status["worker_startup_timestamp_ms"] == (
        both_side_trend_matched_shadow_freeze().frozen_at_ms
    )
    assert status["economic_review_ready"] is False
    assert status["source_and_gaps_independently_authenticated"] is False
    assert status["promotion_authority"] is False
    assert status["execution_authority"] is False
    assert duo.submit_record(
        "tick", now_ms=100, evaluate_decisions=False,
    ) is True
    assert duo.submit_rank_snapshot((), observed_at_ms=101) is True
    assert duo.submit_reconcile((BTC, ETH)) is True
    assert duo.submit_restore_warmup_complete() is True
    markets = asyncio.run(duo.protected_open_markets())
    assert markets == (BTC, ETH)
    assert old.events == trend.events
    result = asyncio.run(duo.checkpoint(end_ms=200))
    assert result == {"candidate_id": "old", "end_ms": 200}
    receipt = json.loads(
        (tmp_path / TREND_PAIR_SUMMARY_FILE).read_text(),
    )
    assert receipt["checkpoint_published"] is True
    assert receipt["checkpoint"]["candidate_id"] == "new"
    assert receipt["ready_for_review"] is False
    assert receipt["promotion_authority"] is False
    assert receipt["execution_authority"] is False
    assert receipt["forward_profitable_signed_account_edge_proven"] is False
    assert receipt["original_mainnet_source_and_gaps_independently_authenticated"] is False
    assert receipt["started_after_frozen_boundary"] is False
    asyncio.run(duo.close())
    assert old.events[-1] == trend.events[-1] == ("close",)


def test_trend_checkpoint_failure_never_rewrites_v5_or_reports_success(
    tmp_path: Path,
) -> None:
    duo, old, trend = _pair(tmp_path, bad_trend=True)
    assert asyncio.run(duo.checkpoint(end_ms=200)) == {
        "candidate_id": "old", "end_ms": 200,
    }
    assert old.failures == []
    assert trend.failures and "unsafe handoff" in trend.failures[0]
    receipt = json.loads(
        (tmp_path / TREND_PAIR_SUMMARY_FILE).read_text(),
    )
    assert receipt["checkpoint_published"] is False
    assert receipt["checkpoint"] is None
    assert "unsafe handoff" in receipt["checkpoint_error"]
    assert receipt["ready_for_review"] is False


def test_v5_checkpoint_failure_still_produces_negative_independent_receipt(
    tmp_path: Path,
) -> None:
    duo, _, trend = _pair(tmp_path, bad_primary=True)
    with pytest.raises(RuntimeError, match="unsafe handoff"):
        asyncio.run(duo.checkpoint(end_ms=200))
    assert ("checkpoint", 200) in trend.events
    receipt = json.loads(
        (tmp_path / TREND_PAIR_SUMMARY_FILE).read_text(),
    )
    assert receipt["checkpoint_published"] is True
    assert receipt["ready_for_review"] is False


def test_unavailable_trend_held_markets_disable_only_trend(tmp_path: Path) -> None:
    duo, old, trend = _pair(tmp_path, bad_census=True)
    assert asyncio.run(duo.protected_open_markets()) == (BTC,)
    assert old.failures == []
    assert len(trend.failures) == 1
    assert "market census unavailable" in trend.failures[0]
    duo.fail_closed("shared feed gap")
    assert old.failures == ["shared feed gap"]
    assert trend.failures[-1] == "shared feed gap"


def test_worker_wiring_is_read_only_and_does_not_replace_v5() -> None:
    paper = Path("src/cocomelon/continuous_paper.py").read_text()
    workflow = Path(".github/workflows/continuous-paper.yml").read_text()
    assert "start_trend_paired_shadow_sidecar(" in paper
    assert "legacy_shadow_root_name=LOSS_CONTEXT_PAIRED_SHADOW_ROOT" in paper
    assert "loss_context_paired_shadow_runtime.submit_record(" in paper
    assert "TREND_PAIR_SUMMARY_FILE" in paper
    assert "both-side-trend-paired-shadow-v1" in workflow
    assert "both-side-trend-paired-shadow-summary.json" in workflow
    assert "continuous-paper-both-side-trend-paired-shadow-" in workflow
    assert "loss-context-paired-portfolio-shadow-scoped-v5" in workflow


def test_new_trend_shadow_runs_without_any_legacy_v5_actor(
    tmp_path: Path,
) -> None:
    _, _, trend = _pair(tmp_path)
    from typing import cast

    from cocomelon.research.loss_context_paired_shadow_runtime import (
        LossContextPairedShadowRuntime,
    )

    duo = PairedShadowTrendSidecar(
        None,
        cast(LossContextPairedShadowRuntime, trend),
        summary_path=tmp_path / TREND_PAIR_SUMMARY_FILE,
        startup_timestamp_ms=both_side_trend_matched_shadow_freeze().frozen_at_ms,
    )
    assert duo.status_payload()["enabled"] is False
    assert duo.submit_record(
        "independent-future-tick", now_ms=201, evaluate_decisions=True,
    ) is True
    assert asyncio.run(duo.protected_open_markets()) == (BTC, ETH)
    with pytest.raises(RuntimeError, match="legacy paired shadow unavailable"):
        asyncio.run(duo.checkpoint(end_ms=300))
    receipt = json.loads((tmp_path / TREND_PAIR_SUMMARY_FILE).read_text())
    assert receipt["checkpoint_published"] is True
    assert receipt["checkpoint"]["candidate_id"] == "new"
    assert receipt["promotion_authority"] is False
    assert receipt["ready_for_review"] is False
    asyncio.run(duo.close())
    assert ("close",) in trend.events


def test_broken_legacy_v5_market_census_does_not_disable_fresh_trial(
    tmp_path: Path,
) -> None:
    duo, old, trend = _pair(tmp_path)
    old.bad_census = True
    assert asyncio.run(duo.protected_open_markets()) == (BTC, ETH)
    assert len(old.failures) == 1
    assert trend.failures == []
    with pytest.raises(RuntimeError, match="unsafe handoff"):
        asyncio.run(duo.checkpoint(end_ms=305))
    receipt = json.loads((tmp_path / TREND_PAIR_SUMMARY_FILE).read_text())
    assert receipt["checkpoint_published"] is True
    assert receipt["ready_for_review"] is False
