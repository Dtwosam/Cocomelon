"""Non-authoritative, append-only original paper position census at opportunity capture.

This does NOT prove archival receipt before the exchange decision, or the
historic online state of prospective strike filters. It records the ACTUAL
paper execution adapter's currently open same-market/side opening plans,
excluding openings timestamped at or after the opportunity under review.
Old opportunities without a witness stay missing, never backfilled.
"""
from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Sequence
from pathlib import Path

from cocomelon.domain.journal import TradeJournalEntry
from cocomelon.execution.accounting import PaperPosition
from cocomelon.research.continuous_paper_opening_opportunity import (
    ContinuousPaperOpeningOpportunityEvidence,
)

SCHEMA_VERSION = 1
PHASE = "opening_opportunity_research_sink_after_risk_evaluation"


class OpportunityInventoryWitnessError(RuntimeError):
    pass


def _canonical(raw: object) -> str:
    return json.dumps(
        raw, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False,
    )


def _fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def opportunity_inventory_witness(
    opportunity: ContinuousPaperOpeningOpportunityEvidence,
    positions: Sequence[PaperPosition],
    *,
    recorded_at_ms: int,
) -> dict[str, object]:
    """Capture an in-process census only; no hypothetical/backfilled entries."""
    timestamp = opportunity.opportunity_timestamp_ms
    if (
        type(recorded_at_ms) is not int
        or recorded_at_ms < timestamp
        or timestamp < 0
    ):
        raise OpportunityInventoryWitnessError(
            "inventory observation time precedes opportunity"
        )
    active: set[str] = set()
    for position in positions:
        if (
            position.market.canonical == opportunity.market
            and position.side.value == opportunity.direction
            and position.opened_at_ms < timestamp
        ):
            plan = _fingerprint(position.opening_plan_id)
            if plan in active:
                raise OpportunityInventoryWitnessError(
                    "duplicate simultaneous original paper opening plan"
                )
            active.add(plan)
    payload: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "source_phase": PHASE,
        "opportunity_id": opportunity.opportunity_id,
        "opportunity_timestamp_ms": timestamp,
        "recorded_at_ms": recorded_at_ms,
        "market": opportunity.market,
        "direction": opportunity.direction,
        "prior_opening_plan_sha256": sorted(active),
        "independently_archived_before_opportunity": False,
        "original_filter_state_certified": False,
    }
    payload["payload_sha256"] = _fingerprint(_canonical(payload))
    return payload


def _verify(raw: object) -> dict[str, object]:
    if not isinstance(raw, dict):
        raise OpportunityInventoryWitnessError("witness must be an object")
    payload = dict(raw)
    digest = payload.pop("payload_sha256", None)
    if (
        payload.get("schema_version") != SCHEMA_VERSION
        or payload.get("source_phase") != PHASE
        or payload.get("independently_archived_before_opportunity") is not False
        or payload.get("original_filter_state_certified") is not False
        or not isinstance(digest, str)
        or len(digest) != 64
        or digest != _fingerprint(_canonical(payload))
    ):
        raise OpportunityInventoryWitnessError("witness metadata or digest invalid")
    ident, market, direction = (
        payload.get("opportunity_id"),
        payload.get("market"),
        payload.get("direction"),
    )
    if (
        not isinstance(ident, str) or not ident
        or not isinstance(market, str) or not market
        or direction not in {"long", "short"}
    ):
        raise OpportunityInventoryWitnessError("witness original identity invalid")
    timestamp, observed = (
        payload.get("opportunity_timestamp_ms"),
        payload.get("recorded_at_ms"),
    )
    if (
        type(timestamp) is not int or timestamp < 0
        or type(observed) is not int or observed < timestamp
    ):
        raise OpportunityInventoryWitnessError("witness clock invalid")
    plans = payload.get("prior_opening_plan_sha256")
    if (
        not isinstance(plans, list)
        or any(
            not isinstance(p, str)
            or len(p) != 64
            or any(c not in "0123456789abcdef" for c in p)
            for p in plans
        )
        or plans != sorted(set(plans))
    ):
        raise OpportunityInventoryWitnessError("witness plan identity set invalid")
    return dict(raw)


class OpportunityInventoryWitnessStore:
    def __init__(self, root: str | Path) -> None:
        self.records_root = Path(root) / "records"
        self.records_root.mkdir(parents=True, exist_ok=True)

    def _path(self, opportunity_id: str) -> Path:
        if not opportunity_id:
            raise OpportunityInventoryWitnessError("opportunity ID missing")
        return self.records_root / (_fingerprint(opportunity_id) + ".json")

    def record(
        self,
        opportunity: ContinuousPaperOpeningOpportunityEvidence,
        positions: Sequence[PaperPosition],
        *,
        recorded_at_ms: int,
    ) -> bool:
        value = opportunity_inventory_witness(
            opportunity, positions, recorded_at_ms=recorded_at_ms
        )
        path = self._path(opportunity.opportunity_id)
        encoded = (_canonical(value) + "\n").encode("utf-8")
        if path.exists():
            existing = self._read(path)
            # An actual first record is immutable. Its receipt clock may
            # differ on duplicate observer calls, but original inventory
            # and opportunity identity must not change.
            fields = (
                "opportunity_id", "opportunity_timestamp_ms", "market",
                "direction", "prior_opening_plan_sha256",
            )
            if any(existing[f] != value[f] for f in fields):
                raise OpportunityInventoryWitnessError(
                    "original first-seen opportunity census has changed"
                )
            return False
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        try:
            with temporary.open("xb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(temporary, path)
            except FileExistsError:
                existing = self._read(path)
                if any(
                    existing[f] != value[f]
                    for f in (
                        "opportunity_id", "opportunity_timestamp_ms", "market",
                        "direction", "prior_opening_plan_sha256",
                    )
                ):
                    raise OpportunityInventoryWitnessError(
                        "concurrent first-seen census conflict"
                    ) from None
                return False
        finally:
            temporary.unlink(missing_ok=True)
        return True

    @staticmethod
    def _read(path: Path) -> dict[str, object]:
        try:
            encoded = path.read_bytes()
            raw = json.loads(encoded)
        except (OSError, json.JSONDecodeError) as exc:
            raise OpportunityInventoryWitnessError("census unreadable") from exc
        result = _verify(raw)
        if encoded != (_canonical(result) + "\n").encode("utf-8"):
            raise OpportunityInventoryWitnessError("noncanonical first-seen census")
        return result

    def iter_records(self) -> tuple[dict[str, object], ...]:
        records = []
        for path in sorted(self.records_root.glob("*.json")):
            record = self._read(path)
            if path.name != self._path(str(record["opportunity_id"])).name:
                raise OpportunityInventoryWitnessError("census filename conflict")
            records.append(record)
        return tuple(
            sorted(
                records,
                key=lambda r: (r["opportunity_timestamp_ms"], r["opportunity_id"]),
            )
        )


def original_inventory_overlap_audit(
    opportunities: Sequence[ContinuousPaperOpeningOpportunityEvidence],
    closed_trades: Sequence[TradeJournalEntry],
    censuses: Sequence[dict[str, object]],
    *,
    overlap_started_at_ms: int,
) -> dict[str, object]:
    """Only categorize later-closed overlaps; never restore historic eligibility."""
    if type(overlap_started_at_ms) is not int or overlap_started_at_ms < 0:
        raise OpportunityInventoryWitnessError("overlap start invalid")
    by_id: dict[str, dict[str, object]] = {}
    for raw in censuses:
        record = _verify(raw)
        identity = str(record["opportunity_id"])
        if identity in by_id:
            raise OpportunityInventoryWitnessError("duplicate original census")
        by_id[identity] = record
    eligible = 0
    exposed = 0
    missing = 0
    fully_present = 0
    mismatched = 0
    for evidence in opportunities:
        timestamp = evidence.opportunity_timestamp_ms
        if timestamp < overlap_started_at_ms:
            continue
        eligible += 1
        old = by_id.get(evidence.opportunity_id)
        if old is not None and (
            old["market"] != evidence.market
            or old["direction"] != evidence.direction
            or old["opportunity_timestamp_ms"] != timestamp
        ):
            raise OpportunityInventoryWitnessError(
                "first-seen census contradicts immutable opportunity"
            )
        future = tuple(
            t for t in closed_trades
            if overlap_started_at_ms <= t.opened_at_ms < timestamp
            and t.closed_at_ms > timestamp
            and t.market.canonical == evidence.market
            and t.direction.value == evidence.direction
        )
        if not future:
            continue
        exposed += 1
        if old is None:
            missing += 1
        elif all(
            _fingerprint(t.opening_plan_id) in old["prior_opening_plan_sha256"]
            for t in future
        ):
            fully_present += 1
        else:
            mismatched += 1
    return {
        "kind": "original-in-process-opportunity-open-inventory-v1",
        "research_only": True,
        "execution_authority": False,
        "promotion_authority": False,
        "changes_candidate_readiness": False,
        "historical_ledger_repair_authority": False,
        "independently_archived_before_opportunity": False,
        "decision_time_filter_state_verified": False,
        "research_readiness_grant": False,
        "original_census_count": len(by_id),
        "eligible_opportunity_count": eligible,
        "later_finalized_overlap_opportunities": exposed,
        "overlap_missing_original_census": missing,
        "overlap_original_census_matches": fully_present,
        "overlap_original_census_mismatches": mismatched,
    }
