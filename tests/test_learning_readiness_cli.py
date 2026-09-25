from __future__ import annotations

import json
from decimal import Decimal

from cocomelon.domain.market import MarketId
from cocomelon.domain.strategy import Direction
from cocomelon.learning_readiness_cli import main
from cocomelon.research.outcome_learning import (
    LearningEvidenceKind,
    LearningEvidenceLedger,
    LearningEvidenceRecord,
)


def _record(*, eligible_at_ms: int) -> LearningEvidenceRecord:
    return LearningEvidenceRecord(
        kind=LearningEvidenceKind.PAPER_EXECUTION,
        source_record_id=f"paper-{eligible_at_ms}",
        source_evidence_class="microstructure",
        candidate_id="candidate-readiness-cli",
        candidate_spec_id=None,
        campaign_id=None,
        market=MarketId("", "HYPE"),
        direction=Direction.LONG,
        opened_at_ms=10_000,
        closed_at_ms=20_000,
        feature_snapshot_id="0123456789abcdef01234567",
        research_eligible_at_ms=eligible_at_ms,
        gross_realized_pnl=Decimal("10"),
        entry_fees=Decimal("0.5"),
        exit_fees=Decimal("0.5"),
        funding_cash_pnl=Decimal("0"),
        entry_slippage_fraction=Decimal("0.001"),
        exit_slippage_fraction=Decimal("0.001"),
        net_pnl=Decimal("9"),
        net_r=Decimal("0.36"),
    )


def test_learning_readiness_cli_returns_zero_for_structurally_ready_evidence(
    tmp_path,
    capsys,
) -> None:
    root = tmp_path / "learning"
    LearningEvidenceLedger(root).record(_record(eligible_at_ms=20_000))

    code = main(
        [
            "--learning-root",
            str(root),
            "--as-of-ms",
            "30000",
            "--kind",
            "paper_execution",
            "--feature",
            "market",
            "--feature",
            "direction",
        ]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["command"] == "learning-readiness"
    assert payload["structurally_ready"] is True
    assert payload["eligible_record_count"] == 1
    assert payload["promotion_eligible"] is False
    assert payload["execution_ready"] is False


def test_learning_readiness_cli_returns_three_when_evidence_is_not_ready(
    tmp_path,
    capsys,
) -> None:
    root = tmp_path / "learning"
    LearningEvidenceLedger(root).record(_record(eligible_at_ms=50_000))

    code = main(
        [
            "--learning-root",
            str(root),
            "--as-of-ms",
            "30000",
            "--kind",
            "paper_execution",
            "--feature",
            "market",
        ]
    )

    assert code == 3
    payload = json.loads(capsys.readouterr().out)
    assert payload["structurally_ready"] is False
    assert payload["eligible_record_count"] == 0
    assert payload["quarantined_record_count"] == 1


def test_learning_readiness_cli_returns_two_for_invalid_request(
    tmp_path,
    capsys,
) -> None:
    code = main(
        [
            "--learning-root",
            str(tmp_path / "learning"),
            "--as-of-ms",
            "30000",
            "--kind",
            "paper_execution",
            "--feature",
            "not-a-feature",
        ]
    )

    assert code == 2
    payload = json.loads(capsys.readouterr().err)
    assert payload["error_type"] == "ValueError"
