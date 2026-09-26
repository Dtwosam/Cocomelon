from pathlib import Path

WORKFLOW = Path(".github/workflows/continuous-paper.yml")


def test_continuous_paper_worker_is_long_running_and_self_chaining() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    assert 'duration-seconds 19800' in source
    assert 'selection-refresh-seconds 300' in source
    assert 'continuous-paper-state-${{ github.run_id }}-${{ github.run_attempt }}' in source
    assert "gh workflow run continuous-paper.yml" in source
    assert 'source_run_id' in source
    assert '7,37 * * * *' in source


def test_continuous_paper_worker_is_hard_locked_to_paper() -> None:
    source = WORKFLOW.read_text(encoding="utf-8").lower()
    assert "cocomelon_execution_mode: paper" in source
    runtime = Path("src/cocomelon/continuous_paper.py").read_text(encoding="utf-8").lower()
    assert "live_orders: bool = false" in runtime
    assert '"live_orders": false' in runtime
    assert "private_key" not in source
    assert "withdraw" not in source
    assert "transfer" not in source
