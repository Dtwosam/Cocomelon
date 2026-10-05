from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from cocomelon.domain.features import FeatureSnapshot
from cocomelon.domain.strategy import Direction
from cocomelon.research.learning_feature_snapshots import LearningFeatureSnapshotStore
from cocomelon.research.outcome_learning import (
    LearningEvidenceKind,
    LearningEvidenceLedger,
    LearningEvidenceRecord,
)

ZERO: Final = Decimal("0")
CONTEXT_DIAGNOSTIC_SCHEMA_VERSION = 2

MARGINAL_CONTEXT_DIMENSIONS: Final = (
    "trend_regime",
    "volatility_regime",
    "return_15m_sign",
    "return_1h_sign",
    "funding_sign",
    "book_imbalance_sign",
)


class ContextConditionedPaperError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class _ResolvedRow:
    record: LearningEvidenceRecord
    feature: FeatureSnapshot


@dataclass(frozen=True, slots=True)
class ContextConditionedPaperReport:
    as_of_ms: int
    min_group_rows: int
    records_scanned: int
    paper_execution_records: int
    research_eligible_records: int
    resolved_records: int
    missing_feature_snapshot_ids: tuple[str, ...]
    direction_summary: dict[str, object]
    context_summary: tuple[dict[str, object], ...]
    marginal_summary: dict[str, tuple[dict[str, object], ...]]
    ledger_state_digest: str
    feature_state_digest: str
    schema_version: int = CONTEXT_DIAGNOSTIC_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.as_of_ms < 0:
            raise ValueError("as_of_ms must be non-negative")
        if self.min_group_rows <= 0:
            raise ValueError("min_group_rows must be positive")
        if min(
            self.records_scanned,
            self.paper_execution_records,
            self.research_eligible_records,
            self.resolved_records,
        ) < 0:
            raise ValueError("diagnostic counts must be non-negative")
        if self.paper_execution_records > self.records_scanned:
            raise ValueError("paper execution count cannot exceed scanned count")
        if self.research_eligible_records > self.paper_execution_records:
            raise ValueError("eligible count cannot exceed paper execution count")
        if self.resolved_records > self.research_eligible_records:
            raise ValueError("resolved count cannot exceed eligible count")
        if self.schema_version != CONTEXT_DIAGNOSTIC_SCHEMA_VERSION:
            raise ValueError("unsupported context diagnostic schema")

    def to_dict(self) -> dict[str, object]:
        return {
            "as_of_ms": self.as_of_ms,
            "min_group_rows": self.min_group_rows,
            "records_scanned": self.records_scanned,
            "paper_execution_records": self.paper_execution_records,
            "research_eligible_records": self.research_eligible_records,
            "resolved_records": self.resolved_records,
            "missing_feature_snapshot_ids": self.missing_feature_snapshot_ids,
            "direction_summary": self.direction_summary,
            "context_summary": self.context_summary,
            "marginal_summary": self.marginal_summary,
            "ledger_state_digest": self.ledger_state_digest,
            "feature_state_digest": self.feature_state_digest,
            "diagnostic_only": True,
            "side_suppression_authority": False,
            "promotion_authority": False,
            "execution_authority": False,
            "schema_version": self.schema_version,
        }


def _sign_bucket(value: Decimal | None) -> str:
    if value is None:
        return "missing"
    if value > ZERO:
        return "positive"
    if value < ZERO:
        return "negative"
    return "flat"


def _context_key(row: _ResolvedRow) -> tuple[str, str, str, str, str, str]:
    feature = row.feature
    return (
        feature.trend_regime.value,
        feature.volatility_regime.value,
        _sign_bucket(feature.return_15m),
        _sign_bucket(feature.return_1h),
        _sign_bucket(feature.funding),
        _sign_bucket(feature.book_imbalance),
    )


def _required_execution_value(
    record: LearningEvidenceRecord,
    field: str,
) -> Decimal:
    value = getattr(record, field)
    if not isinstance(value, Decimal):
        raise ContextConditionedPaperError(
            f"paper execution record {record.record_id} is missing {field}"
        )
    return value


def _mean(values: tuple[Decimal, ...]) -> Decimal | None:
    if not values:
        return None
    return sum(values, ZERO) / Decimal(len(values))


def _metrics(rows: tuple[_ResolvedRow, ...]) -> dict[str, object]:
    net_r = tuple(_required_execution_value(row.record, "net_r") for row in rows)
    net_pnl = tuple(_required_execution_value(row.record, "net_pnl") for row in rows)
    entry_fees = tuple(
        _required_execution_value(row.record, "entry_fees") for row in rows
    )
    exit_fees = tuple(
        _required_execution_value(row.record, "exit_fees") for row in rows
    )
    funding = tuple(
        _required_execution_value(row.record, "funding_cash_pnl") for row in rows
    )
    spreads = tuple(
        row.feature.spread_bps
        for row in rows
        if row.feature.spread_bps is not None
    )
    book_ages = tuple(
        Decimal(row.feature.book_age_ms)
        for row in rows
        if row.feature.book_age_ms is not None
    )
    holds = tuple(
        Decimal(row.record.closed_at_ms - row.record.opened_at_ms)
        for row in rows
    )

    mean_net_r = _mean(net_r)
    mean_spread = _mean(spreads)
    mean_book_age = _mean(book_ages)
    mean_hold = _mean(holds)
    wins = sum(1 for value in net_r if value > ZERO)
    losses = sum(1 for value in net_r if value < ZERO)
    flat = len(net_r) - wins - losses

    return {
        "trades": len(rows),
        "wins": wins,
        "losses": losses,
        "flat": flat,
        "net_pnl_sum": str(sum(net_pnl, ZERO)),
        "net_r_sum": str(sum(net_r, ZERO)),
        "mean_net_r": None if mean_net_r is None else str(mean_net_r),
        "fees_sum": str(sum(entry_fees, ZERO) + sum(exit_fees, ZERO)),
        "funding_cash_pnl_sum": str(sum(funding, ZERO)),
        "mean_spread_bps": None if mean_spread is None else str(mean_spread),
        "mean_book_age_ms": (
            None if mean_book_age is None else str(mean_book_age)
        ),
        "mean_hold_ms": None if mean_hold is None else str(mean_hold),
    }


def _direction_summary(
    rows: tuple[_ResolvedRow, ...],
    *,
    min_group_rows: int,
) -> dict[str, object]:
    payload: dict[str, object] = {}
    for direction in (Direction.LONG, Direction.SHORT):
        cohort = tuple(row for row in rows if row.record.direction is direction)
        payload[direction.value] = {
            **_metrics(cohort),
            "sample_sufficient_for_diagnostics": len(cohort) >= min_group_rows,
            "suppression_authority": False,
        }
    return payload


def _context_summary(
    rows: tuple[_ResolvedRow, ...],
    *,
    min_group_rows: int,
) -> tuple[dict[str, object], ...]:
    grouped: defaultdict[
        tuple[str, str, str, str, str, str],
        list[_ResolvedRow],
    ] = defaultdict(list)
    for row in rows:
        grouped[_context_key(row)].append(row)

    output: list[dict[str, object]] = []
    for key in sorted(grouped):
        cohort = tuple(grouped[key])
        long_rows = tuple(
            row for row in cohort if row.record.direction is Direction.LONG
        )
        short_rows = tuple(
            row for row in cohort if row.record.direction is Direction.SHORT
        )
        comparison_ready = (
            len(long_rows) >= min_group_rows
            and len(short_rows) >= min_group_rows
        )
        long_metrics = _metrics(long_rows)
        short_metrics = _metrics(short_rows)
        delta: str | None = None
        if comparison_ready:
            long_mean = _mean(
                tuple(
                    _required_execution_value(row.record, "net_r")
                    for row in long_rows
                )
            )
            short_mean = _mean(
                tuple(
                    _required_execution_value(row.record, "net_r")
                    for row in short_rows
                )
            )
            if long_mean is None or short_mean is None:
                raise ContextConditionedPaperError(
                    "direction comparison unexpectedly lacks mean net R"
                )
            delta = str(long_mean - short_mean)

        output.append(
            {
                "trend_regime": key[0],
                "volatility_regime": key[1],
                "return_15m_sign": key[2],
                "return_1h_sign": key[3],
                "funding_sign": key[4],
                "book_imbalance_sign": key[5],
                "trades": len(cohort),
                "sample_sufficient_for_diagnostics": (
                    len(cohort) >= min_group_rows
                ),
                "direction_comparison_ready": comparison_ready,
                "long": long_metrics,
                "short": short_metrics,
                "mean_net_r_delta_long_minus_short": delta,
                "strategy_authority": False,
            }
        )
    return tuple(output)


def _marginal_value(row: _ResolvedRow, dimension: str) -> str:
    feature = row.feature
    if dimension == "trend_regime":
        return feature.trend_regime.value
    if dimension == "volatility_regime":
        return feature.volatility_regime.value
    if dimension == "return_15m_sign":
        return _sign_bucket(feature.return_15m)
    if dimension == "return_1h_sign":
        return _sign_bucket(feature.return_1h)
    if dimension == "funding_sign":
        return _sign_bucket(feature.funding)
    if dimension == "book_imbalance_sign":
        return _sign_bucket(feature.book_imbalance)
    raise ValueError(f"unsupported marginal context dimension: {dimension}")


def _marginal_summary(
    rows: tuple[_ResolvedRow, ...],
    *,
    min_group_rows: int,
) -> dict[str, tuple[dict[str, object], ...]]:
    payload: dict[str, tuple[dict[str, object], ...]] = {}
    for dimension in MARGINAL_CONTEXT_DIMENSIONS:
        grouped: defaultdict[str, list[_ResolvedRow]] = defaultdict(list)
        for row in rows:
            grouped[_marginal_value(row, dimension)].append(row)

        items: list[dict[str, object]] = []
        for value in sorted(grouped):
            cohort = tuple(grouped[value])
            long_rows = tuple(
                row for row in cohort if row.record.direction is Direction.LONG
            )
            short_rows = tuple(
                row for row in cohort if row.record.direction is Direction.SHORT
            )
            long_ready = len(long_rows) >= min_group_rows
            short_ready = len(short_rows) >= min_group_rows
            items.append(
                {
                    "value": value,
                    "trades": len(cohort),
                    "long": _metrics(long_rows),
                    "short": _metrics(short_rows),
                    "long_sample_sufficient_for_diagnostics": long_ready,
                    "short_sample_sufficient_for_diagnostics": short_ready,
                    "direction_comparison_ready": long_ready and short_ready,
                    "strategy_authority": False,
                }
            )
        payload[dimension] = tuple(items)
    return payload


def build_context_conditioned_paper_report(
    ledger: LearningEvidenceLedger,
    feature_store: LearningFeatureSnapshotStore,
    *,
    as_of_ms: int,
    min_group_rows: int = 3,
) -> ContextConditionedPaperReport:
    if as_of_ms < 0:
        raise ValueError("as_of_ms must be non-negative")
    if min_group_rows <= 0:
        raise ValueError("min_group_rows must be positive")

    records = ledger.iter_records()
    paper_records = tuple(
        record
        for record in records
        if record.kind is LearningEvidenceKind.PAPER_EXECUTION
    )
    eligible = tuple(
        record
        for record in paper_records
        if record.research_eligible_at_ms <= as_of_ms
    )

    resolved: list[_ResolvedRow] = []
    missing: list[str] = []
    for record in eligible:
        verified = feature_store.load(record.feature_snapshot_id)
        if verified is None:
            missing.append(record.feature_snapshot_id)
            continue
        feature = verified.snapshot
        if feature.market != record.market:
            raise ContextConditionedPaperError(
                "CONTEXT_DIAGNOSTIC_FEATURE_MARKET_MISMATCH"
            )
        if feature.as_of_ms > record.opened_at_ms:
            raise ContextConditionedPaperError(
                "CONTEXT_DIAGNOSTIC_FEATURE_AFTER_OPEN"
            )
        if feature.source_received_at_ms > record.opened_at_ms:
            raise ContextConditionedPaperError(
                "CONTEXT_DIAGNOSTIC_FEATURE_SOURCE_AFTER_OPEN"
            )
        resolved.append(_ResolvedRow(record=record, feature=feature))

    rows = tuple(
        sorted(
            resolved,
            key=lambda row: (
                row.record.opened_at_ms,
                row.record.market.canonical,
                row.record.record_id,
            ),
        )
    )
    return ContextConditionedPaperReport(
        as_of_ms=as_of_ms,
        min_group_rows=min_group_rows,
        records_scanned=len(records),
        paper_execution_records=len(paper_records),
        research_eligible_records=len(eligible),
        resolved_records=len(rows),
        missing_feature_snapshot_ids=tuple(sorted(set(missing))),
        direction_summary=_direction_summary(
            rows,
            min_group_rows=min_group_rows,
        ),
        context_summary=_context_summary(
            rows,
            min_group_rows=min_group_rows,
        ),
        marginal_summary=_marginal_summary(
            rows,
            min_group_rows=min_group_rows,
        ),
        ledger_state_digest=ledger.state_digest,
        feature_state_digest=feature_store.state_digest,
    )
