from __future__ import annotations

from pathlib import Path

PAPER_WORKFLOW = Path(".github/workflows/continuous-paper.yml")
DECISION_WORKFLOW = Path(
    ".github/workflows/continuous-paper-decision-learning-evidence.yml"
)


def test_paper_worker_publishes_decision_learning_without_opening_dependency() -> None:
    source = PAPER_WORKFLOW.read_text(encoding="utf-8")

    upload_at = source.index(
        "- name: Upload compact continuous decision learning source"
    )
    durable_at = source.index(
        "- name: Pack durable continuous paper state"
    )
    upload = source[upload_at:durable_at]

    assert "id: decision_learning_upload" in upload
    assert "steps.decision_fact_export.outcome == 'success'" in upload
    assert "learning-decisions/records/*.json" in upload
    assert "learning-features/records/*.json" in upload
    assert "continuous-paper-decision-learning-source-" in upload
    assert "continuous-paper-state/learning-decisions" in upload
    assert "continuous-paper-state/learning-features" in upload
    assert "continuous-paper-state/learning-decisions-summary.json" in upload
    assert "opening-lineage" not in upload
    assert "journal.sqlite3" not in upload
    assert "continue-on-error: true" in upload


def test_decision_learning_upload_stays_off_critical_handoff_path() -> None:
    source = PAPER_WORKFLOW.read_text(encoding="utf-8")

    fast_dispatch_at = source.index(
        "- name: Queue exact successor from fast resume"
    )
    decision_export_at = source.index(
        "- name: Export compact continuous decision facts"
    )
    decision_upload_at = source.index(
        "- name: Upload compact continuous decision learning source"
    )
    decision_summary_at = source.index(
        "- name: Render compact decision learning handoff summary"
    )
    durable_pack_at = source.index(
        "- name: Pack durable continuous paper state"
    )

    assert (
        fast_dispatch_at
        < decision_export_at
        < decision_upload_at
        < decision_summary_at
        < durable_pack_at
    )


def test_decision_learning_workflow_authenticates_exact_worker_source() -> None:
    source = DECISION_WORKFLOW.read_text(encoding="utf-8")

    assert 'workflows: ["Continuous Mainnet Paper Trader"]' in source
    assert "group: continuous-paper-decision-learning-evidence" in source
    assert 'run.get("path") != ".github/workflows/continuous-paper.yml"' in source
    assert 'run.get("name") != "Continuous Mainnet Paper Trader"' in source
    assert 'run.get("conclusion") not in {"success", "failure"}' in source
    assert '"Run continuous paper trader"' in source
    assert '"Export compact continuous decision facts"' in source
    assert '"Upload compact continuous decision learning source"' in source
    assert "continuous-paper-decision-learning-source-${RUN_ID}-${RUN_ATTEMPT}" in source
    assert 'digest.startswith("sha256:")' in source
    assert "incoming/decision/learning-decisions/records" in source
    assert "incoming/decision/learning-features/records" in source
    assert "opening-lineage" not in source
    assert "journal.sqlite3" not in source


def test_decision_learning_workflow_is_authority_negative() -> None:
    source = DECISION_WORKFLOW.read_text(encoding="utf-8")
    lowered = source.lower()

    assert "cocomelon-no-trade-forward-opportunity" in source
    assert "no-trade-forward-opportunity.json" in source
    assert '"hypothetical_pnl": False' in source
    assert '"cost_complete": False' in source
    assert '"research_only": True' in source
    assert '"promotion_eligible": False' in source
    assert '"execution_ready": False' in source
    assert "labels are future market returns, not hypothetical PnL" in source
    assert "continuous-paper-decision-learning-evidence" in source
    assert "retention-days: 90" in source
    assert "private_key" not in lowered
    assert "withdraw" not in lowered
    assert "transfer" not in lowered



def test_decision_learning_handoff_summary_exposes_population_and_upload() -> None:
    source = PAPER_WORKFLOW.read_text(encoding="utf-8")

    summary_at = source.index(
        "- name: Render compact decision learning handoff summary"
    )
    durable_at = source.index(
        "- name: Pack durable continuous paper state"
    )
    summary = source[summary_at:durable_at]

    assert "learning-decisions-summary.json" in summary
    assert "DECISION_SOURCE_UPLOAD_OUTCOME" in summary
    assert "steps.decision_learning_upload.outcome" in summary
    assert "selected decision facts" in summary
    assert "LONG decisions" in summary
    assert "SHORT decisions" in summary
    assert "NO_TRADE decisions" in summary
    assert "decision state digest" in summary
    assert "research-only: true" in summary
    assert "execution enabled: false" in summary
