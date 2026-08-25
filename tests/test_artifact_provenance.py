from __future__ import annotations

import importlib
import importlib.util
from types import ModuleType


def _module() -> ModuleType:
    spec = importlib.util.find_spec("cocomelon.ops.artifact_provenance")
    assert spec is not None, "artifact provenance helper must exist"
    return importlib.import_module("cocomelon.ops.artifact_provenance")


def test_ranked_artifact_candidates_are_exact_nonexpired_and_newest_first() -> None:
    provenance = _module()
    payload = {
        "artifacts": [
            {
                "id": 11,
                "name": "v2-mainnet-corpus",
                "expired": False,
                "created_at": "2026-08-25T09:00:00Z",
                "workflow_run": {"id": 101},
            },
            {
                "id": 12,
                "name": "v2-mainnet-corpus",
                "expired": False,
                "created_at": "2026-08-25T10:00:00Z",
                "workflow_run": {"id": 102},
            },
            {
                "id": 13,
                "name": "v2-mainnet-corpus",
                "expired": True,
                "created_at": "2026-08-25T11:00:00Z",
                "workflow_run": {"id": 103},
            },
            {
                "id": 14,
                "name": "v2-mainnet-corpus-copy",
                "expired": False,
                "created_at": "2026-08-25T12:00:00Z",
                "workflow_run": {"id": 104},
            },
            {
                "id": 15,
                "name": "v2-mainnet-corpus",
                "expired": False,
                "created_at": "2026-08-25T13:00:00Z",
                "workflow_run": None,
            },
        ]
    }

    candidates = provenance.ranked_artifact_candidates(payload, "v2-mainnet-corpus")

    assert [(item.artifact_id, item.workflow_run_id) for item in candidates] == [
        (12, 102),
        (11, 101),
    ]


def test_trusted_curator_run_requires_exact_workflow_event_and_repository() -> None:
    provenance = _module()
    trusted = {
        "id": 102,
        "path": ".github/workflows/evidence-corpus-curator.yml",
        "event": "workflow_run",
        "repository": {"full_name": "Dtwosam/Cocomelon"},
        "head_repository": {"full_name": "Dtwosam/Cocomelon"},
    }

    assert provenance.trusted_curator_run(trusted, repository="Dtwosam/Cocomelon") is True

    for field, value in (
        ("path", ".github/workflows/other.yml"),
        ("event", "workflow_dispatch"),
    ):
        mutated = {**trusted, field: value}
        assert provenance.trusted_curator_run(
            mutated,
            repository="Dtwosam/Cocomelon",
        ) is False

    wrong_repo = {**trusted, "repository": {"full_name": "attacker/Cocomelon"}}
    assert provenance.trusted_curator_run(
        wrong_repo,
        repository="Dtwosam/Cocomelon",
    ) is False

    wrong_head_repo = {
        **trusted,
        "head_repository": {"full_name": "attacker/Cocomelon"},
    }
    assert provenance.trusted_curator_run(
        wrong_head_repo,
        repository="Dtwosam/Cocomelon",
    ) is False


def test_trusted_curator_run_requires_matching_expected_run_id_when_supplied() -> None:
    provenance = _module()
    run = {
        "id": 102,
        "path": ".github/workflows/evidence-corpus-curator.yml",
        "event": "workflow_run",
        "repository": {"full_name": "Dtwosam/Cocomelon"},
        "head_repository": {"full_name": "Dtwosam/Cocomelon"},
    }

    assert provenance.trusted_curator_run(
        run,
        repository="Dtwosam/Cocomelon",
        expected_run_id=102,
    ) is True
    assert provenance.trusted_curator_run(
        run,
        repository="Dtwosam/Cocomelon",
        expected_run_id=999,
    ) is False
