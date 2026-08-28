from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any

JsonObject = dict[str, object]

_ALLOWED_EDGE_STATUSES = {
    "invalid_evidence",
    "oos_contaminated",
    "insufficient_evidence",
    "no_edge_demonstrated",
    "candidate_edge",
}


def _phase9_v4_final_verdict(state: JsonObject) -> str:
    freeze_obj = state.get("freeze")
    final_obj = state.get("final")
    freeze = freeze_obj if isinstance(freeze_obj, dict) else None
    final = final_obj if isinstance(final_obj, dict) else None

    if final is None:
        return "Not measured yet"
    if freeze is None:
        raise RuntimeError("V4 final verdict exists without durable freeze")
    if final.get("freeze_id") != freeze.get("freeze_id"):
        raise RuntimeError("V4 final verdict freeze id mismatch")

    freeze_snapshot_id = freeze.get("snapshot_id")
    if not isinstance(freeze_snapshot_id, str) or not freeze_snapshot_id:
        raise RuntimeError("V4 final verdict freeze snapshot is invalid")

    protocol_state = final.get("protocol_state")
    if protocol_state == "insufficient_evidence":
        if final.get("final_type") != "terminal_insufficient":
            raise RuntimeError("V4 terminal verdict final type is invalid")
        if final.get("economic_claim") != "phase9_readiness_only":
            raise RuntimeError("V4 terminal verdict economic claim is invalid")
        if final.get("evaluation") is not None:
            raise RuntimeError("V4 terminal verdict contains an evaluation")
        terminal_obj = final.get("terminal")
        if not isinstance(terminal_obj, dict):
            raise RuntimeError("V4 terminal verdict payload is invalid")
        terminal = terminal_obj
        if terminal.get("edge_status") != "insufficient_evidence":
            raise RuntimeError("V4 terminal verdict edge status is invalid")
        if terminal.get("economic_claim") != "phase9_readiness_only":
            raise RuntimeError("V4 terminal verdict claim is invalid")
        if terminal.get("one_shot_oos") is not True:
            raise RuntimeError("V4 terminal verdict is not one-shot OOS")
        if terminal.get("network_access") is not False or terminal.get("live_orders") is not False:
            raise RuntimeError("V4 terminal verdict violates offline-only semantics")
        if terminal.get("snapshot_id") != freeze_snapshot_id:
            raise RuntimeError("V4 terminal verdict snapshot mismatch")
        return "INSUFFICIENT_EVIDENCE (readiness-only terminal)"

    if protocol_state == "evaluated":
        if final.get("final_type") != "evaluation":
            raise RuntimeError("V4 evaluated verdict final type is invalid")
        if final.get("economic_claim") != "phase9_baseline_edge_assessment":
            raise RuntimeError("V4 evaluated verdict economic claim is invalid")
        if final.get("terminal") is not None:
            raise RuntimeError("V4 evaluated verdict contains a terminal payload")
        evaluation_obj = final.get("evaluation")
        if not isinstance(evaluation_obj, dict):
            raise RuntimeError("V4 evaluated verdict payload is invalid")
        evaluation = evaluation_obj
        if evaluation.get("evaluation_name") != "v4-phase9-evaluation":
            raise RuntimeError("V4 final verdict evaluation identity is invalid")
        if evaluation.get("economic_claim") != "phase9_baseline_edge_assessment":
            raise RuntimeError("V4 evaluated verdict claim is invalid")
        if evaluation.get("one_shot_oos") is not True:
            raise RuntimeError("V4 evaluated verdict is not one-shot OOS")
        offline = evaluation.get("network_access") is False
        paper_only = evaluation.get("live_orders") is False
        if not offline or not paper_only:
            raise RuntimeError("V4 evaluated verdict violates offline-only semantics")
        if evaluation.get("snapshot_id") != freeze_snapshot_id:
            raise RuntimeError("V4 evaluated verdict snapshot mismatch")
        edge_status = evaluation.get("edge_status")
        if not isinstance(edge_status, str) or edge_status not in _ALLOWED_EDGE_STATUSES:
            raise RuntimeError("V4 evaluated verdict edge status is invalid")
        return edge_status.upper()

    raise RuntimeError("V4 final verdict protocol state is invalid")


def _replace_edge_line(body: str, verdict: str) -> str:
    updated, count = re.subn(
        r"(?m)^\*\*Economic edge:\*\* [^\n]*$",
        f"**Economic edge:** {verdict}  ",
        body,
    )
    if count != 1:
        raise RuntimeError("dashboard must contain exactly one Economic edge line")
    return updated


def _load_dashboard_state(repo: str) -> JsonObject:
    from build_evidence_dashboard import _phase9_v4_state

    state = _phase9_v4_state(repo)
    if not isinstance(state, dict):
        raise RuntimeError("V4 one-shot dashboard state is invalid")
    return state


def apply_final_verdict(patch: JsonObject, state: JsonObject) -> JsonObject:
    body = patch.get("body")
    if not isinstance(body, str):
        raise RuntimeError("dashboard patch body is invalid")
    verdict = _phase9_v4_final_verdict(state)
    return {**patch, "body": _replace_edge_line(body, verdict)}


def _read_patch(path: Path) -> JsonObject:
    try:
        payload: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("dashboard patch is invalid JSON") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("dashboard patch must be a JSON object")
    return {str(key): value for key, value in payload.items()}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--patch", required=True)
    args = parser.parse_args()

    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    if not repo or "/" not in repo:
        raise RuntimeError("GITHUB_REPOSITORY is invalid")

    patch_path = Path(args.patch).resolve()
    patch = _read_patch(patch_path)
    state = _load_dashboard_state(repo)
    updated = apply_final_verdict(patch, state)
    patch_path.write_text(
        json.dumps(updated, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
