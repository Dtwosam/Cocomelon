"""Write-once, provenance-bound genesis for truly new paired v2 research accounts.

This is a *declaration of initial conditions*, not an exchange-data attestation.
Never recreate a missing genesis for already-advanced execution SQLite stores.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Final, cast

from cocomelon.research.loss_context_portfolio_shadow_candidate import (
    LossContextPortfolioShadowFreeze,
)
from cocomelon.research.prospective_both_side_trend_paired_v2_freeze import (
    FORWARD_NOT_BEFORE_MS_V2,
    FROZEN_AT_MS_V2,
    TRIAL_ID_V2,
    both_side_trend_matched_shadow_v2_freeze,
)

GENESIS_FILE_V2: Final = "v2-genesis.json"
GENESIS_SCHEMA_V2: Final = 1
STATE_FILE: Final = "paired-shadow-state.json"
SQLITE_STORE_FILES: Final = (
    "baseline-execution.sqlite3",
    "candidate-execution.sqlite3",
)
_SHA_CHARS: Final = frozenset("0123456789abcdef")


class V2GenesisError(ValueError):
    """V2 paper account origin cannot be independently established."""


def _digest(payload: Mapping[str, object]) -> str:
    return hashlib.sha256(json.dumps(
        payload, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False,
    ).encode("utf-8")).hexdigest()


def _positive_int(value: object, field: str) -> int:
    if type(value) is not int or value <= 0:
        raise V2GenesisError(f"{field} must be a positive integer")
    return value


def _money(value: object) -> Decimal:
    if not isinstance(value, str):
        raise V2GenesisError("v2 genesis starting cash is not an exact string")
    try:
        amount = Decimal(value)
    except InvalidOperation as exc:
        raise V2GenesisError("v2 genesis starting cash is not finite") from exc
    if not amount.is_finite() or amount <= 0:
        raise V2GenesisError("v2 genesis starting cash must be finite and positive")
    return amount


def verify_v2_genesis(
    value: object, *, require_github_identity: bool = True,
) -> dict[str, object]:
    if not isinstance(value, dict) or not all(
        isinstance(key, str) for key in value
    ):
        raise V2GenesisError("v2 genesis must be a JSON object")
    payload = cast(dict[str, object], value)
    actual = dict(payload)
    recorded_digest = actual.pop("genesis_digest", None)
    if not isinstance(recorded_digest, str) or recorded_digest != _digest(actual):
        raise V2GenesisError("v2 genesis digest mismatch")
    freeze = both_side_trend_matched_shadow_v2_freeze()
    fixed = {
        "schema_version": GENESIS_SCHEMA_V2,
        "trial_id": TRIAL_ID_V2,
        "frozen_candidate_id": freeze.candidate_id,
        "source_composition_digest": freeze.source_composition_digest,
        "frozen_at_ms": FROZEN_AT_MS_V2,
        "forward_not_before_ms": FORWARD_NOT_BEFORE_MS_V2,
        "initial_record_count": 0,
        "initial_signed_review_rows": 0,
        "original_v1_account_reuse": False,
        "research_only": True,
        "paper_only": True,
        "shadow_only": True,
        "execution_authority": False,
        "promotion_authority": False,
    }
    for name, expected in fixed.items():
        if type(payload.get(name)) is not type(expected) or payload[name] != expected:
            raise V2GenesisError(f"v2 genesis {name} does not match fixed freeze")
    started_at = _positive_int(payload.get("genesis_startup_ms"), "genesis_startup_ms")
    if started_at < FROZEN_AT_MS_V2:
        raise V2GenesisError("v2 genesis predates frozen calendar")
    markets = payload.get("selected_markets")
    if (
        not isinstance(markets, list) or not markets
        or any(not isinstance(market, str) or not market for market in markets)
        or sorted(set(markets)) != markets
    ):
        raise V2GenesisError("v2 genesis market selection is not canonical")
    replay_digest = payload.get("replay_config_digest")
    if (
        not isinstance(replay_digest, str) or len(replay_digest) != 64
        or any(char not in _SHA_CHARS for char in replay_digest)
    ):
        raise V2GenesisError("v2 genesis replay configuration digest invalid")
    _money(payload.get("initial_cash_each_lane"))
    source_run = payload.get("source_github_run_id")
    source_attempt = payload.get("source_github_attempt")
    source_sha = payload.get("source_github_head_sha")
    if require_github_identity or any(
        value is not None for value in (source_run, source_attempt, source_sha)
    ):
        _positive_int(source_run, "source_github_run_id")
        _positive_int(source_attempt, "source_github_attempt")
        if (
            not isinstance(source_sha, str) or len(source_sha) != 40
            or any(char not in _SHA_CHARS for char in source_sha)
        ):
            raise V2GenesisError("v2 genesis source GitHub commit invalid")
    else:
        if source_run is not None or source_attempt is not None or source_sha is not None:
            raise V2GenesisError("partial v2 genesis source identity invalid")
    return payload


def prepare_v2_genesis(
    state_root: Path,
    *,
    freeze: LossContextPortfolioShadowFreeze,
    startup_timestamp_ms: int,
    selected_markets: Sequence[str],
    replay_config_digest: str,
    starting_cash: Decimal,
) -> dict[str, object]:
    """Create only before the first execution store; later require exact match.

    No missing-origin "recovery": a restored account without its original
    genesis is quarantined, and the ordinary paper strategy is unaffected.
    """
    if freeze != both_side_trend_matched_shadow_v2_freeze():
        raise V2GenesisError("v2 genesis frozen candidate differs")
    if type(startup_timestamp_ms) is not int:
        raise V2GenesisError("v2 genesis startup timestamp must be integer")
    root = Path(state_root)
    root.mkdir(parents=True, exist_ok=True)
    target = root / GENESIS_FILE_V2
    canonical_markets = sorted(item for item in selected_markets)
    if len(canonical_markets) != len(set(canonical_markets)):
        raise V2GenesisError("duplicate v2 genesis selected market")
    if target.exists():
        existing = verify_v2_genesis(
            json.loads(target.read_text(encoding="utf-8")),
            require_github_identity=False,
        )
        if (
            existing.get("replay_config_digest") != replay_config_digest
            or _money(existing.get("initial_cash_each_lane")) != starting_cash
            or startup_timestamp_ms < _positive_int(
                existing.get("genesis_startup_ms"), "genesis_startup_ms",
            )
        ):
            raise V2GenesisError("restored v2 origin/configuration changed")
        if not all((root / item).is_file() for item in (
            STATE_FILE, *SQLITE_STORE_FILES,
        )):
            raise V2GenesisError(
                "restored v2 genesis lacks signed state or both SQLite stores"
            )
        # The first worker's selection belongs to immutable genesis, not to
        # the ongoing scanner. During normal mainnet paper operation markets
        # are reranked/reconciled; forcing today's selection to equal the
        # originating list would silently kill a valid forward v2 campaign
        # at the first handoff. Instead require the *last signed* universe
        # before the actor opens the exact restored execution stores.
        try:
            signed = json.loads(
                (root / STATE_FILE).read_text(encoding="utf-8"),
            )
        except (OSError, ValueError) as exc:
            raise V2GenesisError(
                "restored v2 market universe lacks readable signed state"
            ) from exc
        if not isinstance(signed, dict):
            raise V2GenesisError("restored v2 signed state is not an object")
        unsigned = dict(signed)
        state_digest = unsigned.pop("state_digest", None)
        if (
            not isinstance(state_digest, str)
            or state_digest != _digest(unsigned)
            or unsigned.get("portfolio_shadow_candidate_id")
            != existing["frozen_candidate_id"]
            or unsigned.get("replay_config_digest")
            != existing["replay_config_digest"]
        ):
            raise V2GenesisError(
                "restored v2 ranked universe not bound to signed candidate/config"
            )
        restored_markets = unsigned.get("selected_markets")
        if (
            not isinstance(restored_markets, list)
            or not restored_markets
            or any(
                not isinstance(market, str) or not market
                for market in restored_markets
            )
            or sorted(set(restored_markets)) != restored_markets
        ):
            raise V2GenesisError("restored v2 ranked universe not canonical")
        # The actual actor will restore this signed selection and then
        # reconcile both lanes to the new mainnet scanner selection. Neither
        # lane may import data from v1 or reset its signed economic history.
        return existing

    # The freeze lives outside this root. Any nonempty new-root evidence
    # (including a prior SQLite) means the initial account is not provably clean.
    if any(root.iterdir()):
        raise V2GenesisError("v2 state already advanced without a genesis seal")
    def source_number(name: str) -> int | None:
        raw = os.getenv(name)
        return int(raw) if raw and raw.isdecimal() and int(raw) > 0 else None

    source_sha = os.getenv("GITHUB_SHA")
    genesis: dict[str, object] = {
        "schema_version": GENESIS_SCHEMA_V2,
        "trial_id": TRIAL_ID_V2,
        "frozen_candidate_id": freeze.candidate_id,
        "source_composition_digest": freeze.source_composition_digest,
        "frozen_at_ms": FROZEN_AT_MS_V2,
        "forward_not_before_ms": FORWARD_NOT_BEFORE_MS_V2,
        "genesis_startup_ms": startup_timestamp_ms,
        "selected_markets": canonical_markets,
        "replay_config_digest": replay_config_digest,
        "initial_cash_each_lane": str(starting_cash),
        "initial_record_count": 0,
        "initial_signed_review_rows": 0,
        "source_github_run_id": source_number("GITHUB_RUN_ID"),
        "source_github_attempt": source_number("GITHUB_RUN_ATTEMPT"),
        "source_github_head_sha": source_sha,
        "original_v1_account_reuse": False,
        "research_only": True,
        "paper_only": True,
        "shadow_only": True,
        "execution_authority": False,
        "promotion_authority": False,
    }
    genesis["genesis_digest"] = _digest(genesis)
    verify_v2_genesis(genesis, require_github_identity=False)
    payload = json.dumps(genesis, sort_keys=True, separators=(",", ":")) + "\n"
    # Atomic write-once: never overwrite a signed origin following any failure.
    with target.open("x", encoding="utf-8") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    return genesis
