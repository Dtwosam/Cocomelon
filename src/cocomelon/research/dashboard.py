from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import Counter

from cocomelon.research.checkpoint_history import load_authenticated_checkpoint_commits
from cocomelon.research.contracts import ResearchCandidateState, TimeInterval
from cocomelon.research.registry import ResearchRegistry, ResearchRegistryError
from cocomelon.research.report_auth import (
    assert_checkpoint_report_backed_by_observations,
    assert_historical_checkpoint_report_backed_by_observations,
)

RESEARCH_STATUS_LABEL = "TOUCHED / NON-PROMOTIONAL"


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _candidate_ids(registry: ResearchRegistry) -> tuple[str, ...]:
    rows = registry.connection.execute(
        "SELECT candidate_id FROM research_candidates ORDER BY candidate_id"
    ).fetchall()
    return tuple(str(row["candidate_id"]) for row in rows)


def _performance_reports(
    registry: ResearchRegistry,
    *,
    candidate_id: str,
) -> dict[str, dict[str, object]]:
    rows = registry.connection.execute(
        """
        SELECT report_id, payload_json
        FROM research_performance_reports
        WHERE candidate_id = ?
        ORDER BY report_id
        """,
        (candidate_id,),
    ).fetchall()
    reports: dict[str, dict[str, object]] = {}
    for row in rows:
        report_id = str(row["report_id"])
        try:
            payload = json.loads(str(row["payload_json"]))
        except json.JSONDecodeError as exc:
            raise ResearchRegistryError("stored research performance report is invalid") from exc
        if not isinstance(payload, dict) or not all(isinstance(key, str) for key in payload):
            raise ResearchRegistryError("stored research performance report is invalid")
        reports[report_id] = payload
    return reports


def _verified_report_id(report_id: str, payload: dict[str, object]) -> None:
    unsigned = dict(payload)
    embedded = unsigned.pop("report_id", None)
    authenticated = hashlib.sha256(_canonical_json(unsigned).encode("utf-8")).hexdigest()
    if authenticated != report_id or embedded != report_id:
        raise ResearchRegistryError("research dashboard report id does not authenticate payload")


def _string_list(payload: dict[str, object], field: str) -> list[str]:
    value = payload.get(field)
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        raise ResearchRegistryError(f"research dashboard checkpoint {field} is invalid")
    return list(value)


def _report_state(payload: dict[str, object]) -> ResearchCandidateState:
    value = payload.get("candidate_state")
    if not isinstance(value, str):
        raise ResearchRegistryError("research dashboard checkpoint state is invalid")
    try:
        return ResearchCandidateState(value)
    except ValueError as exc:
        raise ResearchRegistryError("research dashboard checkpoint state is invalid") from exc


def _source_end_ms(
    registry: ResearchRegistry,
    *,
    candidate_id: str,
    batch_ids: list[str],
    allow_contaminated: bool = False,
) -> int:
    if not batch_ids:
        raise ResearchRegistryError("research dashboard checkpoint lacks batch provenance")
    ends: list[int] = []
    for batch_id in batch_ids:
        row = registry.connection.execute(
            """
            SELECT candidate_id, end_ms, status, contamination_v4_run_id
            FROM research_batches
            WHERE batch_id = ?
            """,
            (batch_id,),
        ).fetchone()
        if row is None or str(row["candidate_id"]) != candidate_id:
            raise ResearchRegistryError("research dashboard checkpoint batch provenance is invalid")
        status = str(row["status"])
        contamination_id = row["contamination_v4_run_id"]
        valid_status = status == "admitted" or (
            allow_contaminated
            and status == "rejected_contamination"
            and contamination_id is not None
            and str(contamination_id).strip() != ""
        )
        if not valid_status:
            raise ResearchRegistryError(
                "research dashboard cannot expose economics from contaminated research batches"
            )
        ends.append(int(row["end_ms"]))
    return max(ends)


def _interval_payload(intervals: tuple[TimeInterval, ...]) -> list[dict[str, int]]:
    return [
        {"start_ms": interval.start_ms, "end_ms": interval.end_ms}
        for interval in intervals
    ]


def _contamination_authentication_connection(
    registry: ResearchRegistry,
    *,
    candidate_id: str,
) -> sqlite3.Connection:
    shadow = sqlite3.connect(":memory:")
    shadow.row_factory = sqlite3.Row
    try:
        registry.connection.backup(shadow)
        shadow.execute(
            """
            UPDATE research_batches
            SET status = 'admitted'
            WHERE candidate_id = ?
              AND status = 'rejected_contamination'
              AND contamination_v4_run_id IS NOT NULL
              AND contamination_v4_run_id != ''
            """,
            (candidate_id,),
        )
        shadow.commit()
    except Exception:
        shadow.close()
        raise
    return shadow


def _authenticate_history_report(
    registry: ResearchRegistry,
    *,
    candidate_id: str,
    report_id: str,
    payload: dict[str, object],
    state: ResearchCandidateState,
    authentication_connection: sqlite3.Connection | None = None,
    allow_contaminated_batches: bool = False,
) -> tuple[list[str], int]:
    _verified_report_id(report_id, payload)
    if payload.get("candidate_id") != candidate_id:
        raise ResearchRegistryError("research dashboard checkpoint candidate is invalid")
    if payload.get("candidate_state") != state.value:
        raise ResearchRegistryError("research dashboard checkpoint state is invalid")
    try:
        assert_historical_checkpoint_report_backed_by_observations(
            registry.connection
            if authentication_connection is None
            else authentication_connection,
            candidate_id=candidate_id,
            report_id=report_id,
            payload=payload,
            state=state,
        )
    except ValueError as exc:
        raise ResearchRegistryError(str(exc)) from exc
    batch_ids = _string_list(payload, "batch_ids")
    return batch_ids, _source_end_ms(
        registry,
        candidate_id=candidate_id,
        batch_ids=batch_ids,
        allow_contaminated=allow_contaminated_batches,
    )


def _checkpoint_history(
    registry: ResearchRegistry,
    *,
    candidate_id: str,
    candidate_state: ResearchCandidateState,
) -> list[dict[str, object]]:
    reports = _performance_reports(registry, candidate_id=candidate_id)
    commits = load_authenticated_checkpoint_commits(
        registry.connection,
        candidate_id=candidate_id,
    )
    if not reports:
        if commits:
            raise ResearchRegistryError(
                "research dashboard checkpoint commit is missing its performance report"
            )
        return []

    suppress_economics = candidate_state is ResearchCandidateState.REJECTED_CONTAMINATION
    authentication_connection: sqlite3.Connection | None = None
    if suppress_economics:
        authentication_connection = _contamination_authentication_connection(
            registry,
            candidate_id=candidate_id,
        )

    try:
        commits_by_report = {commit.report_id: commit for commit in commits}
        committed_ids = set(commits_by_report)
        if not committed_ids.issubset(reports):
            raise ResearchRegistryError(
                "research dashboard checkpoint commit is missing its performance report"
            )

        ordered: list[
            tuple[int, str, ResearchCandidateState, list[str], int, dict[str, object]]
        ] = []
        if set(reports) == committed_ids:
            for commit in commits:
                payload = reports[commit.report_id]
                batch_ids, source_end_ms = _authenticate_history_report(
                    registry,
                    candidate_id=candidate_id,
                    report_id=commit.report_id,
                    payload=payload,
                    state=commit.state,
                    authentication_connection=authentication_connection,
                    allow_contaminated_batches=suppress_economics,
                )
                ordered.append(
                    (
                        commit.commit_index,
                        commit.report_id,
                        commit.state,
                        batch_ids,
                        source_end_ms,
                        payload,
                    )
                )
        else:
            legacy: list[
                tuple[int, int, str, ResearchCandidateState, list[str], dict[str, object]]
            ] = []
            for report_id, payload in reports.items():
                try:
                    state = _report_state(payload)
                    existing_commit = commits_by_report.get(report_id)
                    if existing_commit is not None and existing_commit.state is not state:
                        raise ResearchRegistryError(
                            "research dashboard checkpoint state is invalid"
                        )
                    batch_ids, source_end_ms = _authenticate_history_report(
                        registry,
                        candidate_id=candidate_id,
                        report_id=report_id,
                        payload=payload,
                        state=state,
                        authentication_connection=authentication_connection,
                        allow_contaminated_batches=suppress_economics,
                    )
                except ResearchRegistryError as exc:
                    raise ResearchRegistryError(
                        "research dashboard found unauthenticated performance report"
                    ) from exc
                legacy.append(
                    (source_end_ms, len(batch_ids), report_id, state, batch_ids, payload)
                )
            legacy.sort(key=lambda item: (item[0], item[1], item[2]))
            ordered = [
                (index, report_id, state, batch_ids, source_end_ms, payload)
                for index, (
                    source_end_ms,
                    _batch_count,
                    report_id,
                    state,
                    batch_ids,
                    payload,
                ) in enumerate(legacy, start=1)
            ]

        previous_batch_ids: set[str] = set()
        history: list[dict[str, object]] = []
        for commit_index, _report_id, _state, batch_ids, source_end_ms, payload in ordered:
            current_batch_ids = set(batch_ids)
            if not previous_batch_ids.issubset(current_batch_ids):
                raise ResearchRegistryError(
                    "research dashboard checkpoint history is not cumulative"
                )
            previous_batch_ids = current_batch_ids
            checkpoint = dict(payload)
            checkpoint["commit_index"] = commit_index
            checkpoint["source_end_ms"] = source_end_ms
            history.append(checkpoint)

        if suppress_economics:
            return []

        latest_index, latest_report_id, latest_state, _batch_ids, _source_end, latest_payload = (
            ordered[-1]
        )
        del latest_index
        try:
            assert_checkpoint_report_backed_by_observations(
                registry.connection,
                candidate_id=candidate_id,
                report_id=latest_report_id,
                payload=latest_payload,
                state=latest_state,
            )
        except ValueError as exc:
            raise ResearchRegistryError(str(exc)) from exc
        return history
    finally:
        if authentication_connection is not None:
            authentication_connection.close()


def _build_research_status(registry: ResearchRegistry) -> dict[str, object]:
    candidates: list[dict[str, object]] = []
    state_counts: Counter[str] = Counter()
    for candidate_id in _candidate_ids(registry):
        candidate = registry.load_candidate(candidate_id)
        state_counts[candidate.state.value] += 1
        checkpoints = _checkpoint_history(
            registry,
            candidate_id=candidate_id,
            candidate_state=candidate.state,
        )
        reports = _performance_reports(registry, candidate_id=candidate_id)
        candidates.append(
            {
                "candidate_id": candidate.candidate_id,
                "family_id": candidate.family_id,
                "parent_candidate_id": candidate.parent_candidate_id,
                "ancestor_candidate_ids": list(candidate.ancestor_candidate_ids),
                "config_digest": candidate.config_digest,
                "code_revision": candidate.code_revision,
                "execution_config_json": candidate.execution_config_json,
                "risk_config_json": candidate.risk_config_json,
                "state": candidate.state.value,
                "first_observation_ms": candidate.first_observation_ms,
                "last_observation_ms": candidate.last_observation_ms,
                "source_provenance_ids": list(candidate.source_provenance_ids),
                "local_touched_intervals": _interval_payload(
                    candidate.local_touched_intervals
                ),
                "effective_touched_intervals": _interval_payload(
                    candidate.effective_touched_intervals
                ),
                "checkpoint_count": len(reports),
                "economics_visible": (
                    candidate.state is not ResearchCandidateState.REJECTED_CONTAMINATION
                ),
                "checkpoints": checkpoints,
            }
        )
    return {
        "label": RESEARCH_STATUS_LABEL,
        "candidate_count": len(candidates),
        "state_counts": dict(sorted(state_counts.items())),
        "candidates": candidates,
    }


def build_research_status(registry: ResearchRegistry) -> dict[str, object]:
    connection = registry.connection
    owns_snapshot = not connection.in_transaction
    if owns_snapshot:
        connection.execute("BEGIN")
    try:
        return _build_research_status(registry)
    finally:
        if owns_snapshot:
            connection.rollback()


def _mapping(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError(f"research status {field} must be an object")
    return value


def _mapping_list(value: object, field: str) -> list[dict[str, object]]:
    if not isinstance(value, list):
        raise ValueError(f"research status {field} must be an array")
    return [_mapping(item, field) for item in value]


def _cell(value: object) -> str:
    if value is None:
        return "—"
    return str(value).replace("|", "\\|").replace("\n", " ")


def _candidate_latest(candidate: dict[str, object]) -> dict[str, object] | None:
    if candidate.get("economics_visible") is not True:
        return None
    checkpoints = _mapping_list(candidate.get("checkpoints"), "candidate checkpoints")
    return checkpoints[-1] if checkpoints else None


def render_research_status_markdown(snapshot: dict[str, object]) -> str:
    if snapshot.get("label") != RESEARCH_STATUS_LABEL:
        raise ValueError("research status label is not the locked non-promotional label")
    candidates = _mapping_list(snapshot.get("candidates"), "candidates")
    lines = [
        "# Research Status",
        "",
        f"**{RESEARCH_STATUS_LABEL}**",
        "",
        "Research results are not promotion or verified-edge evidence.",
        "",
    ]
    if not candidates:
        lines.append("No research candidates.")
        return "\n".join(lines) + "\n"

    lines.extend(
        [
            "| Candidate | State | Checkpoints | Trades | Days | Net PnL | Mean R | Posterior |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for candidate in candidates:
        latest = _candidate_latest(candidate)
        lines.append(
            "| "
            + " | ".join(
                (
                    _cell(candidate.get("candidate_id")),
                    _cell(candidate.get("state")),
                    _cell(candidate.get("checkpoint_count")),
                    _cell(None if latest is None else latest.get("closed_trade_count")),
                    _cell(None if latest is None else latest.get("closed_trade_days")),
                    _cell(None if latest is None else latest.get("net_pnl")),
                    _cell(None if latest is None else latest.get("mean_net_r")),
                    _cell(
                        None
                        if latest is None
                        else latest.get("posterior_probability_positive")
                    ),
                )
            )
            + " |"
        )

    for candidate in candidates:
        candidate_id = _cell(candidate.get("candidate_id"))
        lines.extend(["", f"## {candidate_id} checkpoint history", ""])
        if candidate.get("economics_visible") is not True:
            lines.append("Economics hidden because the candidate is contaminated.")
            continue
        checkpoints = _mapping_list(candidate.get("checkpoints"), "candidate checkpoints")
        if not checkpoints:
            lines.append("No authenticated checkpoints.")
            continue
        lines.extend(
            [
                "| # | Source end ms | Checkpoint | Trades | Days | Net PnL | Mean R | Posterior |",
                "| ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for checkpoint in checkpoints:
            lines.append(
                "| "
                + " | ".join(
                    (
                        _cell(checkpoint.get("commit_index")),
                        _cell(checkpoint.get("source_end_ms")),
                        _cell(checkpoint.get("checkpoint_state")),
                        _cell(checkpoint.get("closed_trade_count")),
                        _cell(checkpoint.get("closed_trade_days")),
                        _cell(checkpoint.get("net_pnl")),
                        _cell(checkpoint.get("mean_net_r")),
                        _cell(checkpoint.get("posterior_probability_positive")),
                    )
                )
                + " |"
            )
    return "\n".join(lines) + "\n"
