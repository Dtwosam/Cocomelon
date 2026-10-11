from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from cocomelon.research.prospective_short_rank_first_seen import (
    FirstSeenRankSnapshot,
    FirstSeenRankSnapshotStore,
)
from scripts.seal_paper_short_rank_archive import (
    ARCHIVE_NAME,
    RECEIPT_NAME,
    ShortRankSealError,
    seal_completed_short_rank_archive,
)

OBSERVED_MS = 1_790_000_000_000
HEAD_SHA = "a" * 40


def _source(root: Path) -> FirstSeenRankSnapshotStore:
    root.mkdir(parents=True, exist_ok=True)
    store = FirstSeenRankSnapshotStore(
        root / "prospective-short-rank-first-seen"
    )
    assert store.append(
        FirstSeenRankSnapshot(
            observed_at_ms=OBSERVED_MS,
            captured_at_ms=OBSERVED_MS + 30,
            features=(("BTC", "fixture-feature-btc", OBSERVED_MS - 100),),
            ranks=(("BTC", 1, "0.7", ("fixture",)),),
        )
    )
    return store


def _seal(root: Path, out: Path) -> dict[str, object]:
    return seal_completed_short_rank_archive(
        root, out,
        worker_run_id=38152483456,
        worker_run_attempt=1,
        worker_head_sha=HEAD_SHA,
        sealed_at_ms=OBSERVED_MS + 60,
    )


def test_completed_worker_seals_full_identical_rank_bytes_and_claimed_identity(
    tmp_path: Path,
) -> None:
    root, out = tmp_path / "original", tmp_path / "separate-output"
    store = _source(root)
    files_before = {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in root.rglob("*.json")
    }
    receipt = _seal(root, out)
    assert receipt["rank_source_status"] == "locally_sealed"
    assert receipt["rank_state_digest"] == store.state_digest
    assert receipt["archive_snapshot_count"] == 1
    assert receipt["github_artifact_provenance_independently_authenticated"] is False
    assert receipt["original_market_archive_bound"] is False
    assert receipt["ready_for_review"] is False
    assert receipt["execution_authority"] is False
    assert receipt["worker_run_id_claimed"] == 38152483456
    assert receipt["worker_head_sha_claimed"] == HEAD_SHA
    assert (out / RECEIPT_NAME).exists()
    data = (out / ARCHIVE_NAME).read_bytes()
    assert hashlib.sha256(data).hexdigest() == receipt["archive_file_sha256"]
    with zipfile.ZipFile(out / ARCHIVE_NAME) as archive:
        assert len(archive.namelist()) == 2
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["rank_state_digest"] == store.state_digest
        assert manifest["rank_snapshot_count"] == 1
        row = manifest["files"][0]
        original = files_before[
            "prospective-short-rank-first-seen/" + row["path"]
        ]
        assert archive.read(row["path"]) == original
        assert hashlib.sha256(original).hexdigest() == row["sha256"]
    files_after = {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in root.rglob("*.json")
    }
    assert files_before == files_after


@pytest.mark.parametrize("cause", ["missing", "capture_failure", "tampered"])
def test_missing_corrupt_or_failed_first_seen_source_cannot_publish_sealed_archive(
    tmp_path: Path,
    cause: str,
) -> None:
    root, out = tmp_path / "state", tmp_path / "out"
    if cause != "missing":
        _source(root)
    else:
        root.mkdir()
    if cause == "capture_failure":
        (root / "prospective-short-rank-first-seen-error.json").write_text(
            '{"error":"permanent research source failure"}\n',
            encoding="utf-8",
        )
    if cause == "tampered":
        p = next(root.glob("prospective-short-rank-first-seen/snapshots/*.json"))
        raw = json.loads(p.read_text())
        raw["ranks"][0]["ordinal"] = 9
        p.write_text(json.dumps(raw) + "\n", encoding="utf-8")
    receipt = _seal(root, out)
    assert receipt["rank_source_status"] == "rejected"
    assert receipt["rejection_reason"]
    assert receipt["rank_state_digest"] is None
    assert receipt["archive_snapshot_count"] == 0
    assert (out / RECEIPT_NAME).exists()
    assert not (out / ARCHIVE_NAME).exists()


def test_partial_or_hidden_file_must_not_be_omitted(tmp_path: Path) -> None:
    root, out = tmp_path / "state", tmp_path / "out"
    _source(root)
    (root / "prospective-short-rank-first-seen" / "snapshots" / ".pending.tmp").write_bytes(
        b"stale"
    )
    receipt = _seal(root, out)
    assert receipt["rank_source_status"] == "rejected"
    assert not (out / ARCHIVE_NAME).exists()


def test_out_of_sequence_or_future_rank_snapshot_has_no_artifact(
    tmp_path: Path,
) -> None:
    root, out = tmp_path / "state", tmp_path / "out"
    store = _source(root)
    store.append(
        FirstSeenRankSnapshot(
            observed_at_ms=OBSERVED_MS + 50,
            captured_at_ms=OBSERVED_MS + 100,
            features=(("ETH", "second-feature", OBSERVED_MS + 40),),
            ranks=(),
        )
    )
    receipt = _seal(root, out)
    assert receipt["rank_source_status"] == "rejected"
    assert not (out / ARCHIVE_NAME).exists()


def test_symlink_rank_snapshot_cannot_be_sealed(
    tmp_path: Path,
) -> None:
    root, out = tmp_path / "state", tmp_path / "out"
    _source(root)
    p = next(root.glob("prospective-short-rank-first-seen/snapshots/*.json"))
    external = tmp_path / "elsewhere.json"
    external.write_bytes(p.read_bytes())
    p.unlink()
    p.symlink_to(external)
    receipt = _seal(root, out)
    assert receipt["rank_source_status"] == "rejected"
    assert not (out / ARCHIVE_NAME).exists()


def test_refuse_to_write_into_original_state_or_reuse_seal_output(
    tmp_path: Path,
) -> None:
    root = tmp_path / "state"
    _source(root)
    with pytest.raises(ShortRankSealError, match="overlaps"):
        _seal(root, root / "research-outputs")
    with pytest.raises(ShortRankSealError, match="overlaps"):
        _seal(root, tmp_path)
    out = tmp_path / "out"
    assert _seal(root, out)["rank_source_status"] == "locally_sealed"
    with pytest.raises(ShortRankSealError, match="new and empty"):
        _seal(root, out)


def test_rank_seal_requires_worker_identity_and_never_self_claims_authentication(
    tmp_path: Path,
) -> None:
    root, out = tmp_path / "state", tmp_path / "out"
    _source(root)
    with pytest.raises(ShortRankSealError, match="identity"):
        seal_completed_short_rank_archive(
            root, out,
            worker_run_id=0, worker_run_attempt=1,
            worker_head_sha=HEAD_SHA, sealed_at_ms=OBSERVED_MS + 60,
        )
    assert not out.exists()


def test_workflow_seals_rank_only_after_worker_exit_with_nonblocking_upload() -> None:
    source = Path(".github/workflows/continuous-paper.yml").read_text(
        encoding="utf-8"
    )
    end = source.index("- name: Remove local fast resume archive")
    seal = source.index(
        "- name: Seal original first-seen SHORT rank source after worker exit"
    )
    publish = source.index(
        "- name: Upload original first-seen SHORT rank seal and failure receipt"
    )
    facts = source.index("- name: Export compact continuous decision facts")
    assert end < seal < publish < facts
    assert "continue-on-error: true" in source[seal:publish]
    assert "if-no-files-found: error" in source[publish:facts]
    assert "scripts/seal_paper_short_rank_archive.py" in source
    assert (
        "continuous-paper-first-seen-short-rank-${{ github.run_id }}-"
        "${{ github.run_attempt }}"
    ) in source



def test_original_worker_seals_actual_restored_predecessor_run_and_attempt(
    tmp_path: Path,
) -> None:
    root, out = tmp_path / "state", tmp_path / "sealed"
    _source(root)
    receipt = seal_completed_short_rank_archive(
        root, out,
        worker_run_id=38162541394,
        worker_run_attempt=1,
        worker_head_sha=HEAD_SHA,
        restored_from_run_id=38152483456,
        restored_from_run_attempt=1,
        sealed_at_ms=OBSERVED_MS + 60,
    )
    assert receipt["rank_source_status"] == "locally_sealed"
    assert receipt["restored_from_run_id_claimed"] == 38152483456
    assert receipt["restored_from_run_attempt_claimed"] == 1
    with zipfile.ZipFile(out / ARCHIVE_NAME) as bundle:
        manifest = json.loads(bundle.read("manifest.json"))
    assert manifest["restored_from_run_id_claimed"] == 38152483456
    assert manifest["restored_from_run_attempt_claimed"] == 1


def test_no_partial_or_self_claimed_predecessor_source_can_be_sealed(
    tmp_path: Path,
) -> None:
    root, out = tmp_path / "state", tmp_path / "sealed"
    _source(root)
    for source_id, attempt in (
        (38152483456, None),
        (None, 1),
        (0, 1),
        (38162541394, 1),
        (38152483456, 0),
    ):
        with pytest.raises(ShortRankSealError, match="predecessor"):
            seal_completed_short_rank_archive(
                root, out,
                worker_run_id=38162541394,
                worker_run_attempt=1,
                worker_head_sha=HEAD_SHA,
                restored_from_run_id=source_id,
                restored_from_run_attempt=attempt,
                sealed_at_ms=OBSERVED_MS + 60,
            )
    assert not out.exists()


def test_real_workflow_dispatch_sources_are_written_into_rank_seal() -> None:
    workflow = Path(".github/workflows/continuous-paper.yml").read_text(
        encoding="utf-8"
    )
    step_start = workflow.index(
        "- name: Seal original first-seen SHORT rank source after worker exit"
    )
    step_end = workflow.index(
        "- name: Upload original first-seen SHORT rank seal and failure receipt"
    )
    source = workflow[step_start:step_end]
    assert '--restored-from-run-id "${{ inputs.source_run_id || \'\' }}"' in source
    assert '--restored-from-run-attempt "${{ inputs.source_run_attempt || \'\' }}"' in source
    assert "--worker-run-attempt" in source
    assert "continue-on-error: true" in source


def test_separate_original_rank_seal_commands_never_consume_other_script_as_argument(
) -> None:
    """The real rank seal would fail after worker exit if the watcher
    dependency's script path becomes a stray Python CLI positional argument.
    """
    workflow = Path(".github/workflows/continuous-paper.yml").read_text(
        encoding="utf-8"
    )
    rank_start = workflow.index(
        "- name: Seal original first-seen SHORT rank source after worker exit"
    )
    rank_end = workflow.index(
        "- name: Upload original first-seen SHORT rank seal and failure receipt"
    )
    full_start = workflow.index(
        "- name: Seal entire original SHORT rank input features after paper exit"
    )
    full_end = workflow.index(
        "- name: Upload original SHORT rank full-input seal or rejection"
    )
    rank_step = workflow[rank_start:rank_end]
    full_step = workflow[full_start:full_end]

    assert "python scripts/seal_paper_short_rank_archive.py \\n" in rank_step
    assert "scripts/seal_paper_short_rank_full_features.py" not in rank_step
    assert "--restored-from-run-id" in rank_step
    assert "--restored-from-run-attempt" in rank_step
    assert "python scripts/seal_paper_short_rank_full_features.py \\n" in full_step
    assert "scripts/seal_paper_short_rank_archive.py" not in full_step

    # One trigger path, one independent upgrade watcher dependency, and
    # exactly one executable step for each of the two distinct exporters.
    assert workflow.count("scripts/seal_paper_short_rank_archive.py") == 3
    assert workflow.count("scripts/seal_paper_short_rank_full_features.py") == 3
    assert workflow.index("scripts/seal_paper_short_rank_full_features.py") < rank_start
