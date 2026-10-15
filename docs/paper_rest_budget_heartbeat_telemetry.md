# Authenticated PAPER REST budget heartbeat telemetry

This is **observation only**: the existing continuous PAPER worker's authenticated
operational heartbeat now includes \`local_public_rest_budget\`, derived from
its **existing** mainnet \`InfoClient.rest_budget_snapshot()\`.

The snapshot measures the rolling in-process, 60-second request-weight
ledger; it reports required information requests, separate optional
REST shadow requests, unclassified REST reservations, their combined
weight, observed peak utilization, denied shadow requests and the
required-worker priority reserve.

Every actual heartbeat emission path includes the snapshot, including
the initial heartbeat, source-unhealthy status, context-refresh failure
and regular control-loop status. It adds **no HTTP calls** and does not
acquire any request-budget weight. Its value is an atomic local dictionary
from the same original reader object; the ordinary trading subscriptions,
L2 source-gap evidence, account, order and risk logic do not change.

Interpretation: for a default quota limit of 1000 weight per rolling
minute, the 300-weight reservation protects future mandatory requests
against *optional* shadow reservations. A peak near the budget limit
can indicate that co-locating REST shadow activity is unsafe. Baseline
mandatory usage can now be measured on authenticated successor workers
**before** any optional shadow activation.

**Crucial:** this does not observe other processes, runners or services
behind the same public IP/NAT; the snapshot must always retain
\`external_process_ip_weight_verified=false\` and
\`source_or_execution_authority=false\`. Nothing in this read-only
telemetry certifies a safe public IP, a profitable strategy or a
market-data source ready for production.

No activation environment variables are added. The three-market REST
shadow stays **default off** and cannot supply orders or modify signed
exchange-source histories. Source stale/gap windows and strategy
freshness thresholds remain unchanged.

Reference: [tracking issue #1243](https://github.com/Dtwosam/Cocomelon/issues/1243).
