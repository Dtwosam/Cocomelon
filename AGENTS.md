# AGENTS.md — Cocomelon Repository Rules

This file is mandatory reading for every coding agent, assistant, or human contributor before changing the repository.

## 1. Source-of-truth hierarchy

When instructions conflict, use this order unless the user explicitly overrides it in the current conversation:

1. Current explicit user instruction.
2. `AGENTS.md`.
3. `docs/MASTER_SPEC.md`.
4. `docs/DECISIONS.md`.
5. `docs/BUILD_ORDER.md`.
6. The active phase plan under `docs/superpowers/plans/`.
7. `docs/STATUS.md` for current progress/state.
8. Older implementation notes, comments, issues, or chat history.

`docs/CHATGPT_PROJECT_SOURCE.md` is a portable bootstrap summary for new ChatGPT conversations. It must stay consistent with the authoritative repo docs, but newer repo docs win if the portable copy is stale.

## 2. Mission

Build an autonomous Hyperliquid perpetual-futures trader that:

- observes real Hyperliquid mainnet markets;
- scans a broad eligible perp universe;
- ranks opportunities;
- decides LONG, SHORT, or NO TRADE;
- sizes and approves risk independently of strategy conviction;
- manages positions and exits automatically;
- records every decision and result;
- evaluates strategies with realistic costs;
- learns only through validated champion/challenger promotion;
- eventually trades real capital only after explicit promotion gates pass.

The system is intended to pursue positive risk-adjusted net expectancy. Profit is never assumed or guaranteed.

## 3. Hard invariants

These rules may not be silently weakened.

### Network and market data

- Hyperliquid testnet is forbidden. Do not add testnet endpoints, testnet keys, testnet fixtures that pretend to be live validation, or testnet deployment steps.
- Runtime market observations come from Hyperliquid **mainnet**.
- Paper trading uses real mainnet observations with simulated execution.
- Code must reject known Hyperliquid testnet URLs in runtime configuration.
- Historical microstructure/order-book behavior must not be fabricated from OHLCV candles.

### Execution safety

- Default execution mode is `paper`.
- Live trading must require an explicit configuration switch plus an explicit environment acknowledgement. A single accidental flag must not enable live trading.
- The live runtime must never require the master wallet private key. Use a dedicated Hyperliquid API/agent wallet when live execution is eventually enabled.
- Secrets belong in environment variables or local secret stores, never Git, examples, logs, fixtures, screenshots, or telemetry.
- The execution adapter exposed to the trading engine must not expose transfer or withdrawal functions.
- A stale-data, inconsistent-state, or execution-health failure must fail closed: no new exposure.

### Risk

Initial V1 defaults:

- planned account risk per trade: **0.25%**;
- maximum aggregate planned open risk: **0.75%**;
- maximum realized daily loss before lockout: **1.00%**;
- maximum rolling weekly drawdown before lockout: **3.00%**;
- three consecutive losing trades trigger a cooldown;
- no averaging down into losing positions;
- no martingale sizing;
- no position without a defined invalidation/stop;
- correlated positions must be treated as shared risk, not independent bets;
- leverage is an implementation of notional exposure, not the definition of risk.

A planned 0.25% risk is a target, not a promise: gaps/slippage can create larger realized loss. Simulation and reporting must reflect this.

### Strategy and learning

- NO TRADE is a first-class valid outcome.
- V1 must establish deterministic, explainable baselines before ML controls live decisions.
- Do not optimize primarily for win rate.
- Evaluation must include net expectancy after fees/funding/slippage, drawdown, profit factor, and risk-adjusted performance.
- Every model change is a challenger. It may not replace the champion until it passes reproducible out-of-sample and walk-forward tests plus mainnet shadow validation.
- Never retrain and immediately deploy a model into live money automatically.

## 4. Engineering approach

- Primary language: Python.
- V1 does not need Solidity. HyperCore perp trading is accessed through Hyperliquid APIs/SDK; Solidity is introduced only if a later, explicit HyperEVM contract requirement justifies it.
- Prefer small focused modules and explicit interfaces.
- Use type hints throughout core logic.
- Use deterministic pure functions for feature, strategy, risk, and accounting calculations wherever possible.
- Keep market-data ingestion separate from trading decisions.
- Keep strategy decisions separate from risk approval.
- Keep paper and live execution behind the same execution interface.
- Keep operational state/trade journal separate from high-volume raw market data.
- SQLite is appropriate for control state, decisions, orders, fills, positions, and journal metadata. Columnar files such as Parquet are preferred for high-volume market events/features.

## 5. Development process

For every phase:

1. Read `docs/STATUS.md` and the active plan.
2. Confirm the previous phase's exit criteria are actually satisfied.
3. Write/adjust tests before implementation where practical.
4. Build the smallest complete slice that satisfies the phase.
5. Run the relevant unit/integration tests.
6. Run formatting/type/static checks configured in the repo.
7. Verify no secret or live-trading escape hatch was introduced.
8. Update `docs/STATUS.md` with evidence: tests, commit, completed criteria, active next phase.
9. Update `docs/DECISIONS.md` only when a real architectural/product decision changes.
10. Commit coherent changes with descriptive messages.

Do not skip phases merely because a later feature is more interesting.

## 6. Data integrity rules

Every persisted market event or derived feature must preserve enough provenance to answer:

- source;
- market identifier;
- exchange timestamp where available;
- receive timestamp;
- schema version;
- whether it was raw, normalized, or derived.

Backtests must prevent lookahead bias. Feature values at decision time may use only information available at or before that timestamp.

If data is missing or stale, record the gap. Do not interpolate order books/trades into fake certainty.

## 7. Market-universe rules

The architecture must support multiple Hyperliquid perp DEX namespaces via a canonical market key. Initial paper-trading support may be phased, but market discovery must not hard-code a small list of favorite coins.

A market becomes trade-eligible only after passing configurable checks such as:

- active/not delisted;
- sufficient notional volume;
- sufficient open interest;
- acceptable spread;
- acceptable visible depth;
- usable mark/mid/oracle data;
- supported margin semantics;
- data freshness.

Ranking opportunity is separate from eligibility. A bad-quality market cannot become tradable merely because its momentum score is high.

## 8. Documentation discipline

`docs/MASTER_SPEC.md` describes what the system is.

`docs/BUILD_ORDER.md` describes the approved construction sequence.

`docs/STATUS.md` describes where the repo is now.

Phase plans describe exactly how the next approved slice is implemented.

When implementation reveals a spec contradiction, stop and resolve the contradiction in the docs rather than silently coding around it.

## 9. Current official references

Use official Hyperliquid documentation as the primary external reference:

- API: https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api
- Info endpoints: https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint
- Perpetual info: https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint/perpetuals
- WebSocket: https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket
- WebSocket subscriptions: https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket/subscriptions
- Rate limits: https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/rate-limits-and-user-limits
- Exchange endpoint: https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/exchange-endpoint
- Nonces/API wallets: https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/nonces-and-api-wallets
- Official Python SDK: https://github.com/hyperliquid-dex/hyperliquid-python-sdk

Re-check current docs before implementing behavior that Hyperliquid can change.