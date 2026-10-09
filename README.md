<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/tiresias-dark.svg">
  <img src="assets/tiresias-light.svg" width="100%" alt="Tiresias: verifiable private analytics">
</picture>

**Answers from data you never reveal. Every aggregate carries a proof that it is true. Never a row.**

[![CI](https://img.shields.io/github/actions/workflow/status/EgorKhaklin/tiresias/ci.yml?branch=main&label=CI&labelColor=1f2328&color=59636e&style=flat-square)](https://github.com/EgorKhaklin/tiresias/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/EgorKhaklin/tiresias?label=release&labelColor=1f2328&color=59636e&style=flat-square)](https://github.com/EgorKhaklin/tiresias/releases/latest)
[![Built on Glass](https://img.shields.io/badge/built_on-Glass-59636e?labelColor=1f2328&style=flat-square)](https://github.com/EgorKhaklin/Glass)
[![Status](https://img.shields.io/badge/status-research,_educational_crypto-9a6b2f?labelColor=1f2328&style=flat-square)](#status)
[![License](https://img.shields.io/badge/license-Apache--2.0-59636e?labelColor=1f2328&style=flat-square)](LICENSE)

</div>

<picture><source media="(prefers-color-scheme: dark)" srcset="assets/rule-dark.svg"><img src="assets/rule-light.svg" width="100%" alt=""></picture>

Tiresias was the seer of Thebes who knew the truth without seeing it. That is what this asks of its reader.

A data holder commits a sensitive dataset and publishes only the commitment. Anyone may then ask an aggregate question of it: a sum, a count, an average, a minimum, a breakdown by group. The answer comes back bound to that commitment, with a proof that it is the true result of the query over the committed rows. The rows never leave the holder's machine.

- **Share a number, not the data.** Report an aggregate to a regulator, contribute to an industry benchmark, or answer a partner's question, without handing over a single record.
- **The registry never sees a row.** Proving runs where the data lives. The registry stores commitments and proofs, checks them, and serves a public link that needs no account.
- **Nothing is taken on the holder's word.** A forged answer is rejected, and an answer cannot be moved onto different data than the data that was committed.

<picture><source media="(prefers-color-scheme: dark)" srcset="assets/rule-dark.svg"><img src="assets/rule-light.svg" width="100%" alt=""></picture>

## Try it

Tiresias is pure standard library and proves with [Glass](https://github.com/EgorKhaklin/Glass). It pins the Glass release it was tested against, by tag and by the SHA-256 of every Glass file it reads, fetches that release on first use (with `git`), and refuses to prove with any other.

```bash
git clone https://github.com/EgorKhaklin/tiresias && cd tiresias
pip install -e .                       # Python 3.12; installs the `tiresias` command
tiresias glass --fetch                 # fetch and verify the pinned Glass
tiresias app                           # the workbench: http://127.0.0.1:8765
```

The workbench runs on the machine that holds the data and never sends a row anywhere. Drop in a CSV and it detects each column's type; choose the minimum cohort and commit. Then build a question (a total, count, average, lowest or highest value, with conditions and a breakdown) without writing SQL, or write the SQL yourself. Each answer comes back with the number of rows it describes, any groups withheld for being too small, and its verification checks; a tamper test shows a forged answer failing, and the proof downloads as a bundle anyone can check.

For the same flow in a terminal, `python3.12 -m tiresias.demo` commits a payroll, proves `AVG(salary) WHERE dept = 'eng'`, verifies the answer against the public commitment without the data, and rejects a forged answer.

### The registry, in five commands

```bash
export TIRESIAS_ADMIN_TOKEN=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')
tiresias serve                                              # 1. run the registry
tiresias create-org "Acme Health"                           # 2. a tenant and its API key
TIRESIAS_API_KEY=tir_live_... tiresias remote-commit payroll.csv --types "dept=category,remote=bool"
                                                            # 3. commit locally, upload the manifest
tiresias remote-query <dataset_id> "SELECT SUM(salary) GROUP BY dept" --data payroll.csv
                                                            # 4. prove locally, upload the proof
tiresias share <bundle_id>                                  # 5. a public link: /v/<token>
```

### What you can ask

```sql
SELECT SUM(salary)   WHERE dept = 'eng'
SELECT COUNT(*)      WHERE remote = 'true'
SELECT AVG(salary)   WHERE level > 3            -- proven as a sum and a count
SELECT MIN(level)    WHERE dept = 'eng'
SELECT MAX(level)
SELECT dept, SUM(salary) GROUP BY dept          -- each group proven
```

Filters: `=`, `!=`, `<`, `>`, `<=`, `>=`, joined by `AND` and `OR`. Columns are integers, booleans, or categories (labels mapped to codes in the public manifest).

Every answer carries a proven count of the rows it describes, its cohort. A dataset declares a minimum cohort when it is committed (`--min-cohort`, default 5): a query about fewer rows is refused, and a `GROUP BY` group below it is suppressed and listed by label only. The policy is part of the dataset's id, so it cannot be loosened quietly.

<picture><source media="(prefers-color-scheme: dark)" srcset="assets/rule-dark.svg"><img src="assets/rule-light.svg" width="100%" alt=""></picture>

## What a proof buys you today

| Tier | Who can check | Needs the data | What it guarantees |
|---|---|---|---|
| 1. Binding | Anyone, from the public link | No | The answer is tied to the published commitment and cannot be moved onto other data |
| 2. Soundness | The data holder, or anyone the holder trusts with the data | Yes | Re-running the proof accepts the stated answer and rejects any other |
| 3. Witness-free | Anyone | No | The proof itself is checked without the data. Not yet built; this is the next stage |

## Status

Tiresias 1.0.0 is research software on educational-grade cryptography. It proves through Glass's older query path, over the 31-bit prime field 2^31 − 1 with an unaudited hash, and every artifact it produces is stamped `crypto-grade: educational`. It is a working demonstration of the whole idea, end to end. **Do not use it to protect real data.**

Limits it enforces rather than hides:
- Comparisons (`MIN`, `MAX`, `<`, `>`) work on values below 65,536 and are refused above it.
- A `SUM`, `AVG` or `GROUP BY` total must stay below the field; one that would overflow is refused instead of proven wrapped.
- `GROUP BY` keys are categories.

The next stages move Tiresias onto Glass's sound 64-bit path with a witness-free verifier, then onto an audited proving backend with zero-knowledge, and add more protection for the answers themselves (query auditing against differencing, a privacy budget). See the [roadmap](docs/roadmap.md).

## Layout

```
tiresias/
  engine/      schema, commitments, the Glass adapter, prover, verifier, proof bundles
  query/       the SQL subset, its parser, and the query algebra it lowers to
  registry/    the multi-tenant server, its store, authentication, and web pages
  web/         the workbench (`tiresias app`) and the design system its pages share with the registry
  client/      the local prover and the registry client
  sdk.py       an embeddable engine
  cli.py       the `tiresias` command
deploy/        a container image and compose file for the registry (no Glass inside)
docs/          the HTTP API, configuration, and the roadmap
tests/         unit tests and an engine round trip
```

Every setting is a `TIRESIAS_*` environment variable, listed in [configuration](docs/configuration.md); `tiresias serve` refuses to start on a malformed, weak or unknown one.

```bash
python3.12 -m unittest discover -s tests     # unit tests, plus an engine round trip when Glass is present
docker compose -f deploy/docker-compose.yml up --build      # a self-hosted registry
```

## License

Apache-2.0. Glass, which does all the proving, is MIT or Apache-2.0; see [NOTICE](NOTICE).
