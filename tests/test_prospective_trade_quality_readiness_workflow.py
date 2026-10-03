from __future__ import annotations

from pathlib import Path
from textwrap import dedent


def test_prospective_readiness_workflow_is_fail_closed() -> None:
    source = Path(
        ".github/workflows/prospective-trade-quality-readiness.yml"
    ).read_text(encoding="utf-8")

    assert "Prospective Cadence Prediction Ledger" in source
    assert "Prospective Cadence A/B Ledger" in source
    assert "Prospective Side-Conditioned Timing Ledger" in source
    assert "github.event.workflow_run.conclusion == 'success'" not in source
    assert 'READINESS_ISSUE: "695"' in source
    assert (
        "evaluate_prospective_trade_quality_readiness.py"
        in source
    )
    assert "Resolve latest coherent immutable ledgers" in source
    assert "completed_runs(workflow_file" in source
    assert 'latest.get("conclusion") != "success"' in source
    assert "artifact_for_run(" in source
    assert "Artifact digest mismatch" in source
    assert "cadence_signature(" in source
    assert "No authenticated prediction/comparison ledger pair shares" in source
    assert "cadence_cohort_row_count" in source
    assert "coherent cadence cohort rows" in source
    assert "**Status:** BLOCKED" in source
    blocked = source.split(
        "      - name: Publish blocked readiness status",
        1,
    )[1].split(
        "      - name: Fail closed on readiness integrity",
        1,
    )[0]
    assert "python - <<'PY'" in blocked
    assert "LEDGER_OUTCOME" in blocked
    assert "EVALUATE_OUTCOME" in blocked
    assert "**Execution authority:** `false`" in blocked
    assert "**Promotion authority:** `false`" in blocked
    assert "<<EOF" not in blocked
    assert "Fail closed on readiness integrity" in source
    assert "prospective-trade-quality-readiness.json" in source
    assert "paper " in source
    assert "entries, timing, sizing, stops, risk, promotion state" in source
    assert "no authority to change" in source



def test_prospective_readiness_embedded_resolver_python_compiles() -> None:
    source = Path(
        ".github/workflows/prospective-trade-quality-readiness.yml"
    ).read_text(encoding="utf-8")
    resolver = source.split(
        "      - name: Resolve latest coherent immutable ledgers",
        1,
    )[1].split(
        "      - name: Build fail-closed readiness manifest",
        1,
    )[0]
    embedded = resolver.split(
        "          python - <<'PY'\n",
        1,
    )[1].split(
        "\n          PY",
        1,
    )[0]
    compile(
        dedent(embedded),
        "<prospective-readiness-resolver>",
        "exec",
    )
