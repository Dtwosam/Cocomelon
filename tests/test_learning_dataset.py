from __future__ import annotations

from decimal import Decimal

from cocomelon.domain.market import MarketId
from cocomelon.domain.strategy import Direction
from cocomelon.research.learning_dataset import build_learning_dataset_snapshot
from cocomelon.research.outcome_learning import (
    LearningEvidenceKind,
    LearningEvidenceLedger,
    LearningEvidenceRecord,
)

HYPE = MarketId("", "HYPE")
SOL = MarketId("", "SOL")


def _prospective(*, eligible_at_ms: int) -> LearningEvidenceRecord:
    return LearningEvidenceRecord(
        kind=LearningEvidenceKind.PROSPECTIVE_PAPER,
        source_record_id="prospective-outcome-1",
        source_evidence_class="prospective_clean",
        candidate_id="hype-v3",
        candidate_spec_id="a" * 64,
        campaign_id="campaign-v3",
        market=HYPE,
        direction=Direction.LONG,
        opened_at_ms=10_000,
        closed_at_ms=20_000,
        feature_snapshot_id="feature-prospective",
        research_eligible_at_ms=eligible_at_ms,
        context_state_1h="down/bearish/near_basket",
        gross_return_fraction=Decimal("0.02"),
        modeled_cost_fraction=Decimal("0.0016"),
        net_return_fraction=Decimal("0.0184"),
    )


def _execution(
    *,
    kind: LearningEvidenceKind,
    source_record_id: str,
    candidate_id: str,
    eligible_at_ms: int,
    opened_at_ms: int,
) -> LearningEvidenceRecord:
    return LearningEvidenceRecord(
        kind=kind,
        source_record_id=source_record_id,
        source_evidence_class="microstructure",
        candidate_id=candidate_id,
        candidate_spec_id=None,
        campaign_id=None,
        market=SOL,
        direction=Direction.SHORT,
        opened_at_ms=opened_at_ms,
        closed_at_ms=opened_at_ms + 10_000,
        feature_snapshot_id=f"feature-{source_record_id}",
        research_eligible_at_ms=eligible_at_ms,
        gross_realized_pnl=Decimal("10"),
        entry_fees=Decimal("0.45"),
        exit_fees=Decimal("0.44"),
        funding_cash_pnl=Decimal("-0.10"),
        entry_slippage_fraction=Decimal("0.001"),
        exit_slippage_fraction=Decimal("0.002"),
        net_pnl=Decimal("9.01"),
        net_r=Decimal("0.3604"),
    )


def test_snapshot_exposes_only_eligible_records_and_separates_metric_families(
    tmp_path,
) -> None:
    ledger = LearningEvidenceLedger(tmp_path)
    prospective = _prospective(eligible_at_ms=200_000)
    paper = _execution(
        kind=LearningEvidenceKind.PAPER_EXECUTION,
        source_record_id="paper-1",
        candidate_id="paper-sol-short",
        eligible_at_ms=50_000,
        opened_at_ms=20_000,
    )
    live = _execution(
        kind=LearningEvidenceKind.LIVE_EXECUTION,
        source_record_id="live-1",
        candidate_id="live-sol-short",
        eligible_at_ms=100_000,
        opened_at_ms=30_000,
    )
    for item in (prospective, paper, live):
        assert ledger.record(item) is True

    snapshot = build_learning_dataset_snapshot(ledger, as_of_ms=150_000)

    assert snapshot.prospective_records == ()
    assert snapshot.paper_execution_records == (paper,)
    assert snapshot.live_execution_records == (live,)
    assert snapshot.eligible_records == (paper, live)
    assert snapshot.manifest.quarantined_record_ids == (prospective.record_id,)
    assert snapshot.manifest.candidate_ids == (
        "live-sol-short",
        "paper-sol-short",
    )
    payload = snapshot.manifest.to_dict()
    assert payload["eligible_record_count"] == 2
    assert payload["quarantined_record_count"] == 1
    assert payload["prospective_record_count"] == 0
    assert payload["paper_execution_record_count"] == 1
    assert payload["live_execution_record_count"] == 1
    assert len(snapshot.manifest.dataset_id) == 64


def test_quarantined_prospective_record_enters_only_after_eligibility_boundary(
    tmp_path,
) -> None:
    ledger = LearningEvidenceLedger(tmp_path)
    prospective = _prospective(eligible_at_ms=200_000)
    ledger.record(prospective)

    before = build_learning_dataset_snapshot(ledger, as_of_ms=199_999)
    at_boundary = build_learning_dataset_snapshot(ledger, as_of_ms=200_000)

    assert before.prospective_records == ()
    assert before.manifest.quarantined_record_ids == (prospective.record_id,)
    assert at_boundary.prospective_records == (prospective,)
    assert at_boundary.manifest.quarantined_record_ids == ()
    assert before.manifest.dataset_id != at_boundary.manifest.dataset_id


def test_dataset_identity_binds_full_ledger_state_even_for_quarantined_records(
    tmp_path,
) -> None:
    ledger = LearningEvidenceLedger(tmp_path)
    paper = _execution(
        kind=LearningEvidenceKind.PAPER_EXECUTION,
        source_record_id="paper-1",
        candidate_id="paper-sol-short",
        eligible_at_ms=50_000,
        opened_at_ms=20_000,
    )
    ledger.record(paper)
    first = build_learning_dataset_snapshot(ledger, as_of_ms=100_000)

    future = _prospective(eligible_at_ms=200_000)
    ledger.record(future)
    second = build_learning_dataset_snapshot(ledger, as_of_ms=100_000)

    assert first.eligible_records == second.eligible_records
    assert first.manifest.ledger_state_digest != second.manifest.ledger_state_digest
    assert first.manifest.dataset_id != second.manifest.dataset_id
    assert second.manifest.quarantined_record_ids == (future.record_id,)
