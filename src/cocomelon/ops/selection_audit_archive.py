from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections.abc import Sequence
from pathlib import Path
from typing import cast

_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
_HEX64_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def _read_json_object(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"unable to read JSON object: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"expected a JSON object in {path}")
    return cast(dict[str, object], payload)


def _canonical_id(payload: dict[str, object]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _require_sha(value: object, *, label: str) -> str:
    if not isinstance(value, str) or _SHA_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{label} must be a lowercase 40-character git sha")
    return value


def _require_hex64(value: object, *, label: str) -> str:
    if not isinstance(value, str) or _HEX64_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{label} must be a lowercase 64-character hex digest")
    return value


def _require_nonnegative_int(value: object, *, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{label} must be a non-negative integer")
    return value


def _validate_final(payload: dict[str, object]) -> tuple[str, str]:
    final_id = _require_hex64(payload.get("final_id"), label="Phase 9 final id")
    base = {key: value for key, value in payload.items() if key != "final_id"}
    if final_id != _canonical_id(base):
        raise ValueError("Phase 9 final id is invalid")
    if payload.get("protocol_id") != "v2-phase9-one-shot":
        raise ValueError("Phase 9 final protocol id is invalid")
    if payload.get("one_shot_oos") is not True:
        raise ValueError("Phase 9 final state is not one-shot OOS")
    if payload.get("network_access") is not False or payload.get("live_orders") is not False:
        raise ValueError("Phase 9 final state violates offline-only semantics")
    attestation_id = _require_hex64(
        payload.get("mainnet_attestation_id"),
        label="Phase 9 mainnet attestation id",
    )
    return final_id, attestation_id


def _validate_selection_audit(
    path: Path,
    *,
    expected_source_run_id: int,
) -> dict[str, object]:
    payload = _read_json_object(path)
    source_run_id = _require_nonnegative_int(
        payload.get("source_run_id"),
        label="selection audit source run id",
    )
    if source_run_id <= 0 or source_run_id != expected_source_run_id:
        raise ValueError("selection audit source run id does not match filename")

    audit_id = _require_hex64(
        payload.get("selection_audit_id"),
        label="selection audit id",
    )
    base = {key: value for key, value in payload.items() if key != "selection_audit_id"}
    if audit_id != _canonical_id(base):
        raise ValueError("selection audit id is invalid")
    if payload.get("economic_claim") != "none":
        raise ValueError("selection audit economic claim is invalid")
    if payload.get("network_access") is not False or payload.get("live_orders") is not False:
        raise ValueError("selection audit violates offline-only semantics")
    _require_sha(
        payload.get("trigger_head_sha"),
        label="selection audit trigger head sha",
    )
    _require_sha(
        payload.get("attempt_ledger_revision"),
        label="selection audit ledger revision",
    )

    attempt_count = _require_nonnegative_int(
        payload.get("attempt_count"),
        label="selection audit attempt count",
    )
    rejected_count = _require_nonnegative_int(
        payload.get("rejected_attempt_count"),
        label="selection audit rejected attempt count",
    )
    admitted_attempt = _require_nonnegative_int(
        payload.get("admitted_attempt"),
        label="selection audit admitted attempt",
    )
    if attempt_count <= 0 or admitted_attempt <= 0 or rejected_count > attempt_count:
        raise ValueError("selection audit attempt metadata is invalid")

    ledger = payload.get("attempt_ledger")
    if not isinstance(ledger, dict):
        raise ValueError("selection audit attempt ledger is invalid")
    if ledger.get("selection_audit_only") is not True:
        raise ValueError("selection audit ledger is not audit-only")
    if ledger.get("economic_claim") != "none":
        raise ValueError("selection audit ledger economic claim is invalid")
    if ledger.get("network_access") is not False or ledger.get("live_orders") is not False:
        raise ValueError("selection audit ledger violates offline-only semantics")
    if ledger.get("attempt_count") != attempt_count:
        raise ValueError("selection audit attempt count does not match ledger")
    if ledger.get("admitted_attempt") != admitted_attempt:
        raise ValueError("selection audit admitted attempt does not match ledger")
    attempts = ledger.get("attempts")
    if not isinstance(attempts, list) or len(attempts) != attempt_count:
        raise ValueError("selection audit ledger attempts are invalid")
    observed_rejected = sum(
        1
        for item in attempts
        if isinstance(item, dict) and item.get("status") == "rejected"
    )
    observed_admitted = sum(
        1
        for item in attempts
        if isinstance(item, dict)
        and item.get("status") == "admitted"
        and item.get("attempt") == admitted_attempt
    )
    if observed_rejected != rejected_count or observed_admitted != 1:
        raise ValueError("selection audit ledger status counts are invalid")
    return payload


def build_selection_audit_archive(
    corpus_root: str | Path,
    phase9_final_path: str | Path,
    *,
    archive_tool_revision: str,
) -> dict[str, object]:
    corpus = Path(corpus_root)
    final_payload = _read_json_object(Path(phase9_final_path))
    final_id, final_attestation_id = _validate_final(final_payload)
    tool_revision = _require_sha(
        archive_tool_revision,
        label="selection audit archive tool revision",
    )

    attestation = _read_json_object(corpus / "mainnet-attestation.json")
    attestation_id = _require_hex64(
        attestation.get("attestation_id"),
        label="corpus mainnet attestation id",
    )
    if attestation_id != final_attestation_id:
        raise ValueError("mainnet attestation does not match Phase 9 final state")
    source_count = _require_nonnegative_int(
        attestation.get("source_count"),
        label="mainnet attestation source count",
    )
    sources = attestation.get("sources")
    if source_count <= 0 or not isinstance(sources, list) or len(sources) != source_count:
        raise ValueError("mainnet attestation source metadata is invalid")

    corpus_index = _read_json_object(corpus / "corpus-index.json")
    if corpus_index.get("mainnet_attestation_id") != attestation_id:
        raise ValueError("corpus index mainnet attestation id is invalid")
    expected_audit_count = _require_nonnegative_int(
        corpus_index.get("selection_audit_count"),
        label="corpus selection audit count",
    )

    audit_root = corpus / "selection-audits"
    audit_paths = sorted(audit_root.glob("*.json")) if audit_root.is_dir() else []
    audits: list[dict[str, object]] = []
    source_run_ids: list[int] = []
    audit_ids: list[str] = []
    for path in audit_paths:
        if not path.stem.isdigit() or int(path.stem) <= 0:
            raise ValueError("selection audit filename must be a positive source run id")
        expected_source_run_id = int(path.stem)
        payload = _validate_selection_audit(
            path,
            expected_source_run_id=expected_source_run_id,
        )
        source_run_ids.append(expected_source_run_id)
        audit_ids.append(
            _require_hex64(payload.get("selection_audit_id"), label="selection audit id")
        )
        audits.append(payload)

    if len(audits) != expected_audit_count:
        raise ValueError("selection audit count does not match corpus index")
    if len(audits) > source_count:
        raise ValueError("selection audit count exceeds attested source count")
    if len(set(source_run_ids)) != len(source_run_ids):
        raise ValueError("selection audit source run ids are not unique")

    base: dict[str, object] = {
        "schema_version": 1,
        "protocol_id": "v2-phase9-one-shot-selection-audits",
        "phase9_final_id": final_id,
        "mainnet_attestation_id": attestation_id,
        "archive_tool_revision": tool_revision,
        "attested_source_count": source_count,
        "selection_audit_count": len(audits),
        "legacy_source_count": source_count - len(audits),
        "audited_source_run_ids": source_run_ids,
        "selection_audit_ids": audit_ids,
        "selection_audits": audits,
        "economic_claim": "none",
        "network_access": False,
        "live_orders": False,
    }
    return {**base, "archive_id": _canonical_id(base)}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cocomelon-selection-audit-archive")
    parser.add_argument("--corpus-root", required=True, type=Path)
    parser.add_argument("--phase9-final", required=True, type=Path)
    parser.add_argument("--archive-tool-revision", required=True)
    parser.add_argument("--out", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    payload = build_selection_audit_archive(
        cast(Path, args.corpus_root),
        cast(Path, args.phase9_final),
        archive_tool_revision=str(args.archive_tool_revision),
    )
    output = cast(Path, args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, sort_keys=True))


if __name__ == "__main__":
    main()
