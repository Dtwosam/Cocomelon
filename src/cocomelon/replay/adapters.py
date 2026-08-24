from __future__ import annotations

from dataclasses import dataclass

from cocomelon.domain.replay import EvidenceClass, ReplayManifest, ReplayRecord, SourceRecordKind

MICROSTRUCTURE_KINDS = frozenset({"l2_book", "trade"})


class EvidenceClassError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ReplayRequirements:
    requires_l2: bool = False
    requires_trades: bool = False


def validate_replay_evidence(
    manifest: ReplayManifest,
    records: tuple[ReplayRecord, ...],
    requirements: ReplayRequirements,
) -> None:
    event_kinds = {
        record.event_kind
        for record in records
        if record.record_kind is SourceRecordKind.NORMALIZED_EVENT
        and record.event_kind is not None
    }
    if manifest.evidence_class is EvidenceClass.CANDLE_CONTEXT:
        forbidden = tuple(sorted(event_kinds & MICROSTRUCTURE_KINDS))
        if forbidden:
            joined = ", ".join(forbidden)
            raise EvidenceClassError(
                f"CANDLE_CONTEXT replay cannot contain microstructure evidence: {joined}"
            )
        if requirements.requires_l2 or requirements.requires_trades:
            raise EvidenceClassError(
                "CANDLE_CONTEXT replay cannot satisfy l2/trade execution requirements"
            )
        return

    if manifest.evidence_class is not EvidenceClass.MICROSTRUCTURE:
        raise EvidenceClassError(f"unsupported evidence class: {manifest.evidence_class}")
    if requirements.requires_l2 and "l2_book" not in event_kinds:
        raise EvidenceClassError("microstructure replay requires recorded l2 evidence")
    if requirements.requires_trades and "trade" not in event_kinds:
        raise EvidenceClassError("microstructure replay requires recorded trade evidence")
