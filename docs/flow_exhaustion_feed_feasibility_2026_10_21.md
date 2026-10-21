# Flow-exhaustion feed feasibility — 2026-10-21

**BLOCKED FOR SAFETY. No provider feed, experimental market collector, or candidate entries were activated. No purchase or provider contact was made.** The frozen economic protocol remains SHA256 `c248746bbe4cd36fa63233b32bd643e368f2d20c63b0e973cf39ffd515873057`; thresholds, native broad-universe eligibility, costs, stops and risk limits must remain unchanged.

## What is actually available

Authenticated repository Actions inspection found the expected `QUICKNODE_HYPERCORE_GRPC_ENDPOINT` and `QUICKNODE_HYPERCORE_GRPC_TOKEN` secrets absent; local `GRPC_ENDPOINT` and `AUTH_TOKEN` were also absent. Repository self-hosted runners: **0**. No usable independently authenticated existing feed/fan-out or owned research egress was established. These findings do not claim that the owner has no provider account elsewhere.

At 10:17:50 UTC, [Issue #469](https://github.com/Dtwosam/Cocomelon/issues/469) identified ordinary worker **39572026775**, head `528c10e071c808dd8c305822a2a378ad17e7bb9f`, predecessor **39543863546**. Its actual trader step was in progress after successful exact restore. Original source capture failed `original_received_clock_regression`, with **946,204 dropped observations**. Its process-local REST weight was 262/1000, observed peak 1000/1000, reserved mandatory weight 300; other same-public-IP consumers remained **unverified**. A second local quota or separate hosted VM does not prove exclusive public egress. [GitHub runner/IP documentation](https://docs.github.com/en/actions/reference/runners/github-hosted-runners#ip-addresses) and [Hyperliquid per-IP limits](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/rate-limits-and-user-limits).

Prior independent authenticated 20×20 public-WS receipts across 20 markets measured median distinct-book interval **5,365.53ms**, p95 5,555.94ms, max5,674.46ms. That historical sample cannot satisfy the frozen≤2s book-gap contract. Fast 5-level data are ineligible. Three-market 1Hz REST previously worked diagnostically at 360 weight/minute, but is neither broad-universe coverage nor current shared-IP safety proof. [Original receipt audit](https://github.com/Dtwosam/Cocomelon/issues/1235#issuecomment-6179482205), [REST diagnostic](https://github.com/Dtwosam/Cocomelon/issues/1235#issuecomment-6179647893).

## Affordable existing services

Prices checked against current provider documentation; capabilities below are **provider claims, not measured acceptance evidence**.

| Service | Recurring published cost | Practical assessment |
| --- | --- | --- |
| HyperliquidRPC Ultra | **$200/month**; 500GB/day included | Advertises unlimited streams/coin filters, per-block 1–100-level L2, trades and `/info`. Best bounded candidate for an evaluation key. Pro $100 has 25-coin/25-stream caps and may restrict the frozen universe. [Pricing](https://hyperliquidrpc.com/pricing) |
| QuickNode Build | **$49/month**, 80M credits; monthly overage$0.62/M | Paid HyperCore access with 5 concurrent streams. L2 requires one coin/stream, leaving at most 4 book streams if one trade stream is used. **Probe floor, not broad-universe launch price.** L2 bills 10 credits/0.0165MB. [Pricing](https://www.quicknode.com/pricing), [HyperCore limits](https://www.quicknode.com/docs/hyperliquid/pricing) |
| Dwellir Order Book | **$199/month add-on + API plan + usage** | Claims 20–100-level WS books and trades; each streamed message costs 1 credit. Broad per-block traffic may materially exceed the base price. [Pricing](https://www.dwellir.com/docs/hyperliquid/pricing) |

## Smallest next step

Obtain an authorized read-only **HyperliquidRPC Ultra evaluation key** before paying for a month. No current credential or prospective sample proves it works here. Measure≤1s latest receipt/exchange ages,≤2s book gaps, native precision, complete native eligible coverage, funding, durable source gaps, actual bytes/day and owned-host resource limits.

Its trade surface contains **per-account fills**, not automatically canonical matched prints. Verify native `(block/time,coin,tid)` identity, aggressor direction, `crossed` role and multiple-maker folding; never count both counterparties as additional pressure. Its advertised QuickNode-compatible L2 docs describe different field names/time representations, so actual proto/message compatibility requires examination. [Trade semantics](https://hyperliquidrpc.com/docs/streams/trades), [L2 schema](https://hyperliquidrpc.com/docs/streams/l2-book), [QuickNode L2](https://www.quicknode.com/docs/hyperliquid/grpc-api/StreamL2Book).

Provider provenance must stay truthful: do not label third-party frames `hyperliquid-mainnet-ws` merely to pass the current validator. A reviewed source-admission seam must preserve the original protocol/hash and economic rules. No published uptime claim establishes this trial's timing/completeness contract. **$200 is the candidate feed price, not a verified all-in quote**; hosting and measured overage remain unknown.

## Budget and bounded acceptance

A planning example is **$224/month before storage, usage overage and taxes**:
$200 feed plus a $24/month DigitalOcean Basic VM (2 vCPU, 4GiB RAM, 80GiB SSD).
The VM price is a published example, not evidence that its CPU, disk or location
can satisfy this stream. Each bundled Droplet has its own public IPv4; actual
outbound routing/ownership still needs verification. Inbound transfer is free.
[Host pricing](https://www.digitalocean.com/pricing/droplets). An existing suitable
owned host could avoid that $24. No VM or subscription was provisioned.

Ultra publishes $0.06/GB stream egress overage beyond the included allowance.
Actual archive storage is not priced yet: retaining all required original
observations for 14 days needs measured compressed bytes/day × 14 plus headroom;
500GB/day is the service allowance, **not** a measured archive rate. A reliable
all-in quote is unavailable until that bounded measurement. Do not buy a month or
build a collector around an unexamined schema.

The next decision needs exactly (1) authorized read-only evaluation access;
(2) an identified host and outbound-IP/resource owner; and (3) an initial
60-minute raw sample across the native eligible universe, including real market
activity, with original receipt clocks. This is a source-contract and cost probe,
not economic evidence or the 72-hour validation period. Check full-depth
precision/coverage, canonical aggressor prints, exchange/receipt ages and gaps,
funding, reconnect/gap recording, CPU/disk lag and bytes/day. Any incompatible
semantics or frozen-quality violation leaves entries closed. Only after this
passes should the one provider adapter and immutable activation receipt be built.
No generalized feed service or self-hosted Hyperliquid node is justified.
