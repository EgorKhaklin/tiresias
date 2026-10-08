# Changelog

Externally observable changes to Tiresias, research software on educational-grade cryptography.
The reasoning behind each change, with its tests, is in its commit message.
Entries use the [Keep a Changelog](https://keepachangelog.com/) groups: Security, Fixed, Added, Changed, Removed.

---

## Unreleased

### Added

- Every `TIRESIAS_*` setting is declared once with its type, range and reader. `tiresias serve` refuses to start on a malformed, out-of-range or unknown setting, or an admin token under 32 characters, and names each one; `tiresias config` prints the effective values; docs/configuration.md is generated from the declaration and a test keeps them equal.

- Pushing a tag `vX.Y.Z` publishes a release: the job checks the tag against the package version, `tiresias --version` and the changelog, runs the unit tests, and attaches the wheel and source distribution with build-provenance attestations.

### Fixed

- A malformed numeric setting, such as `TIRESIAS_PORT=abc`, raised a traceback on every command at import; it is now reported by name and the default is kept.

## v1.0.0 - 2026-10-07 (development resumes under the Tiresias name)

### Added

- Commit a dataset locally and publish only its manifest; ask `SUM`, `COUNT`, `AVG`, `MIN`, `MAX` and `GROUP BY` questions with filters, each answered with a proof from the Glass engine.
- Two verification tiers, always labeled: binding to the published commitment (anyone, no data) and reproducible soundness (with the data).
- A multi-tenant registry that never sees a row: API keys, tenant isolation, rate limits, an audit log, Prometheus metrics, and a public verification link that needs no account.
- A local prover and registry client, so proving runs where the data lives; an embeddable SDK; a container image for the registry.

### Changed

- The package, command and settings are named `tiresias`: `python -m tiresias.demo`, the `tiresias` command, `TIRESIAS_*` environment variables, `~/.tiresias/registry.db`, `tir_live_` API keys, `tiresias_*` metrics.
- The README states what each verification tier guarantees today, next to the limits.

### Removed

- The witness-free verification spike and the investor pitch; both remain in the git history.

### Fixed

- The proving field was described as Baby Bear; the query path uses the 31-bit prime 2^31 − 1.
- The test suite wrote its registry database into the home directory; it uses a temporary directory.
