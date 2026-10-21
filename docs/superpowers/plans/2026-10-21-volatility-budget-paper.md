# Frozen volatility-budget PAPER binding

> Execute the owner's October 21 activation request; ordinary worker unchanged.

**Goal:** Make the existing frozen volatility-budget hypothesis executable in isolated PAPER accounts, and activate only if independent operational safety is actually verified.

**Architecture:** A policy-specific pure decision module and durable account lifecycle reuse existing PAPER IOC, risk, fees, funding and accounting. Preserve the flow-specific core and its identity. No generalized runner or ordinary-worker changes.

**Authoritative specification:** `research/experiments/volatility-budget-v1/policy.json`, byte-for-byte copy of the locally frozen policy, SHA256 `eca2816e42a1a0409737e179b45761a8a4ad0ebb2149ee7ad956b6867caffdaa`. Earlier documentation that forbids this binding is superseded by the current explicit owner instruction. No policy parameters or historical outcomes change.

**Global constraints:** PAPER only; no paid resources, loss reset, PR1392 activation, ordinary runtime restart/duplicate, fabricated source, retiming, or reduced safety. No operational account genesis before resource/custody admission. Release requires a prospective daily first-entry boundary at least six hours later. Exploratory safety and economic validation are separate.

## Tasks

1. Verify current Issue469 account/run/SHA, Issue1258 permanent mandate, main/open PRs and frozen bytes. Preserve existing historical evidence.
2. Test then implement exact native8h-to-daily signal, ratios, daily clock, reference geometry and costs. Missing data remains UNKNOWN. Independent arithmetic and both crossing tests.
3. Test then implement separate durable candidate/control lifecycle: daily attempt, all-signal cooldown, risk, delayed IOC, stop/target/time intents, partial/no-fill retries, restart identity/history and hourly/post-close funding.
4. In parallel inspect existing free source, process, IP-wide quota and durable custody. No new infrastructure. If verified ownership/service cannot meet the frozen contract, retain inactivity and stop deployment work.
5. Independent adversarial review, relevant tests, compile/Ruff/mypy and full/research exact-head CI. Merge only reviewed coherent code after both suites pass, then verify merged head.
6. Only if every independent operational admission requirement passes, produce immutable exact-SHA activation receipt and activate using verified existing controls. Otherwise no receipt, operational accounts or entry boundary; report the exact remaining blocker.

## Review focus

Original receipt clocks and unfinished bars; previous/current windows; exact rational thresholds; eligibility before canonical selection; rejected signals consume cooldown; attempted daily batch cannot chase; fixed geometry; actual fill time; durable fresh-book reductions; ambiguous commit/restart; hourly boundary position/oracle before fills; late funding; candidate/control anti-reset/alias/lease; loss suspension survives recovery; LIVE impossible; operational isolation is evidence, not a boolean.

## Verification

Focused new policy/lifecycle tests, existing flow/paper/funding/risk regression tests, configured research suite and complete Linux CI at the exact PR head. Verify policy SHA before and after. Synthetic tests establish behavior only, not source reliability, activation or profitability. Record failures and blockers honestly.
