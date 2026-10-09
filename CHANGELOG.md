# Changelog

Externally observable changes to Tiresias, research software on educational-grade cryptography.
The reasoning behind each change, with its tests, is in its commit message.
Entries use the [Keep a Changelog](https://keepachangelog.com/) groups: Security, Fixed, Added, Changed, Removed.

---

## Unreleased

### Security

- The public shared-answer page wrote a bundle's query, the organization name and the dataset name into the page as HTML, and the registry stored any query a tenant uploaded. A tenant could publish a link whose page ran script on the registry's origin and read the API key the console kept in `localStorage`. Pages now build every node as text, every response carries a Content-Security-Policy that forbids inline script, the registry refuses queries that are not Tiresias SQL over the bundle's own columns and names with markup, and the console keeps the key for the tab only.

### Added

- `tiresias app`, the workbench, for the data holder's machine: commit a CSV with detected column types and a chosen minimum cohort, build questions without writing SQL (or write it), see each answer with its cohort and withheld groups, verify it, run a tamper test, and download the proof.

### Changed

- The registry's landing page, console and shared-answer page are redesigned in the house style (Cinzel capitals, the meander rule, the oracle-bronze accent, light and dark), on one design system shared with the workbench. The proofs' status is stated once, in plain words, where it applies.
- The registry refuses a bundle whose query names a column its dataset does not have.

## v1.0.0 - 2026-10-08 (development resumes under the Tiresias name)

### Added

- Commit a dataset locally and publish only its manifest; ask `SUM`, `COUNT`, `AVG`, `MIN`, `MAX` and `GROUP BY` questions with filters, each answered with a proof from the Glass engine.
- Two verification tiers, always labeled: binding to the published commitment (anyone, no data) and reproducible soundness (with the data).
- A multi-tenant registry that never sees a row: API keys, tenant isolation, rate limits, an audit log, Prometheus metrics, and a public verification link that needs no account.
- A local prover and registry client, so proving runs where the data lives; an embeddable SDK; a container image for the registry.
- Every `TIRESIAS_*` setting is declared once with its type, range and reader. `tiresias serve` refuses to start on a malformed, out-of-range or unknown setting, or an admin token under 32 characters, and names each one; `tiresias config` prints the effective values; docs/configuration.md is generated from the declaration and a test keeps them equal.
- Every answer carries a proven count of the rows it describes. A dataset declares a minimum cohort at commit (`--min-cohort`, default 5, part of the dataset id); a query about fewer rows is refused, a `GROUP BY` group below it is suppressed and listed by label, and the registry rejects any bundle that breaks the policy.
- Tiresias pins the Glass release it proves with, by tag and by the SHA-256 of the two Glass files it reads; it fetches that release on first use, refuses a checkout that differs and names the files, and loads the verified interpreter by path. `tiresias glass` shows the pin and the checkout; CI fetches the pinned Glass and runs the engine round trip.
- Pushing a tag `vX.Y.Z` publishes a release: the job checks the tag against the package version, `tiresias --version` and the changelog, runs the unit tests, and attaches the wheel and source distribution with build-provenance attestations.

### Security

- A negative `Content-Length` passed the registry's size check and became an unbounded read; it, a non-numeric length, and a body that is not a JSON object are rejected with 400.
- An unhandled registry error returned its exception text to the client; the client now gets an error id, and the trace is logged under it.
- Public share lookups and admin routes are rate-limited per client address; before, only authenticated routes were limited.
- Dataset and bundle ids must be 1 to 128 letters, digits or underscores.

### Changed

- The package, command and settings are named `tiresias`: `python -m tiresias.demo`, the `tiresias` command, `TIRESIAS_*` environment variables, `~/.tiresias/registry.db`, `tir_live_` API keys, `tiresias_*` metrics.
- The README states what each verification tier guarantees today, next to the limits.

### Removed

- The witness-free verification spike and the investor pitch; both remain in the git history.

### Fixed

- Reproducible verification of an `AVG` re-proved its sum but not its count, so a bundle with a consistently forged count and average passed; the count is now re-proved.
- The demo, the registry landing page and the web UI called each answer's proof zero-knowledge; a bundle carries the proof's verdict bound to the commitment, and checking the proof itself still needs the data.
- The proving field was described as Baby Bear; the query path uses the 31-bit prime 2^31 − 1.
- The test suite wrote its registry database into the home directory; it uses a temporary directory.
- A malformed numeric setting, such as `TIRESIAS_PORT=abc`, raised a traceback on every command at import; it is now reported by name and the default is kept.
