from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from cocomelon.domain.evaluation import (
    EvaluationDatasetManifest,
    ReplayEvaluationSource,
    TradeEvaluationSample,
)
from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.domain.replay import ReplayManifest, ReplayResult
from cocomelon.evaluation.store import EvaluationFactStore
from cocomelon.journal.store import JournalStore


class EvaluationDatasetError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class DatasetBuildResult:
    manifest: EvaluationDatasetManifest
    samples: tuple[TradeEvaluationSample, ...]
    excluded_trade_ids: tuple[str, ...]
    exclusion_reasons: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        ordered_samples = tuple(
            sorted(
                self.samples,
                key=lambda item: (
                    item.decision_timestamp_ms,
                    item.opened_at_ms,
                    item.closed_at_ms,
                    item.trade_id,
                ),
            )
        )
        ordered_reasons = tuple(sorted(set(self.exclusion_reasons)))
        excluded = tuple(sorted(set(self.excluded_trade_ids)))
        reason_ids = tuple(sorted({trade_id for trade_id, _ in ordered_reasons}))
        if excluded != reason_ids:
            raise ValueError("excluded_trade_ids must match exclusion_reasons")
        included_ids = {item.trade_id for item in ordered_samples}
        if included_ids & set(excluded):
            raise ValueError("included and excluded trade ids must not overlap")
        if len(included_ids) != len(ordered_samples):
            raise ValueError("samples must contain unique trade ids")
        object.__setattr__(self, "samples", ordered_samples)
        object.__setattr__(self, "excluded_trade_ids", excluded)
        object.__setattr__(self, "exclusion_reasons", ordered_reasons)


def _source_for_run(
    journal: JournalStore,
    run_id: str,
) -> tuple[ReplayEvaluationSource, ReplayManifest, ReplayResult]:
    result = journal.load_replay_result(run_id)
    if result is None:
        raise EvaluationDatasetError(f"UNKNOWN_REPLAY_RESULT:{run_id}")
    manifest = journal.load_manifest(result.manifest_id)
    if manifest is None:
        raise EvaluationDatasetError(f"MISSING_REPLAY_MANIFEST:{result.manifest_id}")
    if manifest.evidence_class is not result.evidence_class:
        raise EvaluationDatasetError(f"REPLAY_EVIDENCE_MISMATCH:{run_id}")
    if manifest.start_ms != result.start_ms or manifest.end_ms != result.end_ms:
        raise EvaluationDatasetError(f"REPLAY_WINDOW_MISMATCH:{run_id}")
    return (
        ReplayEvaluationSource(
            run_id=result.run_id,
            manifest_id=result.manifest_id,
            result_digest=result.result_digest,
            evidence_class=result.evidence_class,
            start_ms=result.start_ms,
            end_ms=result.end_ms,
            data_complete=result.data_complete,
        ),
        manifest,
        result,
    )


def _sample_from_trade(
    trade: TradeJournalEntry,
    *,
    facts: EvaluationFactStore,
    source: ReplayEvaluationSource,
) -> tuple[TradeEvaluationSample | None, str | None, str | None]:
    run_id = trade.replay_run_id
    if run_id is None:
        return None, None, "MISSING_REPLAY_RUN_ID"
    fact = facts.load_decision_by_strategy_id(trade.strategy_decision_id, run_id)
    if fact is None:
        return None, None, "MISSING_DECISION_FACT"
    if fact.market != trade.market:
        return None, fact.fact_id, "DECISION_MARKET_MISMATCH"
    if fact.direction is not trade.direction:
        return None, fact.fact_id, "DECISION_DIRECTION_MISMATCH"
    if fact.feature_snapshot_id != trade.feature_snapshot_id:
        return None, fact.fact_id, "FEATURE_SNAPSHOT_MISMATCH"
    if trade.evidence_class is not source.evidence_class:
        return None, fact.fact_id, "EVIDENCE_CLASS_MISMATCH"
    if fact.lead_strategy is None:
        return None, fact.fact_id, "MISSING_LEAD_STRATEGY"
    if fact.timestamp_ms > trade.opened_at_ms:
        return None, fact.fact_id, "DECISION_AFTER_OPEN"
    return (
        TradeEvaluationSample(
            trade_id=trade.trade_id,
            replay_run_id=run_id,
            strategy_decision_id=trade.strategy_decision_id,
            market=trade.market,
            direction=trade.direction,
            decision_timestamp_ms=fact.timestamp_ms,
            opened_at_ms=trade.opened_at_ms,
            closed_at_ms=trade.closed_at_ms,
            score=fact.score,
            lead_strategy=fact.lead_strategy,
            trend_regime=fact.trend_regime,
            volatility_regime=fact.volatility_regime,
            evidence_class=trade.evidence_class,
            gross_realized_pnl=trade.gross_realized_pnl,
            entry_fees=trade.entry_fees,
            exit_fees=trade.exit_fees,
            funding_cash_pnl=trade.funding_cash_pnl,
            net_pnl=trade.net_pnl,
            entry_slippage_amount=trade.entry_slippage_amount,
            exit_slippage_amount=trade.exit_slippage_amount,
            net_r=trade.net_r,
            equity_before=trade.equity_before,
            equity_after=trade.equity_after,
            holding_duration_ms=trade.holding_duration_ms,
            reason_codes=fact.reason_codes,
        ),
        fact.fact_id,
        None,
    )


def build_evaluation_dataset(
    journal: JournalStore,
    facts: EvaluationFactStore,
    *,
    replay_run_ids: Sequence[str],
    code_revision: str,
    allow_mixed_evidence: bool = False,
) -> DatasetBuildResult:
    if not code_revision.strip():
        raise ValueError("code_revision must not be empty")
    if not replay_run_ids:
        raise ValueError("replay_run_ids must not be empty")
    if any(not run_id.strip() for run_id in replay_run_ids):
        raise ValueError("replay_run_ids values must not be empty")
    run_ids = tuple(sorted(set(replay_run_ids)))

    sources: list[ReplayEvaluationSource] = []
    manifests: dict[str, ReplayManifest] = {}
    results: dict[str, ReplayResult] = {}
    expected_trade_runs: dict[str, set[str]] = {}
    for run_id in run_ids:
        source, manifest, result = _source_for_run(journal, run_id)
        sources.append(source)
        manifests[run_id] = manifest
        results[run_id] = result
        for trade_id in result.closed_trade_ids:
            expected_trade_runs.setdefault(trade_id, set()).add(run_id)

    evidence_classes = {source.evidence_class for source in sources}
    mixed = len(evidence_classes) > 1
    if mixed and not allow_mixed_evidence:
        raise EvaluationDatasetError("MIXED_EVIDENCE")

    trade_by_id: dict[str, TradeJournalEntry] = {}
    for trade in journal.iter_trades():
        if trade.trade_id in trade_by_id:
            raise EvaluationDatasetError(f"DUPLICATE_JOURNAL_TRADE:{trade.trade_id}")
        trade_by_id[trade.trade_id] = trade

    samples: list[TradeEvaluationSample] = []
    included_fact_ids: list[str] = []
    exclusions: list[tuple[str, str]] = []
    duplicate_source_ids = {
        trade_id for trade_id, run_set in expected_trade_runs.items() if len(run_set) > 1
    }
    for trade_id in sorted(expected_trade_runs):
        run_set = expected_trade_runs[trade_id]
        if trade_id in duplicate_source_ids:
            exclusions.append((trade_id, "DUPLICATE_TRADE_REFERENCE"))
            continue
        run_id = next(iter(run_set))
        trade = trade_by_id.get(trade_id)
        if trade is None:
            exclusions.append((trade_id, "MISSING_TRADE"))
            continue
        if trade.replay_run_id != run_id:
            exclusions.append((trade_id, "REPLAY_RUN_MISMATCH"))
            continue
        source = next(item for item in sources if item.run_id == run_id)
        sample, fact_id, reason = _sample_from_trade(trade, facts=facts, source=source)
        if reason is not None:
            exclusions.append((trade_id, reason))
            continue
        if sample is None or fact_id is None:
            raise EvaluationDatasetError(f"INVALID_SAMPLE_ASSEMBLY:{trade_id}")
        samples.append(sample)
        included_fact_ids.append(fact_id)

    requested_run_set = set(run_ids)
    unexpected_trades = tuple(
        trade
        for trade in trade_by_id.values()
        if trade.replay_run_id in requested_run_set and trade.trade_id not in expected_trade_runs
    )
    for trade in unexpected_trades:
        exclusions.append((trade.trade_id, "REPLAY_RESULT_TRADE_MISMATCH"))

    exclusion_counts = Counter(trade_id for trade_id, _ in exclusions)
    if any(count > 1 for count in exclusion_counts.values()):
        raise EvaluationDatasetError("DUPLICATE_EXCLUSION_REASON")

    equity_fact_ids = tuple(
        fact.fact_id
        for run_id in run_ids
        for fact in facts.iter_equity_facts(run_id)
    )
    gap_refs = tuple(
        gap_ref
        for run_id in run_ids
        for gap_ref in manifests[run_id].gap_refs
    )
    manifest = EvaluationDatasetManifest(
        sources=tuple(sources),
        trade_ids=tuple(sample.trade_id for sample in samples),
        decision_fact_ids=tuple(included_fact_ids),
        equity_fact_ids=equity_fact_ids,
        start_ms=min(source.start_ms for source in sources),
        end_ms=max(source.end_ms for source in sources),
        code_revision=code_revision,
        data_complete=all(source.data_complete for source in sources),
        gap_refs=gap_refs,
        mixed_evidence_diagnostic=mixed,
    )
    facts.record_dataset_manifest(manifest)
    exclusion_reasons = tuple(sorted(exclusions))
    return DatasetBuildResult(
        manifest=manifest,
        samples=tuple(samples),
        excluded_trade_ids=tuple(trade_id for trade_id, _ in exclusion_reasons),
        exclusion_reasons=exclusion_reasons,
    )
