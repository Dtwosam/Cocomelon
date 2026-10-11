from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Sequence
from decimal import Decimal
from pathlib import Path
from typing import Final

from cocomelon.domain.market import MarketId
from cocomelon.domain.replay import (
    EvidenceClass,
    ReplayManifest,
    ReplayRecord,
    SourceRecordKind,
)
from cocomelon.evaluation.store import EvaluationFactStore
from cocomelon.evidence.contracts import BaselineReplayConfig
from cocomelon.evidence.lifecycle import (
    BaselineReplayPipeline,
    DecisionEpochEngine,
)
from cocomelon.execution.accounting import PaperAccountState
from cocomelon.execution.paper import PaperExecutionAdapter
from cocomelon.research.prospective_short_breakout_paired_entry import (
    ObservedRankWitness,
    ProspectiveShortBreakoutPairedEntryFilter,
    RankWitnessProvider,
)
from cocomelon.research.prospective_short_breakout_rank import (
    ProspectiveShortBreakoutRankState,
)
from cocomelon.research.prospective_short_rank_utc_window import (
    PairedAccountUtcWindowLedger,
)

ZERO: Final = Decimal("0")


class ShortRankPairedReplayError(RuntimeError):
    pass


class ShortRankIndependentPairedPaperReplay:
    """Run TWO real paper execution simulations over each identical source row.

    Isolated one-shot research harness: no existing v5 state, original account
    mutation, live adapters, posttrade rank inference, restart, or promotion.
    The caller must independently authenticate the original mainnet manifest,
    every source segment and a predecision rank-witness stream. A manifest ID
    and local replay hash do not themselves prove source completeness.
    """

    def __init__(
        self,
        *,
        freeze: ProspectiveShortBreakoutRankState,
        config: BaselineReplayConfig,
        manifest: ReplayManifest,
        selected_markets: Sequence[MarketId],
        rank_witness_provider: RankWitnessProvider,
        state_root: str | Path,
        decision_engine_factory: Callable[[], DecisionEpochEngine] | None = None,
    ) -> None:
        if manifest.evidence_class is not EvidenceClass.MICROSTRUCTURE:
            raise ShortRankPairedReplayError(
                "paired replay requires observed mainnet microstructure"
            )
        if manifest.end_ms < freeze.started_at_ms:
            raise ShortRankPairedReplayError(
                "paired replay source ends before frozen forward start"
            )
        markets = tuple(sorted(selected_markets, key=lambda m: m.canonical))
        if not markets or len({m.canonical for m in markets}) != len(markets):
            raise ShortRankPairedReplayError(
                "paired replay requires unique selected markets"
            )
        root = Path(state_root)
        if root.exists() and (not root.is_dir() or any(root.iterdir())):
            raise ShortRankPairedReplayError(
                "independent paired account root must be new and empty"
            )
        root.mkdir(parents=True, exist_ok=True)
        self._manifest = manifest
        self._freeze = freeze
        self._root = root
        # Never let two replay lanes read different rank values because the
        # callback changed its mind between baseline and candidate calls.
        # Source authenticity still needs independent archive verification.
        self._rank_witnesses: dict[
            tuple[str, int], ObservedRankWitness | None
        ] = {}

        def shared_rank_witness(
            market: MarketId, at_ms: int,
        ) -> ObservedRankWitness | None:
            key = (market.canonical, at_ms)
            if key not in self._rank_witnesses:
                self._rank_witnesses[key] = rank_witness_provider(market, at_ms)
            return self._rank_witnesses[key]

        self._baseline_admission = ProspectiveShortBreakoutPairedEntryFilter(
            freeze, False, shared_rank_witness
        )
        self._candidate_admission = ProspectiveShortBreakoutPairedEntryFilter(
            freeze, True, shared_rank_witness
        )
        self._baseline_execution = PaperExecutionAdapter(
            root / "baseline-execution.sqlite3",
            config.execution,
            starting_cash=config.starting_cash,
            startup_timestamp_ms=manifest.start_ms,
        )
        self._candidate_execution = PaperExecutionAdapter(
            root / "candidate-execution.sqlite3",
            config.execution,
            starting_cash=config.starting_cash,
            startup_timestamp_ms=manifest.start_ms,
        )
        self._baseline_facts = EvaluationFactStore(root / "baseline-facts.sqlite3")
        self._candidate_facts = EvaluationFactStore(root / "candidate-facts.sqlite3")
        self._baseline = BaselineReplayPipeline(
            config,
            self._baseline_execution,
            self._baseline_facts,
            selected_markets=markets,
            replay_run_id=f"{freeze.candidate_id}:independent-baseline",
            evidence_class=EvidenceClass.MICROSTRUCTURE,
            decision_engine=(
                None if decision_engine_factory is None
                else decision_engine_factory()
            ),
            opening_candidate_filter=self._baseline_admission,
        )
        self._candidate = BaselineReplayPipeline(
            config,
            self._candidate_execution,
            self._candidate_facts,
            selected_markets=markets,
            replay_run_id=f"{freeze.candidate_id}:independent-candidate",
            evidence_class=EvidenceClass.MICROSTRUCTURE,
            decision_engine=(
                None if decision_engine_factory is None
                else decision_engine_factory()
            ),
            opening_candidate_filter=self._candidate_admission,
        )
        self._last_available_at_ms: int | None = None
        self._seen_records: set[bytes] = set()
        self._record_count = 0
        self._gap_records = 0
        self._record_hash = hashlib.sha256()
        self._failed = False
        self._closed = False
        self._baseline_peak = config.starting_cash
        self._candidate_peak = config.starting_cash
        self._baseline_max_drawdown = ZERO
        self._candidate_max_drawdown = ZERO
        self._utc_window_ledger = PairedAccountUtcWindowLedger(
            started_at_ms=manifest.start_ms,
            starting_cash=config.starting_cash,
        )

    @staticmethod
    def _drawdown(account: PaperAccountState, peak: Decimal) -> Decimal:
        return max(ZERO, (peak - account.equity) / peak)

    def on_record(self, record: ReplayRecord) -> None:
        if self._closed or self._failed:
            raise ShortRankPairedReplayError("paired replay is closed or failed")
        if (
            record.available_at_ms < self._manifest.start_ms
            or record.available_at_ms > self._manifest.end_ms
            or (
                self._last_available_at_ms is not None
                and record.available_at_ms < self._last_available_at_ms
            )
        ):
            self._failed = True
            raise ShortRankPairedReplayError(
                "paired replay has out-of-manifest or nonmonotonic source"
            )
        canonical_record = json.dumps(
            (
                record.record_kind.value,
                record.available_at_ms,
                record.source,
                record.schema_version,
                record.market,
                record.exchange_time_ms,
                record.event_key,
                record.event_kind,
                record.payload_json,
            ),
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        record_identity = hashlib.sha256(canonical_record).digest()
        if record_identity in self._seen_records:
            self._failed = True
            raise ShortRankPairedReplayError(
                "paired replay duplicate source record"
            )
        # The exact same record is presented to both independent replay
        # engines. Any exception invalidates BOTH lanes, not only the loser.
        try:
            self._baseline.on_record(record, record.available_at_ms)
            self._candidate.on_record(record, record.available_at_ms)
        except Exception:
            self._failed = True
            raise
        self._last_available_at_ms = record.available_at_ms
        self._seen_records.add(record_identity)
        self._record_count += 1
        if record.record_kind is SourceRecordKind.DATA_GAP:
            self._gap_records += 1
        self._record_hash.update(canonical_record)
        try:
            self._utc_window_ledger.record(
                at_ms=record.available_at_ms,
                baseline_equity=self._baseline_execution.account.equity,
                baseline_realized=self._realized_net(self._baseline_execution.account),
                candidate_equity=self._candidate_execution.account.equity,
                candidate_realized=self._realized_net(self._candidate_execution.account),
            )
        except Exception:
            self._failed = True
            raise
        for execution, lane in (
            (self._baseline_execution, "baseline"),
            (self._candidate_execution, "candidate"),
        ):
            account = execution.account
            if lane == "baseline":
                self._baseline_peak = max(self._baseline_peak, account.equity)
                self._baseline_max_drawdown = max(
                    self._baseline_max_drawdown,
                    self._drawdown(account, self._baseline_peak),
                )
            else:
                self._candidate_peak = max(self._candidate_peak, account.equity)
                self._candidate_max_drawdown = max(
                    self._candidate_max_drawdown,
                    self._drawdown(account, self._candidate_peak),
                )

    @staticmethod
    def _realized_net(account: PaperAccountState) -> Decimal:
        return (
            account.realized_gross_pnl
            - account.cumulative_fees
            + account.cumulative_funding
        )

    @staticmethod
    def _account_report(
        account: PaperAccountState,
        trades_net: Decimal,
        *,
        closes: int,
        fills: int,
        peak: Decimal,
        max_drawdown: Decimal,
    ) -> dict[str, object]:
        realized = ShortRankIndependentPairedPaperReplay._realized_net(account)
        marked = account.equity - account.starting_cash
        return {
            "starting_cash": str(account.starting_cash),
            "equity": str(account.equity),
            "marked_account_pnl": str(marked),
            "realized_net_account_pnl": str(realized),
            "open_marked_pnl_residual": str(marked - realized),
            "closed_trade_net_sum": str(trades_net),
            "realized_cash_unattributed_to_closed_trades": str(
                realized - trades_net
            ),
            "fill_fees": str(account.cumulative_fees),
            "funding_cash": str(account.cumulative_funding),
            "closed_trades": closes,
            "opening_fills": fills,
            "open_positions": len(account.positions),
            "gross_open_notional": str(account.gross_open_notional),
            "available_margin": str(account.available_margin),
            "observed_peak_equity": str(peak),
            "observed_max_drawdown_fraction": str(max_drawdown),
        }

    def summary(self) -> dict[str, object]:
        if self._closed or self._failed or not self._record_count:
            raise ShortRankPairedReplayError(
                "paired replay has no valid complete record history"
            )
        baseline_trades = self._baseline.finalize(self._manifest.end_ms)
        candidate_trades = self._candidate.finalize(self._manifest.end_ms)
        baseline_account = self._baseline_execution.account
        candidate_account = self._candidate_execution.account
        baseline = self._account_report(
            baseline_account,
            sum((t.net_pnl for t in baseline_trades), ZERO),
            closes=len(baseline_trades),
            fills=self._baseline.session_decision_activity.opening_fills,
            peak=self._baseline_peak,
            max_drawdown=self._baseline_max_drawdown,
        )
        candidate = self._account_report(
            candidate_account,
            sum((t.net_pnl for t in candidate_trades), ZERO),
            closes=len(candidate_trades),
            fills=self._candidate.session_decision_activity.opening_fills,
            peak=self._candidate_peak,
            max_drawdown=self._candidate_max_drawdown,
        )
        if baseline_account.starting_cash != candidate_account.starting_cash:
            raise ShortRankPairedReplayError(
                "independent starting-capital parity mismatch"
            )
        if not (
            self._baseline_execution.health.healthy_for_new_exposure
            and self._candidate_execution.health.healthy_for_new_exposure
        ):
            raise ShortRankPairedReplayError("paired execution health degraded")
        utc_windows = self._utc_window_ledger.reconciled_payload(
            baseline_equity=baseline_account.equity,
            baseline_realized=self._realized_net(baseline_account),
            candidate_equity=candidate_account.equity,
            candidate_realized=self._realized_net(candidate_account),
        )
        return {
            "candidate_id": self._freeze.candidate_id,
            "frozen_forward_start_ms": self._freeze.started_at_ms,
            "source_manifest_id_claimed": self._manifest.manifest_id,
            "paired_observed_record_count": self._record_count,
            "paired_record_stream_sha256": self._record_hash.hexdigest(),
            "source_data_gap_record_count": self._gap_records,
            "fixed_utc_checkpoint_window_reconciliation": utc_windows,
            "baseline": baseline,
            "candidate": candidate,
            "candidate_minus_baseline_marked_account_pnl": str(
                candidate_account.equity - baseline_account.equity
            ),
            "candidate_minus_baseline_realized_net_pnl": str(
                Decimal(str(candidate["realized_net_account_pnl"]))
                - Decimal(str(baseline["realized_net_account_pnl"]))
            ),
            "baseline_admission": self._baseline_admission.summary_payload(),
            "candidate_admission": self._candidate_admission.summary_payload(),
            "same_exact_records_consumed_by_both": True,
            "rank_witness_values_shared_between_lanes": True,
            "independent_simulated_paper_accounts": True,
            "actual_simulated_fills_not_skipped_cash": True,
            "source_manifest_independently_authenticated": False,
            "rank_witness_source_independently_authenticated": False,
            "checkpoint_handoff_continuity_certified": False,
            "complete_forward_observation_maturity_certified": False,
            "full_account_trial": False,
            "ready_for_review": False,
            "promotion_authority": False,
            "execution_authority": False,
            "research_only": True,
        }

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._baseline_facts.close()
        self._candidate_facts.close()
        self._baseline_execution.close()
        self._candidate_execution.close()
