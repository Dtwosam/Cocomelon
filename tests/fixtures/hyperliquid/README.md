# Hyperliquid Phase 2 public mainnet fixtures

Captured from the public Hyperliquid mainnet /info endpoint on 2026-08-23.

- GitHub Actions smoke run: 32648062082
- Commit observed: 76712c692e4689a3e6f91d0be5b21d9efcbbb10c
- API base: https://api.hyperliquid.xyz/info
- metaAndAssetCtxs fixture sample size: 3 aligned markets/contexts
- Requests: perpDexs, native metaAndAssetCtxs, first discovered HIP-3 metaAndAssetCtxs, BTC 15m candleSnapshot (~6h), BTC fundingHistory (~72h)

Public read-only data only. No user address, account state, wallet key, signature, order, or private endpoint is queried.
