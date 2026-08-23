# Phase 1 Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish a typed, testable Python foundation with mainnet-only configuration, shared domain contracts, secret-safe structured logging, a minimal operator CLI, and CI.

**Architecture:** Phase 1 contains no trading strategy, no external market-data collector, and no live exchange adapter. It creates stable contracts that later phases depend on while enforcing the project's mainnet-only and paper-default safety rules at configuration boundaries.

**Tech Stack:** Python 3.12, stdlib dataclasses/enums/logging/argparse, pytest, Ruff, mypy, GitHub Actions.

**Spec:** `docs/MASTER_SPEC.md`

## Global Constraints

- Hyperliquid testnet is forbidden.
- Main REST default is `https://api.hyperliquid.xyz`.
- Main WebSocket default is `wss://api.hyperliquid.xyz/ws`.
- Execution mode defaults to `paper`.
- Planned risk per trade is 0.25%; aggregate planned open risk is 0.75%; daily loss lockout is 1%; rolling weekly drawdown lockout is 3%.
- Python is the primary language; Solidity is not part of V1.
- No secrets may be stored in committed configuration or emitted in logs.
- No strategy, ML, market data, or live order logic is implemented in this phase.

---

## File map after Phase 1

```text
.
├── .env.example
├── .gitignore
├── .github/workflows/ci.yml
├── pyproject.toml
├── src/cocomelon/
│   ├── __init__.py
│   ├── __main__.py
│   ├── cli.py
│   ├── config.py
│   ├── logging_utils.py
│   ├── domain/
│   │   ├── __init__.py
│   │   ├── execution.py
│   │   ├── journal.py
│   │   ├── market.py
│   │   ├── risk.py
│   │   └── strategy.py
│   └── util/
│       ├── __init__.py
│       ├── ids.py
│       └── time.py
└── tests/
    ├── test_cli.py
    ├── test_config.py
    ├── test_domain.py
    └── test_logging_utils.py
```

Each file has one responsibility. Later data/strategy/execution modules must consume these contracts rather than invent parallel structures.

---

### Task 1: Python project scaffold and mainnet-only configuration

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `.env.example`
- Create: `src/cocomelon/__init__.py`
- Create: `src/cocomelon/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `ExecutionMode`, `Settings`, `Settings.from_env()`, `Settings.live_activation_valid`.
- Later phases consume `Settings.api_url`, `Settings.ws_url`, and the locked risk fractions rather than duplicating constants.

- [ ] **Step 1: Create project metadata and development tooling**

Create `pyproject.toml`:

```toml
[build-system]
requires = ["setuptools>=75", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "cocomelon-trader"
version = "0.1.0"
description = "Autonomous Hyperliquid mainnet paper-to-live perpetual trading research system"
requires-python = ">=3.12,<3.13"
dependencies = []

[project.optional-dependencies]
dev = [
  "pytest>=8.3,<9",
  "ruff>=0.12,<1",
  "mypy>=1.14,<2",
]

[project.scripts]
cocomelon = "cocomelon.cli:main"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q"

[tool.ruff]
target-version = "py312"
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B"]

[tool.mypy]
python_version = "3.12"
strict = true
packages = ["cocomelon"]
```

Create `.gitignore`:

```gitignore
.venv/
__pycache__/
*.py[cod]
.pytest_cache/
.mypy_cache/
.ruff_cache/
.coverage
htmlcov/
dist/
build/
*.egg-info/
.env
.env.*
!.env.example
data/
logs/
*.sqlite
*.sqlite3
```

Create `.env.example` with no secret fields:

```dotenv
COCOMELON_API_URL=https://api.hyperliquid.xyz
COCOMELON_WS_URL=wss://api.hyperliquid.xyz/ws
COCOMELON_EXECUTION_MODE=paper
# Live mode remains unavailable until later phases. The acknowledgement name is documented now
# so configuration behavior cannot drift silently.
COCOMELON_LIVE_ACK=
```

- [ ] **Step 2: Write failing configuration tests**

Create `tests/test_config.py`:

```python
import pytest

from cocomelon.config import ExecutionMode, Settings


def test_defaults_are_mainnet_and_paper(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "COCOMELON_API_URL",
        "COCOMELON_WS_URL",
        "COCOMELON_EXECUTION_MODE",
        "COCOMELON_LIVE_ACK",
    ):
        monkeypatch.delenv(key, raising=False)

    settings = Settings.from_env()

    assert settings.api_url == "https://api.hyperliquid.xyz"
    assert settings.ws_url == "wss://api.hyperliquid.xyz/ws"
    assert settings.execution_mode is ExecutionMode.PAPER
    assert settings.live_activation_valid is False
    assert settings.risk_per_trade == 0.0025
    assert settings.max_open_risk == 0.0075
    assert settings.daily_loss_limit == 0.01
    assert settings.weekly_drawdown_limit == 0.03


@pytest.mark.parametrize(
    "env_key,url",
    [
        ("COCOMELON_API_URL", "https://api.hyperliquid-testnet.xyz"),
        ("COCOMELON_WS_URL", "wss://api.hyperliquid-testnet.xyz/ws"),
        ("COCOMELON_API_URL", "https://foo.testnet.example"),
    ],
)
def test_testnet_urls_are_rejected(
    monkeypatch: pytest.MonkeyPatch, env_key: str, url: str
) -> None:
    monkeypatch.setenv(env_key, url)
    with pytest.raises(ValueError, match="testnet"):
        Settings.from_env()


def test_live_mode_requires_exact_ack(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COCOMELON_EXECUTION_MODE", "live")
    monkeypatch.setenv("COCOMELON_LIVE_ACK", "yes")
    settings = Settings.from_env()
    assert settings.live_activation_valid is False

    monkeypatch.setenv(
        "COCOMELON_LIVE_ACK", "I_UNDERSTAND_REAL_FUNDS_ARE_AT_RISK"
    )
    settings = Settings.from_env()
    assert settings.live_activation_valid is True
```

- [ ] **Step 3: Run the tests and confirm they fail because config does not exist**

Run:

```bash
python -m pytest tests/test_config.py -q
```

Expected: import failure for `cocomelon.config`.

- [ ] **Step 4: Implement the minimal configuration contract**

Create `src/cocomelon/__init__.py`:

```python
"""Cocomelon autonomous Hyperliquid trader."""

__version__ = "0.1.0"
```

Create `src/cocomelon/config.py`:

```python
from __future__ import annotations

import os
from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import urlparse

MAINNET_API_URL = "https://api.hyperliquid.xyz"
MAINNET_WS_URL = "wss://api.hyperliquid.xyz/ws"
LIVE_ACK = "I_UNDERSTAND_REAL_FUNDS_ARE_AT_RISK"


class ExecutionMode(StrEnum):
    PAPER = "paper"
    LIVE = "live"


def _reject_testnet(url: str) -> str:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if "testnet" in host:
        raise ValueError(f"Hyperliquid testnet is forbidden: {url}")
    return url


@dataclass(frozen=True, slots=True)
class Settings:
    api_url: str = MAINNET_API_URL
    ws_url: str = MAINNET_WS_URL
    execution_mode: ExecutionMode = ExecutionMode.PAPER
    live_ack: str = ""
    risk_per_trade: float = 0.0025
    max_open_risk: float = 0.0075
    daily_loss_limit: float = 0.01
    weekly_drawdown_limit: float = 0.03
    consecutive_loss_cooldown: int = 3

    @classmethod
    def from_env(cls) -> "Settings":
        mode = ExecutionMode(os.getenv("COCOMELON_EXECUTION_MODE", "paper").lower())
        return cls(
            api_url=_reject_testnet(os.getenv("COCOMELON_API_URL", MAINNET_API_URL)),
            ws_url=_reject_testnet(os.getenv("COCOMELON_WS_URL", MAINNET_WS_URL)),
            execution_mode=mode,
            live_ack=os.getenv("COCOMELON_LIVE_ACK", ""),
        )

    @property
    def live_activation_valid(self) -> bool:
        return self.execution_mode is ExecutionMode.LIVE and self.live_ack == LIVE_ACK
```

- [ ] **Step 5: Install and verify Task 1**

Run:

```bash
python -m pip install -e ".[dev]"
python -m pytest tests/test_config.py -q
python -m ruff check src tests
python -m mypy src
```

Expected: all pass.

- [ ] **Step 6: Commit Task 1**

```bash
git add pyproject.toml .gitignore .env.example src/cocomelon/__init__.py src/cocomelon/config.py tests/test_config.py
git commit -m "build: establish mainnet-only Python foundation"
```

---

### Task 2: Shared domain contracts and utilities

**Files:**
- Create: `src/cocomelon/domain/__init__.py`
- Create: `src/cocomelon/domain/market.py`
- Create: `src/cocomelon/domain/strategy.py`
- Create: `src/cocomelon/domain/risk.py`
- Create: `src/cocomelon/domain/execution.py`
- Create: `src/cocomelon/domain/journal.py`
- Create: `src/cocomelon/util/__init__.py`
- Create: `src/cocomelon/util/ids.py`
- Create: `src/cocomelon/util/time.py`
- Test: `tests/test_domain.py`

**Interfaces:**
- Produces: `MarketId`, `Direction`, `StrategySignal`, `RiskDecision`, `OrderSide`, `OrderType`, `OrderIntent`, `Fill`, `Position`, `DecisionRecord`, `new_id()`, `utc_now_ms()`.
- These names become stable contracts for later phases.

- [ ] **Step 1: Write domain-behavior tests first**

Create `tests/test_domain.py`:

```python
import pytest

from cocomelon.domain.execution import OrderIntent, OrderSide, OrderType
from cocomelon.domain.market import MarketId
from cocomelon.domain.strategy import Direction, StrategySignal


def test_market_id_canonicalizes_default_and_named_dex() -> None:
    assert MarketId(dex="", coin="BTC").canonical == "BTC"
    assert MarketId(dex="xyz", coin="XYZ100").canonical == "xyz:XYZ100"


def test_strategy_score_is_bounded() -> None:
    market = MarketId(dex="", coin="SOL")
    with pytest.raises(ValueError, match="score"):
        StrategySignal(
            strategy="trend",
            market=market,
            direction=Direction.LONG,
            score=101.0,
            timestamp_ms=1,
            reasons=("example",),
            invalidation_price=100.0,
        )


def test_no_trade_does_not_require_invalidation() -> None:
    signal = StrategySignal(
        strategy="trend",
        market=MarketId(dex="", coin="ETH"),
        direction=Direction.NO_TRADE,
        score=40.0,
        timestamp_ms=1,
        reasons=("insufficient edge",),
        invalidation_price=None,
    )
    assert signal.direction is Direction.NO_TRADE


def test_opening_order_requires_positive_quantity() -> None:
    with pytest.raises(ValueError, match="quantity"):
        OrderIntent(
            intent_id="intent-1",
            market=MarketId(dex="", coin="BTC"),
            side=OrderSide.BUY,
            quantity=0.0,
            order_type=OrderType.MARKETABLE_IOC,
            reduce_only=False,
            limit_price=None,
            created_at_ms=1,
        )
```

- [ ] **Step 2: Run and verify the tests fail**

```bash
python -m pytest tests/test_domain.py -q
```

Expected: imports fail because the domain package is not implemented.

- [ ] **Step 3: Implement market and strategy contracts**

Create `src/cocomelon/domain/market.py`:

```python
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MarketId:
    dex: str
    coin: str

    def __post_init__(self) -> None:
        if not self.coin.strip():
            raise ValueError("coin must not be empty")

    @property
    def canonical(self) -> str:
        return f"{self.dex}:{self.coin}" if self.dex else self.coin
```

Create `src/cocomelon/domain/strategy.py`:

```python
from dataclasses import dataclass
from enum import StrEnum

from cocomelon.domain.market import MarketId


class Direction(StrEnum):
    LONG = "long"
    SHORT = "short"
    NO_TRADE = "no_trade"


@dataclass(frozen=True, slots=True)
class StrategySignal:
    strategy: str
    market: MarketId
    direction: Direction
    score: float
    timestamp_ms: int
    reasons: tuple[str, ...]
    invalidation_price: float | None

    def __post_init__(self) -> None:
        if not 0.0 <= self.score <= 100.0:
            raise ValueError("score must be between 0 and 100")
        if self.direction is not Direction.NO_TRADE and self.invalidation_price is None:
            raise ValueError("trade signals require invalidation_price")
```

- [ ] **Step 4: Implement risk, execution, and journal contracts**

Create `src/cocomelon/domain/risk.py`:

```python
from dataclasses import dataclass

from cocomelon.domain.market import MarketId
from cocomelon.domain.strategy import Direction


@dataclass(frozen=True, slots=True)
class RiskDecision:
    decision_id: str
    market: MarketId
    direction: Direction
    approved: bool
    reasons: tuple[str, ...]
    risk_budget: float
    approved_notional: float
    stop_price: float | None
    timestamp_ms: int
```

Create `src/cocomelon/domain/execution.py`:

```python
from dataclasses import dataclass
from enum import StrEnum

from cocomelon.domain.market import MarketId


class OrderSide(StrEnum):
    BUY = "buy"
    SELL = "sell"


class OrderType(StrEnum):
    MARKETABLE_IOC = "marketable_ioc"
    LIMIT_GTC = "limit_gtc"


@dataclass(frozen=True, slots=True)
class OrderIntent:
    intent_id: str
    market: MarketId
    side: OrderSide
    quantity: float
    order_type: OrderType
    reduce_only: bool
    limit_price: float | None
    created_at_ms: int

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise ValueError("quantity must be positive")


@dataclass(frozen=True, slots=True)
class Fill:
    fill_id: str
    intent_id: str
    market: MarketId
    side: OrderSide
    price: float
    quantity: float
    fee: float
    timestamp_ms: int


@dataclass(frozen=True, slots=True)
class Position:
    market: MarketId
    signed_quantity: float
    average_entry_price: float
    stop_price: float | None
    realized_pnl: float = 0.0
```

Create `src/cocomelon/domain/journal.py`:

```python
from dataclasses import dataclass

from cocomelon.domain.market import MarketId
from cocomelon.domain.strategy import Direction


@dataclass(frozen=True, slots=True)
class DecisionRecord:
    decision_id: str
    market: MarketId
    direction: Direction
    timestamp_ms: int
    regime: str
    strategy_names: tuple[str, ...]
    approved_by_risk: bool
    reason_codes: tuple[str, ...]
```

Create `src/cocomelon/domain/__init__.py` with no wildcard exports yet.

- [ ] **Step 5: Implement utilities**

Create `src/cocomelon/util/ids.py`:

```python
from uuid import uuid4


def new_id(prefix: str) -> str:
    if not prefix:
        raise ValueError("prefix must not be empty")
    return f"{prefix}_{uuid4().hex}"
```

Create `src/cocomelon/util/time.py`:

```python
from time import time_ns


def utc_now_ms() -> int:
    return time_ns() // 1_000_000
```

Create an empty `src/cocomelon/util/__init__.py`.

- [ ] **Step 6: Verify Task 2**

```bash
python -m pytest tests/test_domain.py -q
python -m ruff check src tests
python -m mypy src
```

Expected: all pass.

- [ ] **Step 7: Commit Task 2**

```bash
git add src/cocomelon/domain src/cocomelon/util tests/test_domain.py
git commit -m "feat: define core trading domain contracts"
```

---

### Task 3: Structured secret-safe logging

**Files:**
- Create: `src/cocomelon/logging_utils.py`
- Test: `tests/test_logging_utils.py`

**Interfaces:**
- Produces: `redact_mapping()` and `configure_logging()` for later services.

- [ ] **Step 1: Write failing redaction tests**

Create `tests/test_logging_utils.py`:

```python
from cocomelon.logging_utils import redact_mapping


def test_redacts_nested_secret_values() -> None:
    payload = {
        "market": "BTC",
        "secret_key": "0xabc",
        "nested": {"agent_private_key": "0xdef", "value": 12},
    }

    redacted = redact_mapping(payload)

    assert redacted["market"] == "BTC"
    assert redacted["secret_key"] == "[REDACTED]"
    assert redacted["nested"]["agent_private_key"] == "[REDACTED]"
    assert redacted["nested"]["value"] == 12
```

- [ ] **Step 2: Run and verify failure**

```bash
python -m pytest tests/test_logging_utils.py -q
```

- [ ] **Step 3: Implement recursive redaction and JSON logging**

Create `src/cocomelon/logging_utils.py`:

```python
from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from typing import Any

SECRET_KEYS = {
    "secret_key",
    "private_key",
    "agent_private_key",
    "authorization",
    "password",
}


def redact_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for key, item in value.items():
        if key.lower() in SECRET_KEYS:
            output[key] = "[REDACTED]"
        elif isinstance(item, Mapping):
            output[key] = redact_mapping(item)
        else:
            output[key] = item
    return output


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        return json.dumps(payload, separators=(",", ":"), sort_keys=True)


def configure_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
```

- [ ] **Step 4: Verify Task 3**

```bash
python -m pytest tests/test_logging_utils.py -q
python -m ruff check src tests
python -m mypy src
```

- [ ] **Step 5: Commit Task 3**

```bash
git add src/cocomelon/logging_utils.py tests/test_logging_utils.py
git commit -m "feat: add secret-safe structured logging"
```

---

### Task 4: Minimal operator CLI and continuous integration

**Files:**
- Create: `src/cocomelon/cli.py`
- Create: `src/cocomelon/__main__.py`
- Create: `tests/test_cli.py`
- Create: `.github/workflows/ci.yml`
- Modify: `docs/STATUS.md`

**Interfaces:**
- Produces: `cocomelon status` operator command.
- The command must show mode/endpoints/risk settings but never secrets.

- [ ] **Step 1: Write failing CLI test**

Create `tests/test_cli.py`:

```python
from cocomelon.cli import status_payload
from cocomelon.config import Settings


def test_status_payload_is_safe_and_explicit() -> None:
    payload = status_payload(Settings())

    assert payload["execution_mode"] == "paper"
    assert payload["api_url"] == "https://api.hyperliquid.xyz"
    assert payload["ws_url"] == "wss://api.hyperliquid.xyz/ws"
    assert payload["live_activation_valid"] is False
    assert payload["risk_per_trade"] == 0.0025
    assert "live_ack" not in payload
```

- [ ] **Step 2: Run and verify failure**

```bash
python -m pytest tests/test_cli.py -q
```

- [ ] **Step 3: Implement CLI**

Create `src/cocomelon/cli.py`:

```python
from __future__ import annotations

import argparse
import json
from typing import Any

from cocomelon.config import Settings


def status_payload(settings: Settings) -> dict[str, Any]:
    return {
        "execution_mode": settings.execution_mode.value,
        "api_url": settings.api_url,
        "ws_url": settings.ws_url,
        "live_activation_valid": settings.live_activation_valid,
        "risk_per_trade": settings.risk_per_trade,
        "max_open_risk": settings.max_open_risk,
        "daily_loss_limit": settings.daily_loss_limit,
        "weekly_drawdown_limit": settings.weekly_drawdown_limit,
    }


def main() -> None:
    parser = argparse.ArgumentParser(prog="cocomelon")
    parser.add_argument("command", choices=("status",))
    args = parser.parse_args()

    if args.command == "status":
        print(json.dumps(status_payload(Settings.from_env()), indent=2, sort_keys=True))
```

Create `src/cocomelon/__main__.py`:

```python
from cocomelon.cli import main

if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Create CI**

Create `.github/workflows/ci.yml`:

```yaml
name: CI

on:
  push:
  pull_request:

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
      - run: python -m pip install --upgrade pip
      - run: python -m pip install -e ".[dev]"
      - run: python -m ruff check src tests
      - run: python -m mypy src
      - run: python -m pytest -q
```

- [ ] **Step 5: Run complete Phase 1 verification**

```bash
python -m pip install -e ".[dev]"
python -m ruff check src tests
python -m mypy src
python -m pytest -q
python -m cocomelon status
```

Expected CLI properties:

- `execution_mode` is `paper`;
- API/WS URLs are mainnet;
- `live_activation_valid` is false;
- risk defaults match the spec;
- no secret acknowledgement value is printed.

- [ ] **Step 6: Update project status with evidence**

After the commands pass, change `docs/STATUS.md` to:

- mark Phase 1 complete;
- record the verification commands and passing result;
- record the final Phase 1 commit SHA;
- set Phase 2 as active;
- point exact next action to the future Phase 2 implementation plan.

Do not mark Phase 1 complete before the verification commands actually pass.

- [ ] **Step 7: Commit Task 4 / Phase 1 completion**

```bash
git add src/cocomelon/cli.py src/cocomelon/__main__.py tests/test_cli.py .github/workflows/ci.yml docs/STATUS.md
git commit -m "ci: complete phase 1 project foundation"
```

---

## Phase 1 self-review checklist

Before declaring completion, confirm all of the following with fresh command output:

- [ ] `python -m ruff check src tests` passes.
- [ ] `python -m mypy src` passes.
- [ ] `python -m pytest -q` passes.
- [ ] `python -m cocomelon status` reports mainnet + paper.
- [ ] testnet URL configuration is rejected by tests.
- [ ] exact live acknowledgement is not exposed by CLI/log output.
- [ ] no live exchange adapter exists yet.
- [ ] no strategy/ML logic was pulled forward into this phase.
- [ ] `docs/STATUS.md` contains verification evidence and the exact next phase.

## Next plan after completion

Write a separate plan for **Phase 2 — Hyperliquid mainnet discovery and REST snapshots**. It should re-check current official Hyperliquid API schemas and rate limits immediately before implementation.