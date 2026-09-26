from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import cast

LEARNING_SHADOW_SEQUENCE_SCHEMA_VERSION = 1


class LearningShadowCampaignSequenceError(RuntimeError):
    pass


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _sha256_json(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _mapping(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise LearningShadowCampaignSequenceError(f"{field} must be a JSON object")
    return cast(dict[str, object], value)


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise LearningShadowCampaignSequenceError(
            f"{field} must be a non-negative integer"
        )
    return value


def _positive_integer(value: object, field: str) -> int:
    resolved = _integer(value, field)
    if resolved <= 0:
        raise LearningShadowCampaignSequenceError(f"{field} must be positive")
    return resolved


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LearningShadowCampaignSequenceError(
            f"{field} must be a non-empty string"
        )
    return value


def _boolean(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise LearningShadowCampaignSequenceError(f"{field} must be boolean")
    return value


def _timestamp_ms(value: object, field: str) -> int:
    raw = _string(value, field)
    try:
        resolved = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise LearningShadowCampaignSequenceError(
            f"{field} must be an ISO timestamp"
        ) from exc
    if resolved.tzinfo is None:
        raise LearningShadowCampaignSequenceError(
            f"{field} must be timezone-aware"
        )
    return int(resolved.timestamp() * 1000)


def _authority(payload: dict[str, object], field: str) -> None:
    if _boolean(payload.get("paper_only"), f"{field}.paper_only") is not True:
        raise LearningShadowCampaignSequenceError(f"{field} must remain paper-only")
    if _boolean(payload.get("research_only"), f"{field}.research_only") is not True:
        raise LearningShadowCampaignSequenceError(f"{field} must remain research-only")
    if _boolean(
        payload.get("promotion_eligible"),
        f"{field}.promotion_eligible",
    ) is not False:
        raise LearningShadowCampaignSequenceError(
            f"{field} cannot authorize promotion"
        )
    if _boolean(payload.get("execution_ready"), f"{field}.execution_ready") is not False:
        raise LearningShadowCampaignSequenceError(
            f"{field} cannot authorize execution"
        )
    if _boolean(
        payload.get("live_promotion_authorized"),
        f"{field}.live_promotion_authorized",
    ) is not False:
        raise LearningShadowCampaignSequenceError(
            f"{field} cannot authorize live capital"
        )


def _verify_identity_receipt(
    path: Path,
    *,
    id_field: str,
    field: str,
) -> dict[str, object]:
    try:
        encoded = path.read_bytes()
        raw = _mapping(json.loads(encoded), field)
    except (OSError, json.JSONDecodeError) as exc:
        raise LearningShadowCampaignSequenceError(f"{field} is invalid") from exc
    identity = _string(raw.get(id_field), f"{field}.{id_field}")
    if len(identity) != 64 or any(char not in "0123456789abcdef" for char in identity):
        raise LearningShadowCampaignSequenceError(f"{field}.{id_field} is invalid")
    payload = dict(raw)
    payload.pop(id_field)
    if _sha256_json(payload) != identity:
        raise LearningShadowCampaignSequenceError(f"{field} identity mismatch")
    canonical = (_canonical_json(raw) + "\n").encode("utf-8")
    if encoded != canonical:
        raise LearningShadowCampaignSequenceError(f"{field} is non-canonical")
    return raw


@dataclass(frozen=True, slots=True)
class ShadowCampaignRef:
    run_id: int
    run_attempt: int
    created_at_ms: int
    completed_at_ms: int
    head_sha: str

    def __post_init__(self) -> None:
        if self.run_id <= 0 or self.run_attempt <= 0:
            raise ValueError("campaign run identity must be positive")
        if self.created_at_ms < 0 or self.completed_at_ms < self.created_at_ms:
            raise ValueError("campaign timestamps are invalid")
        if (
            len(self.head_sha) != 40
            or any(char not in "0123456789abcdef" for char in self.head_sha)
        ):
            raise ValueError("campaign head_sha must be a lowercase git SHA")

    def to_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "run_attempt": self.run_attempt,
            "created_at_ms": self.created_at_ms,
            "completed_at_ms": self.completed_at_ms,
            "head_sha": self.head_sha,
        }


@dataclass(frozen=True, slots=True)
class LearningShadowCampaignSequenceStatus:
    action: str
    bootstrap_as_of_ms: int
    processed_campaign_count: int
    remaining_campaign_count: int
    current_run_id: int | None
    current_run_attempt: int | None
    next_required_run_id: int | None
    next_required_run_attempt: int | None
    next_required_created_at_ms: int | None
    next_required_completed_at_ms: int | None
    paper_only: bool = True
    research_only: bool = True
    promotion_eligible: bool = False
    execution_ready: bool = False
    live_promotion_authorized: bool = False
    schema_version: int = LEARNING_SHADOW_SEQUENCE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.action not in {
            "process",
            "skip_already_processed",
            "skip_completed_before_bootstrap",
            "gap",
            "caught_up",
            "missing_campaign",
        }:
            raise ValueError("unsupported shadow campaign sequence action")
        if self.bootstrap_as_of_ms < 0:
            raise ValueError("bootstrap_as_of_ms must be non-negative")
        if self.processed_campaign_count < 0 or self.remaining_campaign_count < 0:
            raise ValueError("campaign sequence counts must be non-negative")
        if (self.current_run_id is None) != (self.current_run_attempt is None):
            raise ValueError("current campaign identity must be complete or absent")
        if self.current_run_id is not None and (
            self.current_run_id <= 0 or cast(int, self.current_run_attempt) <= 0
        ):
            raise ValueError("current campaign identity must be positive")
        next_values = (
            self.next_required_run_id,
            self.next_required_run_attempt,
            self.next_required_created_at_ms,
            self.next_required_completed_at_ms,
        )
        if any(value is None for value in next_values) != all(
            value is None for value in next_values
        ):
            raise ValueError("next required campaign identity must be complete or absent")
        if self.next_required_run_id is not None and (
            self.next_required_run_id <= 0
            or cast(int, self.next_required_run_attempt) <= 0
            or cast(int, self.next_required_created_at_ms) < 0
            or cast(int, self.next_required_completed_at_ms)
            < cast(int, self.next_required_created_at_ms)
        ):
            raise ValueError("next required campaign identity is invalid")
        if self.action in {"process", "gap", "missing_campaign"}:
            if self.next_required_run_id is None:
                raise ValueError("action requires a next campaign")
        if self.action in {
            "skip_already_processed",
            "skip_completed_before_bootstrap",
        } and self.current_run_id is None:
            raise ValueError("skip action requires current campaign")
        if self.action == "caught_up" and self.remaining_campaign_count != 0:
            raise ValueError("caught_up requires zero remaining campaigns")
        if (
            not self.paper_only
            or not self.research_only
            or self.promotion_eligible
            or self.execution_ready
            or self.live_promotion_authorized
        ):
            raise ValueError("shadow sequence cannot carry live authority")
        if self.schema_version != LEARNING_SHADOW_SEQUENCE_SCHEMA_VERSION:
            raise ValueError("unsupported learning shadow sequence schema")

    def to_dict(self) -> dict[str, object]:
        return {
            "action": self.action,
            "bootstrap_as_of_ms": self.bootstrap_as_of_ms,
            "processed_campaign_count": self.processed_campaign_count,
            "remaining_campaign_count": self.remaining_campaign_count,
            "current_run_id": self.current_run_id,
            "current_run_attempt": self.current_run_attempt,
            "next_required_run_id": self.next_required_run_id,
            "next_required_run_attempt": self.next_required_run_attempt,
            "next_required_created_at_ms": self.next_required_created_at_ms,
            "next_required_completed_at_ms": self.next_required_completed_at_ms,
            "paper_only": self.paper_only,
            "research_only": self.research_only,
            "promotion_eligible": self.promotion_eligible,
            "execution_ready": self.execution_ready,
            "live_promotion_authorized": self.live_promotion_authorized,
            "schema_version": self.schema_version,
        }


def load_successful_shadow_campaign_history(
    path: Path,
    *,
    repository: str,
) -> tuple[ShadowCampaignRef, ...]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LearningShadowCampaignSequenceError(
            "LEARNING_SHADOW_CAMPAIGN_HISTORY_INVALID"
        ) from exc
    pages: list[object]
    if isinstance(raw, dict):
        pages = [raw]
    elif isinstance(raw, list):
        pages = raw
    else:
        raise LearningShadowCampaignSequenceError(
            "LEARNING_SHADOW_CAMPAIGN_HISTORY_INVALID"
        )

    refs: dict[int, ShadowCampaignRef] = {}
    for page_index, page_raw in enumerate(pages):
        page = _mapping(page_raw, f"campaign_history[{page_index}]")
        workflow_runs = page.get("workflow_runs")
        if not isinstance(workflow_runs, list):
            raise LearningShadowCampaignSequenceError(
                "LEARNING_SHADOW_CAMPAIGN_HISTORY_RUNS_INVALID"
            )
        for run_raw in workflow_runs:
            run = _mapping(run_raw, "campaign_run")
            if (
                run.get("status") != "completed"
                or run.get("conclusion") != "success"
                or run.get("head_branch") != "main"
                or run.get("event") != "workflow_dispatch"
                or run.get("path")
                != ".github/workflows/research-campaign-scheduled.yml"
                or run.get("name") != "Scheduled Research Mainnet Replay Campaign"
            ):
                continue
            head_repository = run.get("head_repository")
            if not isinstance(head_repository, dict):
                continue
            if head_repository.get("full_name") != repository:
                continue

            run_id = _positive_integer(run.get("id"), "campaign_run.id")
            ref = ShadowCampaignRef(
                run_id=run_id,
                run_attempt=_positive_integer(
                    run.get("run_attempt"),
                    "campaign_run.run_attempt",
                ),
                created_at_ms=_timestamp_ms(
                    run.get("created_at"),
                    "campaign_run.created_at",
                ),
                completed_at_ms=_timestamp_ms(
                    run.get("updated_at"),
                    "campaign_run.updated_at",
                ),
                head_sha=_string(run.get("head_sha"), "campaign_run.head_sha"),
            )
            existing = refs.get(run_id)
            if existing is not None and existing != ref:
                raise LearningShadowCampaignSequenceError(
                    "LEARNING_SHADOW_CAMPAIGN_HISTORY_DUPLICATE_RUN"
                )
            refs[run_id] = ref
    return tuple(
        sorted(
            refs.values(),
            key=lambda item: (item.created_at_ms, item.run_id),
        )
    )


def _state_sequence(state_root: Path) -> tuple[int, frozenset[int]]:
    bootstrap = _verify_identity_receipt(
        state_root / "bootstrap.json",
        id_field="bootstrap_id",
        field="shadow_bootstrap",
    )
    _authority(bootstrap, "shadow_bootstrap")
    bootstrap_as_of_ms = _integer(
        bootstrap.get("as_of_ms"),
        "shadow_bootstrap.as_of_ms",
    )

    processed: set[int] = set()
    generations_root = state_root / "generations"
    if generations_root.exists():
        if not generations_root.is_dir():
            raise LearningShadowCampaignSequenceError(
                "LEARNING_SHADOW_GENERATIONS_ROOT_INVALID"
            )
        for path in sorted(generations_root.glob("*.json")):
            generation = _verify_identity_receipt(
                path,
                id_field="generation_id",
                field="shadow_generation",
            )
            _authority(generation, "shadow_generation")
            run_id = _positive_integer(
                generation.get("campaign_run_id"),
                "shadow_generation.campaign_run_id",
            )
            run_attempt = _positive_integer(
                generation.get("campaign_run_attempt"),
                "shadow_generation.campaign_run_attempt",
            )
            if path.name != f"{run_id}-{run_attempt}.json":
                raise LearningShadowCampaignSequenceError(
                    "LEARNING_SHADOW_GENERATION_FILENAME_MISMATCH"
                )
            if run_id in processed:
                raise LearningShadowCampaignSequenceError(
                    "LEARNING_SHADOW_GENERATION_DUPLICATE_CAMPAIGN"
                )
            processed.add(run_id)
    return bootstrap_as_of_ms, frozenset(processed)


def build_learning_shadow_campaign_sequence_status(
    *,
    state_root: Path,
    campaign_history_path: Path,
    repository: str,
    current_run_id: int | None = None,
) -> LearningShadowCampaignSequenceStatus:
    if not repository.strip():
        raise ValueError("repository must not be empty")
    if current_run_id is not None and current_run_id <= 0:
        raise ValueError("current_run_id must be positive")

    bootstrap_as_of_ms, processed = _state_sequence(state_root)
    campaigns = load_successful_shadow_campaign_history(
        campaign_history_path,
        repository=repository,
    )
    by_id = {item.run_id: item for item in campaigns}
    required = tuple(
        item
        for item in campaigns
        if item.completed_at_ms > bootstrap_as_of_ms and item.run_id not in processed
    )
    next_required = None if not required else required[0]

    def status(action: str, current: ShadowCampaignRef | None) -> LearningShadowCampaignSequenceStatus:
        return LearningShadowCampaignSequenceStatus(
            action=action,
            bootstrap_as_of_ms=bootstrap_as_of_ms,
            processed_campaign_count=len(processed),
            remaining_campaign_count=len(required),
            current_run_id=None if current is None else current.run_id,
            current_run_attempt=None if current is None else current.run_attempt,
            next_required_run_id=None if next_required is None else next_required.run_id,
            next_required_run_attempt=(
                None if next_required is None else next_required.run_attempt
            ),
            next_required_created_at_ms=(
                None if next_required is None else next_required.created_at_ms
            ),
            next_required_completed_at_ms=(
                None if next_required is None else next_required.completed_at_ms
            ),
        )

    if current_run_id is None:
        return status(
            "caught_up" if next_required is None else "missing_campaign",
            None,
        )

    current = by_id.get(current_run_id)
    if current is None:
        raise LearningShadowCampaignSequenceError(
            "LEARNING_SHADOW_CURRENT_CAMPAIGN_NOT_IN_HISTORY"
        )
    if current.completed_at_ms <= bootstrap_as_of_ms:
        action = "skip_completed_before_bootstrap"
    elif current.run_id in processed:
        action = "skip_already_processed"
    elif next_required is None:
        raise LearningShadowCampaignSequenceError(
            "LEARNING_SHADOW_REQUIRED_CAMPAIGN_STATE_INCONSISTENT"
        )
    elif current.run_id != next_required.run_id:
        action = "gap"
    else:
        action = "process"
    return status(action, current)
