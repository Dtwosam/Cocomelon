from __future__ import annotations

from dataclasses import dataclass
from typing import Final

PAPER_SOURCE_QUARANTINE_SCHEMA_VERSION: Final = 1


@dataclass(frozen=True, slots=True)
class PaperSourceQuarantineEntry:
    run_id: int
    reason: str
    incident_id: str

    def __post_init__(self) -> None:
        if self.run_id <= 0:
            raise ValueError("run_id must be positive")
        if not self.reason.strip():
            raise ValueError("reason must not be empty")
        if not self.incident_id.strip():
            raise ValueError("incident_id must not be empty")


_INCIDENT = "duplicate-paper-trader-overlap-2026-10-07"

PAPER_SOURCE_QUARANTINE: Final = (
    PaperSourceQuarantineEntry(
        run_id=376_058_302_45,
        reason=(
            "paper trader overlapped another active trader from "
            "2026-10-07T10:27:27Z through 2026-10-07T10:55:13Z"
        ),
        incident_id=_INCIDENT,
    ),
    PaperSourceQuarantineEntry(
        run_id=376_073_726_43,
        reason=(
            "paper trader overlapped another active trader from "
            "2026-10-07T10:27:27Z through 2026-10-07T10:55:13Z"
        ),
        incident_id=_INCIDENT,
    ),
    PaperSourceQuarantineEntry(
        run_id=376_106_484_95,
        reason=(
            "paper trader overlapped another active trader from "
            "2026-10-07T10:57:28Z through 2026-10-07T10:58:52Z"
        ),
        incident_id=_INCIDENT,
    ),
    PaperSourceQuarantineEntry(
        run_id=376_107_182_54,
        reason=(
            "paper trader overlapped another active trader from "
            "2026-10-07T10:57:28Z through 2026-10-07T10:58:52Z"
        ),
        incident_id=_INCIDENT,
    ),
)

_BY_RUN_ID: Final = {item.run_id: item for item in PAPER_SOURCE_QUARANTINE}


def paper_source_quarantine_entry(
    run_id: int,
) -> PaperSourceQuarantineEntry | None:
    if isinstance(run_id, bool) or not isinstance(run_id, int) or run_id <= 0:
        raise ValueError("run_id must be a positive integer")
    return _BY_RUN_ID.get(run_id)


def is_paper_source_quarantined(run_id: int) -> bool:
    return paper_source_quarantine_entry(run_id) is not None


def assert_paper_source_not_quarantined(run_id: int) -> None:
    entry = paper_source_quarantine_entry(run_id)
    if entry is None:
        return
    raise RuntimeError(
        "PAPER_SOURCE_QUARANTINED: "
        f"run_id={entry.run_id} incident={entry.incident_id} "
        f"reason={entry.reason}"
    )
