"""Isolated research-only trend shadow alongside the existing v5 paired actor.

Every incoming replay record is offered to both independently owned actors.
An optional new study can fail without resetting the authenticated v5
checkpoint or changing the original paper trading strategy and risk limits.
"""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from pathlib import Path
from typing import Final

from cocomelon.domain.features import OpportunityRank
from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import ReplayRecord
from cocomelon.evidence.contracts import BaselineReplayConfig
from cocomelon.research.loss_context_paired_shadow_runtime import (
    LossContextPairedShadowRuntime,
)
from cocomelon.research.loss_context_portfolio_shadow_candidate import (
    verify_loss_context_portfolio_shadow_freeze,
)
from cocomelon.research.prospective_both_side_trend_paired_freeze import (
    both_side_trend_matched_shadow_freeze,
)

TREND_PAIR_STATE_ROOT: Final = "both-side-trend-paired-shadow-v1"
TREND_PAIR_FREEZE_FILE: Final = "both-side-trend-paired-shadow-freeze.json"
TREND_PAIR_SUMMARY_FILE: Final = "both-side-trend-paired-shadow-summary.json"


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def prepare_trend_pair_freeze(
    paper_root: Path,
    *,
    legacy_shadow_root_name: str,
) -> Path:
    """Never overwrite a mismatched or incomplete earlier study identity."""
    root = paper_root / TREND_PAIR_STATE_ROOT
    legacy = paper_root / legacy_shadow_root_name
    if root == legacy or root.resolve() == legacy.resolve():
        raise ValueError("trend paired shadow must not reuse v5 state root")
    expected = both_side_trend_matched_shadow_freeze()
    freeze_path = paper_root / TREND_PAIR_FREEZE_FILE
    if freeze_path.exists():
        if verify_loss_context_portfolio_shadow_freeze(freeze_path) != expected:
            raise RuntimeError("existing trend paired shadow identity mismatch")
    else:
        if root.exists() and any(root.iterdir()):
            raise RuntimeError("trend paired shadow state exists without its freeze")
        # Exclusive open prevents an already created freeze from being replaced.
        payload = json.dumps(
            expected.to_dict(), sort_keys=True, separators=(",", ":"),
        ) + "\n"
        with freeze_path.open("x", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    return freeze_path


class PairedShadowTrendSidecar:
    """A non-blocking dual shadow: v5 outcome and fresh trend outcome isolated."""

    def __init__(
        self,
        primary: LossContextPairedShadowRuntime | None,
        trend: LossContextPairedShadowRuntime,
        *,
        summary_path: Path,
        startup_timestamp_ms: int,
    ) -> None:
        if primary is not None and (
            primary is trend or primary.candidate_id == trend.candidate_id
        ):
            raise ValueError("two shadow campaigns must have distinct identities")
        self.primary = primary
        self.trend = trend
        self.summary_path = summary_path
        self.startup_timestamp_ms = startup_timestamp_ms

    @property
    def candidate_id(self) -> str:
        return (
            self.primary.candidate_id
            if self.primary is not None else "legacy_shadow_unavailable"
        )

    def status_payload(self) -> dict[str, object]:
        """Keep legacy v5 status and reports exactly scoped to the v5 lane."""
        if self.primary is None:
            return {
                "enabled": False, "error": "legacy paired shadow unavailable",
                "research_only": True, "shadow_only": True,
                "paper_only": True, "promotion_authority": False,
                "execution_authority": False,
            }
        return self.primary.status_payload()

    def trend_status_payload(self) -> dict[str, object]:
        # Operational counters only. These are not a signed economic result,
        # even when the actor is initialized and processing future records.
        return {
            **self.trend.status_payload(),
            "trial_id": (
                "prospective-both-sides-trend-lead-capital-matched-shadow-v1"
            ),
            "forward_not_before_ms": (
                both_side_trend_matched_shadow_freeze().prospective_not_before_ms
            ),
            "worker_startup_timestamp_ms": self.startup_timestamp_ms,
            "forward_only_after_embargo": True,
            "research_only": True,
            "shadow_only": True,
            "paper_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "source_and_gaps_independently_authenticated": False,
            "economic_review_ready": False,
        }

    def submit_record(
        self, record: ReplayRecord, *, now_ms: int, evaluate_decisions: bool,
    ) -> bool:
        original_ok = (
            self.primary.submit_record(
                record, now_ms=now_ms, evaluate_decisions=evaluate_decisions,
            ) if self.primary is not None else False
        )
        trend_ok = self.trend.submit_record(
            record, now_ms=now_ms, evaluate_decisions=evaluate_decisions,
        )
        return original_ok or trend_ok

    def submit_rank_snapshot(
        self, ranks: Sequence[OpportunityRank], *, observed_at_ms: int,
    ) -> bool:
        legacy = (
            self.primary.submit_rank_snapshot(ranks, observed_at_ms=observed_at_ms)
            if self.primary is not None else False
        )
        trend = self.trend.submit_rank_snapshot(
            ranks, observed_at_ms=observed_at_ms,
        )
        return legacy or trend

    def submit_reconcile(self, selected_markets: Sequence[MarketId]) -> bool:
        legacy = (
            self.primary.submit_reconcile(selected_markets)
            if self.primary is not None else False
        )
        trend = self.trend.submit_reconcile(selected_markets)
        return legacy or trend

    def submit_restore_warmup_complete(self) -> bool:
        legacy = (
            self.primary.submit_restore_warmup_complete()
            if self.primary is not None else False
        )
        trend = self.trend.submit_restore_warmup_complete()
        return legacy or trend

    async def protected_open_markets(
        self, *, timeout_seconds: float = 30.0,
    ) -> tuple[MarketId, ...]:
        legacy: tuple[MarketId, ...] = ()
        if self.primary is not None:
            try:
                legacy = await self.primary.protected_open_markets(
                    timeout_seconds=timeout_seconds,
                )
            except Exception as exc:
                # A failed OLD v5 restore is not grounds to contaminate the
                # new study or force a second reset of its negative history.
                self.primary.fail_closed(
                    "legacy paired market census unavailable: "
                    + f"{type(exc).__name__}: {exc}"
                )
        try:
            trend = await self.trend.protected_open_markets(
                timeout_seconds=timeout_seconds,
            )
        except Exception as exc:
            # Losing the new shadow's position visibility invalidates it.
            # Existing v5 and original paper still receive market data.
            self.trend.fail_closed(
                "trend-held market census unavailable: "
                + f"{type(exc).__name__}: {exc}"
            )
            trend = ()
        unique = {item.canonical: item for item in (*legacy, *trend)}
        return tuple(unique[key] for key in sorted(unique))

    def fail_closed(self, reason: str) -> None:
        """Shared market-source gaps invalidate both shadows, never paper."""
        if self.primary is not None:
            self.primary.fail_closed(reason)
        self.trend.fail_closed(reason)

    async def checkpoint(self, *, end_ms: int) -> dict[str, object]:
        # Always attempt a separate trend receipt, even if primary fails.
        # The primary result must be unchanged; its negative v5 history stays.
        if self.primary is None:
            await self._checkpoint_trend(end_ms=end_ms)
            raise RuntimeError("legacy paired shadow unavailable; no v5 checkpoint")
        try:
            legacy = await self.primary.checkpoint(end_ms=end_ms)
        except Exception:
            await self._checkpoint_trend(end_ms=end_ms)
            raise
        await self._checkpoint_trend(end_ms=end_ms)
        return legacy

    async def _checkpoint_trend(self, *, end_ms: int) -> None:
        status = self.trend.status_payload()
        payload: dict[str, object] = {
            "schema_version": 1,
            "trial_id": "prospective-both-sides-trend-lead-capital-matched-shadow-v1",
            "frozen_forward_not_before_ms": (
                both_side_trend_matched_shadow_freeze().prospective_not_before_ms
            ),
            "startup_timestamp_ms": self.startup_timestamp_ms,
            "started_after_frozen_boundary": (
                self.startup_timestamp_ms
                > both_side_trend_matched_shadow_freeze().prospective_not_before_ms
            ),
            "original_mainnet_source_and_gaps_independently_authenticated": False,
            "research_only": True,
            "shadow_only": True,
            "paper_only": True,
            "execution_authority": False,
            "promotion_authority": False,
            "ready_for_review": False,
            "forward_profitable_signed_account_edge_proven": False,
            "checkpoint_published": False,
            "checkpoint": None,
            "runtime": status,
            "checkpoint_error": None,
        }
        try:
            payload["checkpoint"] = await self.trend.checkpoint(end_ms=end_ms)
            payload["checkpoint_published"] = True
        except Exception as exc:
            self.trend.fail_closed(
                "trend paired checkpoint failed: "
                + f"{type(exc).__name__}: {exc}"
            )
            payload["runtime"] = self.trend.status_payload()
            payload["checkpoint_error"] = f"{type(exc).__name__}: {exc}"
        _write_json(self.summary_path, payload)

    async def close(self) -> None:
        try:
            await self.trend.close()
        finally:
            if self.primary is not None:
                await self.primary.close()


def start_trend_paired_shadow_sidecar(
    primary: LossContextPairedShadowRuntime | None,
    *,
    paper_root: Path,
    replay_config: BaselineReplayConfig,
    selected_markets: Sequence[MarketId],
    startup_timestamp_ms: int,
    legacy_shadow_root_name: str,
) -> PairedShadowTrendSidecar:
    """Open a new isolated actor with or without a healthy legacy shadow.

    The newer candidate must not inherit the old v5 durable-state failure.
    It is still strictly paper-only and requires authentic future events.
    """
    freeze_path = prepare_trend_pair_freeze(
        paper_root, legacy_shadow_root_name=legacy_shadow_root_name,
    )
    freeze = verify_loss_context_portfolio_shadow_freeze(freeze_path)
    trend = LossContextPairedShadowRuntime(
        freeze=freeze,
        replay_config=replay_config,
        selected_markets=selected_markets,
        state_root=paper_root / TREND_PAIR_STATE_ROOT,
        startup_timestamp_ms=startup_timestamp_ms,
    )
    return PairedShadowTrendSidecar(
        primary, trend,
        summary_path=paper_root / TREND_PAIR_SUMMARY_FILE,
        startup_timestamp_ms=startup_timestamp_ms,
    )
