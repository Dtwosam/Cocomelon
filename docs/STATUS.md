# Cocomelon Project Status

**Last updated:** 2026-08-23  
**Repository:** `Dtwosam/Cocomelon`  
**Default branch:** `main`

## Current state

**Active phase:** Phase 1 — Python foundation and domain contracts  
**Last completed phase:** Phase 0 — governance and source-of-truth anchor

## Phase 0 evidence

The repository source-of-truth set is established:

- `README.md`
- `AGENTS.md`
- `docs/MASTER_SPEC.md`
- `docs/DECISIONS.md`
- `docs/BUILD_ORDER.md`
- `docs/STATUS.md`
- `docs/CHATGPT_PROJECT_SOURCE.md`
- `docs/superpowers/plans/2026-08-23-phase-1-foundation.md`

Locked project direction:

- Hyperliquid mainnet data only;
- no Hyperliquid testnet;
- internal paper/shadow trading before live execution;
- autonomous LONG/SHORT/NO_TRADE lifecycle;
- intraday focus, typically ~10 minutes to 6 hours;
- broad market scanner -> dynamic shortlist -> deeper analysis;
- Python primary implementation language;
- no Solidity requirement for V1;
- initial planned risk 0.25% per trade;
- 0.75% aggregate planned open risk;
- 1% daily realized-loss lockout;
- 3% rolling weekly drawdown lockout;
- champion/challenger learning after trustworthy baselines;
- dedicated API/agent wallet only when live mode is eventually promoted.

## Exact next action

Execute `docs/superpowers/plans/2026-08-23-phase-1-foundation.md` from Task 1 onward.

Do not begin strategy code, ML, or live execution before Phase 1 exit criteria pass.

## Phase 1 exit criteria

Phase 1 is complete only when:

- the Python project installs cleanly;
- package/test structure exists;
- core domain contracts are typed and tested;
- runtime config defaults to paper/mainnet;
- known Hyperliquid testnet hosts are rejected;
- live mode requires explicit dual activation in the config model even though no live adapter exists yet;
- structured logging redacts secret fields;
- test/lint/type-check commands pass in CI and locally;
- `docs/STATUS.md` is updated with the final commit and verification evidence.

## Live trading status

**DISABLED.**

There is no approved live execution path yet. The project remains in build/paper infrastructure stages until the later promotion gates in `docs/MASTER_SPEC.md` and `docs/BUILD_ORDER.md` are satisfied.