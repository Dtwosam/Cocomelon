# Research dashboard catch-up retry hardening

## Goal
Prevent the five-minute research dashboard catch-up dispatcher from repeatedly dispatching after a failed dashboard attempt for the same trusted source state.

## Constraints
- Do not modify frozen V4 acquisition, strategy, risk, execution, curator, corpus, schedule, or economics.
- Do not read research artifacts or economic state in the catch-up dispatcher.
- Keep dashboard hourly scheduling as the fallback retry mechanism.

## TDD
1. Add a regression assertion that any completed dashboard attempt newer than the trusted source suppresses another catch-up dispatch.
2. Verify RED with the current success-only dashboard query.
3. Remove the dashboard success-only conclusion filter and update the no-op message.
4. Verify exact-head compile, Ruff, mypy, full pytest, and research CI.
5. Merge only after a clean exact-head PR gate and review scan.
