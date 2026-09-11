from pathlib import Path

path = Path("src/cocomelon/research/fanout.py")
text = path.read_text(encoding="utf-8")
if "def load_research_fanout_plan(" in text:
    raise SystemExit("fanout plan loader already exists")
addition = r'''


def load_research_fanout_plan(path: str | Path) -> tuple[ResearchFanoutCandidate, ...]:
    target = Path(path)
    try:
        decoded = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("research fanout plan must contain valid JSON") from exc
    if not isinstance(decoded, dict) or set(decoded) != {"candidates", "schema_version"}:
        raise ValueError("research fanout plan contract is invalid")
    if decoded.get("schema_version") != 1:
        raise ValueError("research fanout plan schema version is invalid")
    raw_candidates = decoded.get("candidates")
    if not isinstance(raw_candidates, list) or not 1 <= len(raw_candidates) <= 2:
        raise ValueError("research fanout plan must contain one or two candidates")

    candidates: list[ResearchFanoutCandidate] = []
    expected_fields = {
        "artifact_key",
        "attempt_id",
        "batch_id",
        "candidate_id",
        "code_revision",
        "config_digest",
        "execution_config_json",
        "required",
        "risk_config_json",
        "source_id",
    }
    for raw in raw_candidates:
        if not isinstance(raw, dict) or set(raw) != expected_fields:
            raise ValueError("research fanout candidate fields are invalid")
        candidate_id = str(raw["candidate_id"]).strip()
        artifact_key = str(raw["artifact_key"]).strip()
        if not candidate_id or artifact_key != _artifact_key(candidate_id):
            raise ValueError("research fanout artifact key does not match candidate")
        required = raw["required"]
        if not isinstance(required, bool):
            raise ValueError("research fanout required flag must be boolean")
        candidate = ResearchFanoutCandidate(
            candidate_id=candidate_id,
            code_revision=_require_revision(str(raw["code_revision"])),
            config_digest=str(raw["config_digest"]).strip(),
            execution_config_json=str(raw["execution_config_json"]),
            risk_config_json=str(raw["risk_config_json"]),
            required=required,
            attempt_id=_require_id(str(raw["attempt_id"]), "attempt_id"),
            batch_id=_require_id(str(raw["batch_id"]), "batch_id"),
            source_id=_require_id(str(raw["source_id"]), "source_id"),
            artifact_key=artifact_key,
        )
        candidate.manifest
        candidates.append(candidate)

    resolved = tuple(candidates)
    if not resolved[0].required or any(item.required for item in resolved[1:]):
        raise ValueError("research fanout required ordering is invalid")
    if len({item.candidate_id for item in resolved}) != len(resolved):
        raise ValueError("research fanout candidate ids must be unique")
    if len({item.artifact_key for item in resolved}) != len(resolved):
        raise ValueError("research fanout artifact keys must be unique")
    if len({item.source_id for item in resolved}) != 1:
        raise ValueError("research fanout candidates must share one source id")
    return resolved
'''
path.write_text(text.rstrip() + addition + "\n", encoding="utf-8")
