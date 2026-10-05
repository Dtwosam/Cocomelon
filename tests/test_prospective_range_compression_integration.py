from pathlib import Path


def test_continuous_paper_persists_range_compression_shadow() -> None:
    source = Path("src/cocomelon/continuous_paper.py").read_text(
        encoding="utf-8"
    )

    assert (
        "PROSPECTIVE_RANGE_COMPRESSION_ENTRY_STATE_FILENAME"
        in source
    )
    assert "prospective-range-compression-entry-state.json" in source
    assert (
        "PROSPECTIVE_RANGE_COMPRESSION_ENTRY_SUMMARY_FILENAME"
        in source
    )
    assert "prospective-range-compression-entry-summary.json" in source
    assert "_restore_prospective_range_compression_entry(" in source
    assert (
        "prospective_range_compression_entry_state.payload"
        in source
    )
    assert "evaluate_prospective_range_compression_entry(" in source


def test_continuous_paper_handoff_carries_range_compression_shadow() -> None:
    source = Path(".github/workflows/continuous-paper.yml").read_text(
        encoding="utf-8"
    )

    assert (
        'src/cocomelon/research/prospective_range_compression_entry.py'
        in source
    )
    assert (
        "continuous-paper-state/"
        "prospective-range-compression-entry-state.json"
        in source
    )
    assert (
        "continuous-paper-state/"
        "prospective-range-compression-entry-summary.json"
        in source
    )
