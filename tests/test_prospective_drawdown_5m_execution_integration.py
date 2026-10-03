from pathlib import Path


def test_continuous_paper_freezes_drawdown_5m_candidate_state() -> None:
    source = Path("src/cocomelon/continuous_paper.py").read_text(
        encoding="utf-8"
    )

    assert "ProspectiveDrawdown5mExecutionState" in source
    assert "_restore_prospective_drawdown_5m_execution(" in source
    assert "PROSPECTIVE_DRAWDOWN_5M_EXECUTION_STATE_FILENAME" in source
    assert "prospective_drawdown_5m_execution_state.payload()" in source


def test_continuous_paper_builds_drawdown_source_after_full_stack() -> None:
    source = Path("src/cocomelon/continuous_paper.py").read_text(
        encoding="utf-8"
    )

    full_stack_index = source.index(
        "full_stack_forward_markout = ("
    )
    candidate_index = source.index(
        "prospective_drawdown_5m_execution_source("
    )
    summary_index = source.index(
        "prospective_drawdown_5m_execution_summary("
    )

    assert full_stack_index < candidate_index < summary_index
    assert "opening_opportunity_store.iter_records()" in source[
        candidate_index:
    ]
    assert "opening_opportunity_exit_book_store.iter_records()" in source[
        candidate_index:
    ]
    assert "replacement_funding_store.iter_records()" in source[
        candidate_index:
    ]
    assert "prospective_drawdown_5m_execution_restore_error" in source
    assert "changes_risk_limits" in source[candidate_index:summary_index]


def test_continuous_paper_publishes_drawdown_5m_artifacts() -> None:
    workflow = Path(".github/workflows/continuous-paper.yml").read_text(
        encoding="utf-8"
    )

    for filename in (
        "prospective-drawdown-5m-execution-state.json",
        "prospective-drawdown-5m-execution-source.json",
        "prospective-drawdown-5m-execution-summary.json",
    ):
        assert f"continuous-paper-state/{filename}" in workflow

    assert "Drawdown-blocked fixed-5m execution shadow" in workflow
    assert "RESEARCH ONLY / NO RISK-LIMIT CHANGE" in workflow
