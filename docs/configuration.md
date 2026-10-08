# Configuration

Every setting is an environment variable. This page is generated from `tiresias/config.py`;
a test fails if the two disagree. `tiresias config` prints the effective values.
`tiresias serve` refuses to start while any registry setting is malformed, out of range,
or unknown, and names each problem.

| Variable | Read by | Default | Meaning |
|---|---|---|---|
| `TIRESIAS_HOST` | registry | `127.0.0.1` | Address the registry binds to. |
| `TIRESIAS_PORT` | registry | `8765` | Port the registry listens on. Range 1 to 65535. |
| `TIRESIAS_DB` | registry | `~/.tiresias/registry.db` | The registry's SQLite database. |
| `TIRESIAS_ADMIN_TOKEN` | registry | (empty) | Bearer token for the admin API. Empty disables the admin API; when set, at least 32 characters. |
| `TIRESIAS_MAX_BODY_BYTES` | registry | `2097152` | Largest request body the registry accepts. Range 1024 to 67108864. |
| `TIRESIAS_RATE_PER_MIN` | registry | `240` | Requests per minute per API key; 0 disables limiting. Range 0 to 100000. |
| `TIRESIAS_PAGE_SIZE` | registry | `50` | Default page size for list endpoints. Range 1 to 10000. |
| `TIRESIAS_MAX_PAGE_SIZE` | registry | `500` | Largest page size a client may ask for; at least PAGE_SIZE. Range 1 to 10000. |
| `TIRESIAS_LOG_LEVEL` | registry | `INFO` | One of DEBUG, INFO, WARNING, ERROR, CRITICAL. |
| `TIRESIAS_GLASS_DIR` | prover | (empty) | A Glass checkout to prove with. Empty means the pinned release, fetched to ~/.tiresias/glass/<tag> on first use. Either way it must match the pinned files. |
| `TIRESIAS_GLASS_UNPINNED` | prover | `0` | 1 lets the prover use a Glass checkout that differs from the pinned files (development only). Range 0 to 1. |
| `TIRESIAS_GAMMA` | prover | `918273645` | Public Fiat-Shamir point for dataset commitments. Keep it fixed for a dataset's lifetime. Range 2 to 2147483646. |
| `TIRESIAS_REGISTRY_URL` | client | (empty) | Registry the client talks to. Empty means http://HOST:PORT. |
| `TIRESIAS_API_KEY` | client | (empty) | The client's API key. |
