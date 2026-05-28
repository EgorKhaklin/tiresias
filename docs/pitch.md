# Glass Private Intelligence — the pitch

**Prove answers about private data without revealing the data.**

## The problem

Organizations sit on data they can't share but are constantly asked to *report on*:
salaries, patient outcomes, transactions, model inputs. Today the choices are bad:
hand over the raw data (privacy/legal risk), or send an unverifiable number and ask
the recipient to trust you. Regulators, auditors, partners, and benchmarking
consortia all hit this wall.

## The solution

Commit a dataset once (a public, binding fingerprint — no rows). Then answer
aggregate queries (`SUM`, `COUNT`, `AVG`, `MIN`/`MAX`, `GROUP BY`) with a
**zero-knowledge proof** that the answer is the true result over the committed
data. The recipient verifies the proof; the rows never move.

Three things ship today, working end to end:
- a **zero-trust SaaS** where proving happens on the data-holder's machine and the
  registry **never sees a row**;
- **public verification links** — hand a regulator a URL; they confirm the answer
  is bound to a published commitment, with no account and no data;
- a **tamper demonstration** — a forged answer is provably rejected.

## Why now

Zero-knowledge proofs have crossed from theory into infrastructure (rollups, zkML).
The primitives are maturing fast; the *application layer* for "verifiable private
analytics" is wide open. GPI is built on **Glass**, a uniquely complete
self-hosting language that contains its own from-scratch zk-STARK — a credible,
inspectable foundation rather than a black box.

## Who buys

Compliance-heavy, data-sensitive B2B: healthcare, financial services, HR/comp
benchmarking, insurance, clinical research, data marketplaces/clean rooms.
Wedge: **regulatory reporting and cross-org benchmarking**, where "share the number,
not the data" is an explicit, recurring need.

## What's real vs. what's roadmap (we don't blur this)

**Real today:** the full product flow (commit → query → proof → verify → share),
multi-tenant auth + key lifecycle, zero-trust architecture (registry is engine-free),
soundness/overflow guards, a clean SDK/CLI, tests, Docker. The structure of the
zk-STARK is complete and differential-tested.

**Roadmap (stated plainly on every artifact):** the cryptographic *parameters* are
educational-grade. Production readiness = a real field (Goldilocks) end-to-end, an
audited hash, witness-free third-party verification, parameter analysis, and an
external audit. This is a known, scoped path — not hand-waving.

**The moat is the honesty.** A verifiability product that overclaims is dead on
arrival. GPI's discipline — say exactly what's proven, stamp every artifact with its
crypto grade — is both the engineering ethos and the trust differentiator.

## The ask / next milestones

1. Production cryptography (field + audited hash + audit) — the gate to protecting real value.
2. Witness-free third-party verification — the headline trust feature.
3. Design partners in one regulated vertical to harden the workflow against a real reporting obligation.
