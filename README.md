<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/tiresias-dark.svg">
  <img src="assets/tiresias-light.svg" width="100%" alt="Tiresias: verifiable private analytics">
</picture>

**Answers from data you never reveal. Every aggregate carries a proof that it is true. Never a row.**

[![CI](https://img.shields.io/github/actions/workflow/status/EgorKhaklin/tiresias/ci.yml?branch=main&label=CI&labelColor=1f2328&color=59636e&style=flat-square)](https://github.com/EgorKhaklin/tiresias/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/EgorKhaklin/tiresias?label=release&labelColor=1f2328&color=59636e&style=flat-square)](https://github.com/EgorKhaklin/tiresias/releases/latest)
[![Proved with RISC Zero](https://img.shields.io/badge/proved_with-RISC_Zero_zkVM-59636e?labelColor=1f2328&style=flat-square)](https://github.com/risc0/risc0)
[![License](https://img.shields.io/badge/license-Apache--2.0-59636e?labelColor=1f2328&style=flat-square)](LICENSE)

</div>

<picture><source media="(prefers-color-scheme: dark)" srcset="assets/rule-dark.svg"><img src="assets/rule-light.svg" width="100%" alt=""></picture>

Tiresias was the seer of Thebes who knew the truth without seeing it. That is what this asks of its reader.

A data holder commits a sensitive dataset and publishes only the commitment. Anyone may then ask an aggregate question of it: a sum, a count, an average, a minimum, a breakdown by group. The answer comes back with a zero-knowledge proof, made in the RISC Zero zkVM, that it is the true result of the query over the committed rows. Anyone can check that proof in milliseconds, without the data. The rows never leave the holder's machine.

- **Share a number, not the data.** Report an aggregate to a regulator, contribute to an industry benchmark, or answer a partner's question, without handing over a single record.
- **The registry never sees a row.** Proving runs where the data lives. The registry stores commitments and proofs, verifies every proof, and serves a public link that needs no account.
- **Nothing is taken on the holder's word.** An answer that is not the true one has no proof, and a proof cannot be moved onto other data, another question or a laxer privacy floor.

<picture><source media="(prefers-color-scheme: dark)" srcset="assets/rule-dark.svg"><img src="assets/rule-light.svg" width="100%" alt=""></picture>

## Try it

Tiresias is Python 3.12 with no Python dependencies, and a small Rust prover, `tiresias-prover`, built on [RISC Zero](https://github.com/risc0/risc0) 3.0.6. Proving runs in RISC Zero's `r0vm`, on this machine.

```bash
git clone https://github.com/EgorKhaklin/tiresias && cd tiresias
pip install -e .                                        # installs the `tiresias` command
curl -L https://risczero.com/install | bash && rzup install r0vm 3.0.6
cargo build --release --manifest-path zkvm/Cargo.toml   # tiresias-prover
tiresias app                                            # the workbench: http://127.0.0.1:8765
```

The workbench runs on the machine that holds the data and never sends a row anywhere. Drop in a CSV and it detects each column's type; choose the minimum cohort and commit. Then build a question (a total, count, average, lowest or highest value, with conditions and a breakdown) without writing SQL, or write the SQL yourself. Each proof takes about a minute. The answer comes back with the number of rows it describes, any groups withheld for being too small, and its verification checks; a tamper test shows a forged answer failing, and the proof downloads as a bundle anyone can check with `tiresias verify`.

For the same flow in a terminal, `python3.12 -m tiresias.demo` commits a payroll, proves three questions, verifies one with only the public manifest, and rejects a forged answer.

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
SELECT AVG(salary)   WHERE level > 3            -- with its sum and count
SELECT MIN(level)    WHERE dept = 'eng'
SELECT MAX(level)
SELECT dept, SUM(salary) GROUP BY dept          -- every group, in one proof
```

Filters: `=`, `!=`, `<`, `>`, `<=`, `>=`, joined by `AND` and `OR`. Columns are 64-bit integers, booleans, or categories (labels mapped to codes in the public manifest).

Every answer carries a proven count of the rows it describes, its cohort. A dataset declares a minimum cohort when it is committed (`--min-cohort`, default 5): a query about fewer rows is refused, inside the proof, and a `GROUP BY` group below it is withheld and listed by label only. The policy is part of the dataset's id and of every proof, so it cannot be loosened quietly.

<picture><source media="(prefers-color-scheme: dark)" srcset="assets/rule-dark.svg"><img src="assets/rule-light.svg" width="100%" alt=""></picture>

## How it works

**Commit.** The rows are hashed with SHA-256 under a fresh 32-byte salt into a commitment. The manifest publishes the commitment, the schema, the row count and the minimum cohort. The salt, the commitment's opening, stays beside the data (`~/.tiresias/openings`); without it the commitment reveals nothing about the rows, not even to someone guessing them.

**Prove.** A guest program runs in the RISC Zero zkVM with the rows and the salt as private input. It recomputes the commitment, evaluates the query, refuses an answer about too few rows, and commits to its public output only the commitment, the schema's digest, the compiled query and the answer. The receipt is succinct (about 220 KB) and zero-knowledge.

**Verify.** `tiresias verify` checks the receipt against the one guest Tiresias trusts, then checks that it was proved over the published commitment and schema, for this exact query and cohort floor, with the answer stated. The registry runs the same check on every upload and on every view of a shared link.

| Guarantee | Rests on |
|---|---|
| The answer is the true answer over the committed rows | the RISC Zero zkVM's soundness |
| The proof reveals nothing about the rows beyond the answer | RISC Zero's zero-knowledge receipts, and the salted commitment |
| No answer singles out a few people | the cohort floor, enforced in the guest |

The guest (`zkvm/methods/guest`, with its query logic in `zkvm/core`) is built reproducibly in RISC Zero's Docker image and pinned in `zkvm/pinned`; CI rebuilds it and fails on any difference, so the image id `tiresias prover` prints identifies one exact program.

## Security

RISC Zero's zkVM has been audited by Hexens (2023, 2024) and Veridise (2024 to 2025); Tiresias uses its 3.0.6 release, which includes the fixes for every soundness issue RISC Zero has disclosed. RISC Zero designs its receipts to be zero-knowledge but has not published a proof that they are. Tiresias's own guest program and integration have not yet had an independent audit. [SECURITY.md](SECURITY.md) sets out what each part rests on.

Limits it enforces rather than hides:
- A sum must fit in 64 bits; one that would not is refused.
- `GROUP BY` keys are categories.
- A proof takes about a minute on a laptop.

The next stages add more protection for the answers themselves (query auditing against differencing, a privacy budget). See the [roadmap](docs/roadmap.md).

## Layout

```
tiresias/
  engine/      schema, commitments and openings, the prover, the verifier, proof bundles
  query/       the SQL subset, its parser, and the plan the guest proves
  registry/    the multi-tenant server, its store, authentication, and web pages
  web/         the workbench (`tiresias app`) and the design system its pages share with the registry
  client/      the local prover and the registry client
  sdk.py       an embeddable engine
  cli.py       the `tiresias` command
zkvm/          the guest, its query logic, the pinned guest binary, and tiresias-prover
deploy/        a container image and compose file for the registry
docs/          the HTTP API, configuration, and the roadmap
tests/         unit tests (on a real receipt) and end-to-end proofs
```

Every setting is a `TIRESIAS_*` environment variable, listed in [configuration](docs/configuration.md); `tiresias serve` refuses to start on a malformed, weak or unknown one.

```bash
python3.12 -m unittest tests.test_unit       # fast: verifies a committed real receipt
python3.12 -m unittest tests.test_engine     # real proofs, about a minute each
docker compose -f deploy/docker-compose.yml up --build      # a self-hosted registry
```

## License

Apache-2.0. RISC Zero, which does all the proving, is Apache-2.0; see [NOTICE](NOTICE).
