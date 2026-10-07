from __future__ import annotations

from pathlib import Path

LEARNING_SOURCE_WORKFLOWS = (
    (
        ".github/workflows/prospective-two-strike-stop-filter-ledger.yml",
        "latest_successful_with_compact_artifact",
    ),
    (
        ".github/workflows/prospective-full-stack-reflow-exact-ledger.yml",
        "latest_evidence_eligible_with_compact_artifact",
    ),
    (
        ".github/workflows/prospective-consecutive-loss-cooldown-ledger.yml",
        "latest_evidence_eligible_with_compact_artifact",
    ),
)

CADENCE_SOURCE_WORKFLOWS = (
    ".github/workflows/prospective-cadence-microstructure.yml",
    ".github/workflows/prospective-cadence-comparison.yml",
)


CADENCE_LEDGER_WORKFLOWS = (
    (
        ".github/workflows/prospective-cadence-prediction-ledger.yml",
        "latest_success_with_prospective_artifact",
        "cadence-microstructure-prospective-",
    ),
    (
        ".github/workflows/prospective-cadence-comparison-ledger.yml",
        "latest_success_with_comparison_artifact",
        "cadence-model-comparison-",
    ),
)


def _source(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def test_profit_lock_source_accepts_only_durable_upgrade_handoff_failures() -> None:
    source = _source(
        ".github/workflows/profit-lock-execution-ledger.yml"
    )
    resolver = source.split(
        "      - name: Resolve exact source paper run",
        1,
    )[1].split("\n      - name:", 1)[0]

    assert "artifact_for_run()" in resolver
    assert "paper_run_is_evidence_eligible()" in resolver
    assert "wait_for_paper_run_completion()" in resolver
    assert "continuous-paper-learning-source-" in resolver
    assert "latest_evidence_eligible_with_compact_artifact" in resolver
    assert "Fail closed on upgrade handoff source" in resolver
    assert "selected source has no authenticated compact artifact" in resolver


def test_momentum_source_accepts_only_durable_upgrade_handoff_failures() -> None:
    source = _source(
        ".github/workflows/prospective-momentum-band-entry-ledger.yml"
    )
    resolver = source.split(
        "      - name: Resolve exact source paper run",
        1,
    )[1].split("\n      - name:", 1)[0]

    assert "artifact_for_run()" in resolver
    assert "paper_run_is_evidence_eligible()" in resolver
    assert "continuous-paper-learning-source-" in resolver
    assert "latest_evidence_eligible_with_compact_artifact" in resolver
    assert "Fail closed on upgrade handoff source" in resolver
    assert "selected source has no authenticated compact artifact" in resolver


def test_full_stack_matched_source_accepts_only_durable_upgrade_handoff_failures() -> None:
    source = _source(
        ".github/workflows/prospective-full-stack-matched-trade-ledger.yml"
    )
    resolver = source.split(
        "      - name: Resolve exact source paper run",
        1,
    )[1].split("\n      - name:", 1)[0]

    assert "artifact_for_run()" in resolver
    assert "paper_run_is_evidence_eligible()" in resolver
    assert "continuous-paper-learning-source-" in resolver
    assert "latest_evidence_eligible_with_compact_artifact" in resolver
    assert "Fail closed on upgrade handoff source" in resolver
    assert "selected source has no authenticated compact artifact" in resolver


def test_learning_source_consumers_skip_artifactless_runs() -> None:
    for path, fallback_mode in LEARNING_SOURCE_WORKFLOWS:
        source = _source(path)
        resolver = source.split(
            "      - name: Resolve exact source paper run",
            1,
        )[1].split("\n      - name:", 1)[0]

        assert "artifact_for_run()" in resolver
        assert "continuous-paper-learning-source-" in resolver
        assert fallback_mode in resolver
        assert (
            "selected source has no authenticated compact artifact"
            in resolver
        )
        assert (
            "expected exactly one non-expired source artifact named"
            not in resolver
        )
        if "reflow-exact" in path or "consecutive-loss-cooldown" in path:
            assert 'actions/runs/$candidate_run_id/jobs?per_page=100' in resolver
            assert '"Run continuous paper trader"' in resolver
            assert '"Upload compact continuous learning source"' in resolver
            assert "allowed_failed_steps" in resolver
            assert "frozenset(failed_steps) not in allowed_failed_steps" in resolver
            assert "Queue exact successor from fast resume" in resolver


def test_exact_path_export_skips_artifactless_success_runs() -> None:
    source = _source(
        ".github/workflows/continuous-paper-exact-path-export.yml"
    )
    resolver = source.split(
        "      - name: Resolve exact source paper run",
        1,
    )[1].split("\n      - name:", 1)[0]

    assert "artifact_for_run()" in resolver
    assert "continuous-paper-state-" in resolver
    assert "latest_successful_with_state_artifact" in resolver
    assert (
        "selected source has no authenticated paper-state artifact"
        in resolver
    )


def test_cadence_producers_require_compact_artifacts_at_resolution() -> None:
    for path in CADENCE_SOURCE_WORKFLOWS:
        source = _source(path)
        resolver = source.split(
            "      - name: Resolve source paper run",
            1,
        )[1].split("\n      - ", 1)[0]

        assert "required_artifacts_for_run()" in resolver
        assert "paper_run_is_evidence_eligible()" in resolver
        assert "continuous-paper-cadence-shadow-" in resolver
        assert "continuous-paper-learning-features-" in resolver
        assert "latest_evidence_eligible_with_cadence_artifacts" in resolver
        assert "Queue fallback exact successor continuous paper worker" in resolver
        assert "Queue exact successor from fast resume" in resolver


def test_cadence_ledgers_skip_artifactless_producer_runs() -> None:
    for path, fallback, prefix in CADENCE_LEDGER_WORKFLOWS:
        source = _source(path)
        resolver = source.split(
            "      - name: Resolve source ",
            1,
        )[1].split("\n      - name:", 1)[0]

        assert "source_has_artifact()" in resolver
        assert prefix in resolver
        assert fallback in resolver
        assert "Manual source run is missing its required artifact." in resolver


def test_side_conditioned_timing_requires_artifact_at_resolution() -> None:
    source = _source(
        ".github/workflows/prospective-side-conditioned-timing.yml"
    )
    resolver = source.split(
        "      - name: Resolve source paper run",
        1,
    )[1].split("\n      - ", 1)[0]

    assert "timing_artifact_for_run()" in resolver
    assert "continuous-paper-side-conditioned-timing-" in resolver
    assert "paper_run_is_evidence_eligible()" in resolver
    assert "latest_evidence_eligible_with_timing_artifact" in resolver
    assert "Queue fallback exact successor continuous paper worker" in resolver
    assert "Queue exact successor from fast resume" in resolver
    assert (
        "No evidence-eligible continuous-paper run has the compact timing artifact."
        in resolver
    )


def test_long_trend_gate_artifact_parser_avoids_shell_quote_collision() -> None:
    source = _source(
        ".github/workflows/prospective-long-trend-execution-shadow.yml"
    )
    gate = source.split(
        "      - name: Resolve durable execution-shadow gate",
        1,
    )[1].split(
        "      - name: Publish waiting-for-gate status",
        1,
    )[0]

    assert 'print(item["id"], item["name"], digest, sep="|")' in gate
    assert "item['id']" not in gate



DURABLE_HANDOFF_COMPACT_CONSUMERS = (
    ".github/workflows/prospective-momentum-fast-markout-ledger.yml",
    ".github/workflows/prospective-long-trend-carveout-fast-markout-ledger.yml",
    ".github/workflows/prospective-long-trend-execution-shadow.yml",
)


DURABLE_HANDOFF_STATE_CONSUMERS = (
    ".github/workflows/prospective-long-trend-5m-exact.yml",
    ".github/workflows/prospective-long-trend-15m-exact.yml",
)


def test_legacy_compact_consumers_accept_only_authenticated_durable_failures() -> None:
    for path in DURABLE_HANDOFF_COMPACT_CONSUMERS:
        source = _source(path)
        resolver = source.split(
            "      - name: Resolve exact source paper run",
            1,
        )[1].split("\n      - name:", 1)[0]

        assert "paper_run_is_evidence_eligible()" in resolver
        assert "continuous-paper-learning-source-" in resolver
        assert "latest_evidence_eligible_with_compact_artifact" in resolver
        assert '"Run continuous paper trader"' in resolver
        assert '"Measure durable continuous paper state"' in resolver
        assert '"Upload durable continuous paper state"' in resolver
        assert '"Upload compact continuous learning source"' in resolver
        assert "Queue fallback exact successor continuous paper worker" in resolver
        assert "Queue exact successor from fast resume" in resolver
        assert 'conclusion not in {"success", "failure"}' in resolver


def test_exact_state_consumers_accept_only_authenticated_durable_failures() -> None:
    for path in DURABLE_HANDOFF_STATE_CONSUMERS:
        source = _source(path)
        resolver = source.split(
            "      - name: Resolve exact artifact-bearing paper state",
            1,
        )[1].split("\n      - name:", 1)[0]

        assert "paper_run_is_evidence_eligible()" in resolver
        assert "continuous-paper-state-" in resolver
        assert "latest_evidence_eligible_with_state_artifact" in resolver
        assert '"Run continuous paper trader"' in resolver
        assert '"Measure durable continuous paper state"' in resolver
        assert '"Upload durable continuous paper state"' in resolver
        assert "Queue fallback exact successor continuous paper worker" in resolver
        assert "Queue exact successor from fast resume" in resolver
        assert 'conclusion not in {"success", "failure"}' in resolver
