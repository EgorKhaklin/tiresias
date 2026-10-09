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
| `TIRESIAS_PROVER` | prover | (empty) | The tiresias-prover binary, which proves and verifies. Empty means zkvm/target/release in this checkout, then PATH. The registry needs it too, to verify receipts. |
| `TIRESIAS_OPENINGS` | prover | `~/.tiresias/openings` | Where each dataset's opening (the salt of its commitment) is kept, readable only by you. Without it, no answer over that dataset can be proved. |
| `TIRESIAS_REGISTRY_URL` | client | (empty) | Registry the client talks to. Empty means http://HOST:PORT. |
| `TIRESIAS_API_KEY` | client | (empty) | The client's API key. |
