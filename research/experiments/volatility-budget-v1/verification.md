# Inactive volatility binding verification

Reviewed source bytes are pinned in `independent-review.md`; original frozen policy SHA256 remains `eca2816e42a1a0409737e179b45761a8a4ad0ebb2149ee7ad956b6867caffdaa`.

- Root focused run:107testsPASS (76policy+31lifecycle).
- Independent relevant regression run:245testsPASS.
- Configured research selection from `.github/workflows/ci.yml`:1855PASS across253testfiles.
- Complete local macOS suite:5807collected;5805PASS,1SKIP,1pre-existing platform-specific failure. `test_stale_session_summary_retirement_is_idempotent_and_fail_closed` expectsLinux `IsADirectoryError`;macOS returns `PermissionError` for unlinking a directory. No ordinary-worker code/test was changed to hide this failure. Full/researchLinuxCI at the exact PR head remains mandatory before merge.
- Full repository Ruff checkPASS, mypy575modulesPASS, compileallPASS; all4newsource/testfilesformatPASS and `git diff --check`PASS.
- Source/testSHA256 matches independentreview; frozenflow/collateral code/protocol and ordinaryruntime are not modified. Newtestfiles are explicitly included in researchCI.

These are synthetic behavior/static checks. There is no operational source/account/restart certification, no activation receipt and no prospective return. See `resource-verdict.md` for the exact independent owner/egress/custody blocker. The future activation receipt must independently bind exact releaseSHA, retained account/source identities and a00:00:30UTCfirst-entry boundary at least6hoursafterrelease. None is assigned now.
