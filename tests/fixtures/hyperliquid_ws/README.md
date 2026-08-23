# Hyperliquid Mainnet WebSocket Fixtures

These six fixtures are exact public responses captured from Hyperliquid mainnet by the temporary Phase 3 network-smoke workflow. They are regression anchors for the wire protocol and are not synthetic examples.

## Capture provenance

- Mainnet WebSocket: `wss://api.hyperliquid.xyz/ws`
- Workflow run: `32650798749`
- Workflow artifact: `9496120799` (`phase3-mainnet-ws-fixtures`)
- Artifact ZIP SHA-256: `a5720f2012ce696536fa437d9c9102e996e098d0d98fa949c05402f88d515e88`
- Feature-branch fixture commit: `8cabafe0425a3f44ee8f09a9a704360038e1266c`
- HIP-3 sample discovered during capture: DEX `xyz`, market `xyz:XYZ100`

The workflow first ran the bounded read-only `cocomelon stream-smoke --seconds 5 --market BTC` command successfully, then captured native and HIP-3 public response shapes. No wallet, user/account stream, signing key, order, or `post` action was used.

## Exact fixture hashes

| Fixture | SHA-256 |
| --- | --- |
| `all_mids_native.json` | `2cbef45a82ce2bc9ddeb2eb5aaf0b1a8e048cef872a57429d85f2c510098bd8f` |
| `all_mids_hip3.json` | `e461134887e4eddca47723c53448e965cf7f09045eea25baf6688444369550f6` |
| `l2_book_btc.json` | `3b4d7c2093438f40725b59f58128339568564ed1c668ad24950850fd9ac8e2ad` |
| `l2_book_hip3.json` | `31bad51e19de6f2ef06f2137f3947faa73bf49d5a05a2bd35afa6b9afd2e6be7` |
| `trades_btc.json` | `e669d90d3469f5b5b0431b3e5efdd836b45529b72fa4352a463eaa588373df0f` |
| `candle_btc_1m.json` | `f20e41b78781eaa36c6cf929da58c511951f40b5e83a3a31c8ab9248a5c56873` |

`tests/test_ws_fixtures.py` verifies these hashes before exercising normalization contracts, so fixture mutation is explicit rather than silent.
