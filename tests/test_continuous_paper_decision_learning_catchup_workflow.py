from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(
    ".github/workflows/continuous-paper-decision-learning-catchup.yml"
)


def test_decision_learning_catchup_finds_authenticated_decision_source() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert 'branches: [main]' in source
    assert "src/cocomelon/research/no_trade_forward_opportunity.py" in source
    assert "src/cocomelon/no_trade_forward_opportunity_cli.py" in source
    assert "src/cocomelon/research/no_trade_context_stability.py" in source
    assert "src/cocomelon/no_trade_context_stability_cli.py" in source
    assert "src/cocomelon/research/no_trade_context_candidate.py" in source
    assert "src/cocomelon/research/no_trade_context_prospective.py" in source
    assert "src/cocomelon/no_trade_context_prospective_cli.py" in source
    assert "mon-normal-short-1h-v1.json" in source
    assert "mon-normal-short-1h-v1-source.json" in source
    assert 'cron: "*/15 * * * *"' in source
    assert '"Continuous Mainnet Paper Trader"' in source
    assert '"Continuous Paper Decision Learning Evidence"' in source
    assert "actions: write" in source
    assert "group: continuous-paper-decision-learning-catchup" in source
    assert (
        "Find newest decision-learning-capable paper worker"
        in source
    )
    assert 'run.get("path") != ".github/workflows/continuous-paper.yml"' in source
    assert 'run.get("name") != "Continuous Mainnet Paper Trader"' in source
    assert 'run.get("conclusion") not in {"success", "failure"}' in source
    assert '"Run continuous paper trader"' in source
    assert '"Export compact continuous decision facts"' in source
    assert '"Upload compact continuous decision learning source"' in source
    assert (
        "continuous-paper-decision-learning-source-{run_id}-{attempt}"
        in source
    )
    assert 'digest.startswith("sha256:")' in source


def test_decision_learning_catchup_trusts_authority_negative_receipt() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert (
        "continuous-paper-decision-learning-evidence&per_page=100"
        in source
    )
    assert (
        '".github/workflows/continuous-paper-decision-learning-evidence.yml"'
        in source
    )
    assert (
        'receipt.get("source_kind")'
        in source
    )
    assert '"continuous_paper_decision_learning"' in source
    assert 'receipt.get("research_only") is not True' in source
    assert 'receipt.get("promotion_eligible") is not False' in source
    assert 'receipt.get("execution_ready") is not False' in source
    assert 'receipt.get("hypothetical_pnl") is not False' in source
    assert 'receipt.get("cost_complete") is not False' in source
    assert "source-receipt.json" in source
    assert 'EXPECTED_FORWARD_OPPORTUNITY_SCHEMA_VERSION: "2"' in source
    assert 'EXPECTED_CONTEXT_STABILITY_SCHEMA_VERSION: "3"' in source
    assert 'receipt.get("forward_opportunity_schema_version")' in source
    assert 'receipt.get("context_stability_schema_version") != expected_schema' in source
    assert 'receipt.get("directional_candidate_source")' in source
    assert '"strategy_abstained_only"' in source
    assert 'receipt.get("market_aware") is not True' in source
    assert 'receipt.get("validation_block_consistency_required")' in source
    assert 'EXPECTED_PROSPECTIVE_CANDIDATE_SCHEMA_VERSION: "1"' in source
    assert 'EXPECTED_PROSPECTIVE_CANDIDATE_ID:' in source
    assert 'receipt.get("prospective_candidate_schema_version")' in source
    assert 'receipt.get("prospective_candidate_id")' in source


def test_decision_learning_catchup_dispatches_only_missing_worker() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "LATEST_WORKER_RUN_ID" in source
    assert "LATEST_STATE_UPSTREAM_RUN_ID" in source
    assert (
        "newest decision-capable paper worker is already in "
        "decision-learning evidence"
        in source
    )
    assert (
        "trusted decision-learning evidence already covers same or newer "
        "paper worker"
        in source
    )
    assert (
        "continuous-paper-decision-learning-evidence.yml/runs?per_page=100"
        in source
    )
    assert "decision-learning evidence sync already active" in source
    assert (
        "continuous-paper-decision-learning-evidence.yml/dispatches"
        in source
    )
    assert 'inputs[upstream_run_id]=$LATEST_WORKER_RUN_ID' in source
    assert (
        "dispatched missing decision-learning evidence for "
        "$LATEST_WORKER_RUN_ID"
        in source
    )
