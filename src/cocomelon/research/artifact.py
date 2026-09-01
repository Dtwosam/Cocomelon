from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from dataclasses import dataclass
from decimal import Decimal, localcontext
from pathlib import Path

from cocomelon.domain.evaluation import TradeEvaluationSample
from cocomelon.domain.journal import ObservationKind
from cocomelon.domain.replay import ReplayManifest
from cocomelon.evaluation.dataset import EvaluationDatasetError, build_evaluation_dataset
from cocomelon.evaluation.mainnet_evidence import (
    MainnetEvidenceError,
    verify_mainnet_evidence_cohort_payload,
)
from cocomelon.evaluation.metrics import AUTHORITATIVE_CONTEXT
from cocomelon.evaluation.store import EvaluationFactStore
from cocomelon.evidence.bundle import load_baseline_replay_bundle
from cocomelon.journal.store import JournalConsistencyError, JournalStore
from cocomelon.research.contracts import TimeInterval
from cocomelon.research.strategy_seam import (
    load_candidate_strategy_decisions,
    strategy_decision_from_payload,
)

_HARD_RISK_REASONS = frozenset(
    {
        "daily_loss_lockout",
        "weekly_drawdown_lockout",
        "consecutive_loss_cooldown",
        "risk_state_inconsistent",
    }
)


class ResearchArtifactError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class VerifiedResearchBatch:
    batch_id: str
    source_id: str
    replay_run_id: str
    interval: TimeInterval
    manifest_id: str
    result_digest: str
    source_digest: str
    code_revision: str
    config_digest: str
    candidate_config_digest: str | None
    trade_ids: tuple[str, ...]
    sample_digest: str
    samples: tuple[TradeEvaluationSample, ...]
    planned_risk_fractions: tuple[tuple[str, Decimal], ...]
    operational_failure: bool
    hard_risk_failure: bool
    health_reason_codes: tuple[str, ...]


def _require_nonempty(value: str, field: str) -> None:
    if not value.strip():
        raise ResearchArtifactError(f"{field} must not be empty")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise ResearchArtifactError(f"unable to hash research artifact file: {path}") from exc
    return digest.hexdigest()


def _canonical_digest(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _read_replay(path: Path) -> dict[str, object]:
    if not path.is_file():
        raise ResearchArtifactError(f"research replay metadata is missing: {path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ResearchArtifactError("research replay metadata must be valid JSON") from exc
    if not isinstance(raw, dict) or not all(isinstance(key, str) for key in raw):
        raise ResearchArtifactError("research replay metadata must be an object")
    return raw


def _sample_digest(samples: tuple[TradeEvaluationSample, ...]) -> str:
    identities = tuple(sorted((sample.trade_id, sample.sample_id) for sample in samples))
    return _canonical_digest(identities)


def _candidate_config_digest(
    source_root: Path,
    manifest: ReplayManifest,
) -> str | None:
    try:
        bundle = load_baseline_replay_bundle(source_root / "bundle.json")
    except ValueError:
        return None
    if bundle.manifest.manifest_id != manifest.manifest_id:
        raise ResearchArtifactError(
            "research replay bundle does not match canonical manifest identity"
        )
    if bundle.manifest.code_revision != manifest.code_revision:
        raise ResearchArtifactError(
            "research replay bundle does not match canonical code revision"
        )
    if bundle.manifest.config_digest != manifest.config_digest:
        raise ResearchArtifactError(
            "research replay bundle does not match canonical manifest config digest"
        )
    return bundle.replay_config.config_digest


def _candidate_strategy_identity(
    source_root: Path,
    *,
    manifest: ReplayManifest,
    journal: JournalStore,
    replay_run_id: str,
) -> tuple[str, str | None, str | None]:
    strategy_path = source_root / "strategy-decisions.json"
    fallback_config = _candidate_config_digest(source_root, manifest)
    if not strategy_path.is_file():
        return manifest.code_revision, fallback_config, None

    try:
        artifact = load_candidate_strategy_decisions(
            strategy_path,
            bundle_path=source_root / "bundle.json",
        )
    except ValueError as exc:
        raise ResearchArtifactError("research candidate strategy artifact is invalid") from exc

    if fallback_config is None or artifact.candidate_config_digest != fallback_config:
        raise ResearchArtifactError(
            "research candidate strategy config does not match trusted replay config"
        )

    artifact_decision_ids: list[str] = []
    for item in artifact.decisions:
        try:
            decision = strategy_decision_from_payload(item.get("decision"))
        except ValueError as exc:
            raise ResearchArtifactError(
                "research candidate strategy decision is invalid"
            ) from exc
        artifact_decision_ids.append(decision.decision_id)

    journal_decision_ids = sorted(
        str(observation.strategy_decision_id)
        for observation in journal.iter_observations()
        if observation.replay_run_id == replay_run_id
        and observation.kind is ObservationKind.STRATEGY_DECISION
        and observation.strategy_decision_id is not None
    )
    if sorted(artifact_decision_ids) != journal_decision_ids:
        raise ResearchArtifactError(
            "research candidate strategy decisions do not match trusted replay journal"
        )
    if len(artifact_decision_ids) != len(journal_decision_ids):
        raise ResearchArtifactError(
            "research candidate strategy decision accounting is incomplete"
        )

    return (
        artifact.candidate_code_revision,
        artifact.candidate_config_digest,
        _sha256(strategy_path),
    )


def _verified_recording_segment_digest(
    source_root: Path,
    manifest: ReplayManifest,
) -> str:
    recording_root = (source_root.parent / "recording").resolve()
    entries: list[tuple[str, str, int, int]] = []
    for segment in manifest.segments:
        segment_path = (recording_root / segment.relative_path).resolve()
        if recording_root not in segment_path.parents:
            raise ResearchArtifactError("research recording segment escapes recording root")
        if not segment_path.is_file():
            raise ResearchArtifactError(
                f"research recording source segment is missing: {segment.relative_path}"
            )
        try:
            byte_count = segment_path.stat().st_size
            with segment_path.open("rb") as handle:
                row_count = sum(1 for _ in handle)
        except OSError as exc:
            raise ResearchArtifactError("unable to read research recording segment") from exc
        digest = _sha256(segment_path)
        if digest != segment.sha256:
            raise ResearchArtifactError("research recording segment digest mismatch")
        if byte_count != segment.byte_count:
            raise ResearchArtifactError("research recording segment byte count mismatch")
        if row_count != segment.row_count:
            raise ResearchArtifactError("research recording segment row count mismatch")
        entries.append(
            (segment.relative_path, digest, segment.byte_count, segment.row_count)
        )
    if not entries:
        raise ResearchArtifactError("research replay manifest has no recording source segments")
    return _canonical_digest(tuple(sorted(entries)))


def verify_research_batch_artifact(
    root: str | Path,
    *,
    batch_id: str,
    source_id: str,
) -> VerifiedResearchBatch:
    _require_nonempty(batch_id, "batch_id")
    _require_nonempty(source_id, "source_id")
    source_root = Path(root).resolve()
    paths = {
        "bundle.json": source_root / "bundle.json",
        "facts.sqlite3": source_root / "facts.sqlite3",
        "journal.sqlite3": source_root / "journal.sqlite3",
        "replay.json": source_root / "replay.json",
    }
    missing = [name for name, path in paths.items() if not path.is_file()]
    if missing:
        raise ResearchArtifactError(f"research artifact file is missing: {missing[0]}")

    try:
        mainnet = verify_mainnet_evidence_cohort_payload(source_root)
    except MainnetEvidenceError as exc:
        raise ResearchArtifactError(
            "research artifact must be a verified genuine mainnet evidence cohort"
        ) from exc
    mainnet_source_digest = mainnet.get("source_digest")
    if not isinstance(mainnet_source_digest, str) or len(mainnet_source_digest) != 64:
        raise ResearchArtifactError("research mainnet source digest is invalid")

    before = {name: _sha256(path) for name, path in paths.items()}
    replay = _read_replay(paths["replay.json"])
    order_flag_key = "live_" + "order" + "s"

    candidate_code_revision = ""
    candidate_config_digest: str | None = None
    candidate_strategy_digest: str | None = None
    recording_segment_digest = ""
    canonical_trade_ids: tuple[str, ...] = ()
    samples: tuple[TradeEvaluationSample, ...] = ()
    planned_risk_fractions: list[tuple[str, Decimal]] = []
    health_reasons: set[str] = set()
    hard_risk_reasons: set[str] = set()

    with tempfile.TemporaryDirectory(prefix="cocomelon-research-artifact-") as temporary:
        work_root = Path(temporary)
        work_journal_path = work_root / "journal.sqlite3"
        work_facts_path = work_root / "facts.sqlite3"
        shutil.copy2(paths["journal.sqlite3"], work_journal_path)
        shutil.copy2(paths["facts.sqlite3"], work_facts_path)
        if _sha256(work_journal_path) != before["journal.sqlite3"]:
            raise ResearchArtifactError("research journal copy checksum mismatch")
        if _sha256(work_facts_path) != before["facts.sqlite3"]:
            raise ResearchArtifactError("research facts copy checksum mismatch")

        journal = JournalStore(work_journal_path)
        facts = EvaluationFactStore(work_facts_path)
        try:
            results = tuple(journal.iter_replay_results())
            if len(results) != 1:
                raise ResearchArtifactError(
                    "research batch artifact must contain exactly one finished replay result"
                )
            result = results[0]
            manifest = journal.load_manifest(result.manifest_id)
            if manifest is None:
                raise ResearchArtifactError("research replay manifest is missing")
            if (
                manifest.start_ms != result.start_ms
                or manifest.end_ms != result.end_ms
                or manifest.evidence_class is not result.evidence_class
            ):
                raise ResearchArtifactError("research replay manifest/result identity mismatch")

            required_mainnet = {
                "code_revision": manifest.code_revision,
                "run_id": result.run_id,
                "manifest_id": manifest.manifest_id,
                "result_digest": result.result_digest,
                "start_ms": manifest.start_ms,
                "end_ms": manifest.end_ms,
                "data_complete": result.data_complete,
            }
            for field, expected in required_mainnet.items():
                if mainnet.get(field) != expected:
                    raise ResearchArtifactError(
                        f"research mainnet attestation does not match canonical {field}"
                    )

            (
                candidate_code_revision,
                candidate_config_digest,
                candidate_strategy_digest,
            ) = _candidate_strategy_identity(
                source_root,
                manifest=manifest,
                journal=journal,
                replay_run_id=result.run_id,
            )
            recording_segment_digest = _verified_recording_segment_digest(
                source_root,
                manifest,
            )

            required_replay = {
                "run_id": result.run_id,
                "manifest_id": result.manifest_id,
                "result_digest": result.result_digest,
                "data_complete": result.data_complete,
            }
            for field, expected in required_replay.items():
                if replay.get(field) != expected:
                    raise ResearchArtifactError(
                        f"research replay metadata does not match canonical {field}"
                    )
            if not isinstance(replay.get("network_access"), bool):
                raise ResearchArtifactError("research replay network_access must be boolean")
            if not isinstance(replay.get(order_flag_key), bool):
                raise ResearchArtifactError(
                    "research replay order-execution flag must be boolean"
                )

            try:
                built = build_evaluation_dataset(
                    journal,
                    facts,
                    replay_run_ids=(result.run_id,),
                    code_revision=manifest.code_revision,
                )
            except EvaluationDatasetError as exc:
                raise ResearchArtifactError("research evaluation dataset is invalid") from exc

            canonical_trade_ids = tuple(sorted(result.closed_trade_ids))
            sample_trade_ids = tuple(sorted(sample.trade_id for sample in built.samples))
            trades = {
                trade.trade_id: trade
                for trade in journal.iter_trades()
                if trade.replay_run_id == result.run_id
            }
            if set(trades) != set(canonical_trade_ids):
                raise ResearchArtifactError(
                    "research journal trades do not match canonical replay closed trades"
                )

            if result.data_complete is not True or built.manifest.data_complete is not True:
                health_reasons.add("incomplete_replay")
            if result.processed_gaps != 0 or manifest.gap_refs or built.manifest.gap_refs:
                health_reasons.add("source_gap")
            if result.opened_positions != result.closed_positions:
                health_reasons.add("open_exposure")
            if built.excluded_trade_ids or sample_trade_ids != canonical_trade_ids:
                health_reasons.add("incomplete_trade_accounting")
            if replay["network_access"] is not False:
                health_reasons.add("unexpected_replay_network_access")
            if replay[order_flag_key] is not False:
                health_reasons.add("unexpected_" + order_flag_key)

            for observation in journal.iter_observations():
                if (
                    observation.replay_run_id == result.run_id
                    and observation.kind is ObservationKind.RISK_DECISION
                ):
                    hard_risk_reasons.update(
                        reason
                        for reason in observation.reason_codes
                        if reason in _HARD_RISK_REASONS
                    )
            health_reasons.update(hard_risk_reasons)

            with localcontext(AUTHORITATIVE_CONTEXT):
                for trade_id in canonical_trade_ids:
                    trade = trades[trade_id]
                    planned_risk_fractions.append(
                        (trade_id, trade.initial_risk_amount / trade.equity_before)
                    )

            samples = tuple(built.samples)
            config_digest = manifest.config_digest
            replay_run_id = result.run_id
            manifest_id = result.manifest_id
            result_digest = result.result_digest
            interval = TimeInterval(result.start_ms, result.end_ms)
        except JournalConsistencyError as exc:
            raise ResearchArtifactError("research journal is inconsistent") from exc
        finally:
            facts.close()
            journal.close()

    after = {name: _sha256(path) for name, path in paths.items()}
    if before != after:
        raise ResearchArtifactError("research artifact changed during verification")

    source_digest = _canonical_digest(
        {
            "candidate_strategy_digest": candidate_strategy_digest,
            "mainnet_source_digest": mainnet_source_digest,
            "recording_segment_digest": recording_segment_digest,
        }
    )
    operational_reasons = set(health_reasons) - hard_risk_reasons
    return VerifiedResearchBatch(
        batch_id=batch_id,
        source_id=source_id,
        replay_run_id=replay_run_id,
        interval=interval,
        manifest_id=manifest_id,
        result_digest=result_digest,
        source_digest=source_digest,
        code_revision=candidate_code_revision,
        config_digest=config_digest,
        candidate_config_digest=candidate_config_digest,
        trade_ids=canonical_trade_ids,
        sample_digest=_sample_digest(samples),
        samples=samples,
        planned_risk_fractions=tuple(planned_risk_fractions),
        operational_failure=bool(operational_reasons),
        hard_risk_failure=bool(hard_risk_reasons),
        health_reason_codes=tuple(sorted(health_reasons)),
    )
