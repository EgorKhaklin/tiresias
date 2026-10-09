# Roadmap

Tiresias and Glass are raised together as one temple; the full staged plan, with the exit gate of every step, is in the [Glass roadmap](https://github.com/EgorKhaklin/Glass/blob/main/docs/roadmap.md). Tiresias proves with the audited RISC Zero zkVM rather than waiting for Glass's own audited backend. This page lists the parts that are Tiresias's own.

| Stage | Temple part | For Tiresias |
|---|---|---|
| I | Euthynteria, the leveling course | The `tiresias` name in code, 1.0.0, a lean tree. Done. |
| II | Stylobate, the platform | The prover's guest pinned and rebuilt byte for byte in CI (done); registry settings validated at boot (done); release automation (done). |
| III | Peristyle, the columns | The engine, the privacy of the answer, the registry as a service (below). |
| IV | Architrave, the beam | End to end on an audited backend with zero-knowledge, verified without the data. Done, on RISC Zero. |
| V | Frieze, the carved story | Docs, a ten-minute walkthrough, a design partner on notional data. |
| VI | Pediment, the gable | External audit of the guest program, the verifier's checks and the registry. |
| VII | Acroterion, the apex | One recursive proof over many datasets. |

## The engine

Tiresias proves in the RISC Zero zkVM (3.0.6): a guest program recomputes the salted SHA-256 commitment, answers the query over 64-bit integers, and enforces the cohort floor; anyone verifies the succinct, zero-knowledge receipt without the data.

- [x] Witness-free verification: `tiresias verify <bundle>` checks the proof itself with no data and no account, and the public link runs the same check.
- [x] An audited backend with zero-knowledge: RISC Zero's zkVM (audited by Hexens and Veridise). Tiresias ships no proof mode that is not zero-knowledge: the verifier accepts only succinct receipts.
- [ ] Faster proofs: about a minute today, almost all of it RISC Zero's fixed recursion cost.
- [ ] Prove with Glass again if Glass's own audited backend lands and matches these guarantees.

## The privacy of the answer

A true average can still leak a person: two queries that differ by one row reveal that row.

- [x] A minimum cohort size: every answer carries a proven cohort; queries below the dataset's floor are refused, small `GROUP BY` groups suppressed, and the registry rejects bundles that break the policy.
- [ ] Query auditing against differencing, per dataset.
- [ ] A per-dataset privacy budget, with optional differential-privacy noise whose sampling is proven.
- [ ] A written privacy model beside the soundness model.

## The registry as a service

- [ ] PostgreSQL behind the store, with migrations; SQLite for local use.
- [ ] Data holders sign their manifests (ML-DSA), so a commitment names who made it.
- [ ] Versioned datasets: a new version does not invalidate proofs on the old one.
- [ ] Operations: a structured audit log, a backup and restore drill, a Helm chart.
- [x] A security review: authentication, tenant isolation, rate limits, input bounds (see SECURITY.md, Registry review).

## Wider questions

- [ ] Large-value comparisons, multi-key `GROUP BY`, `HAVING`, `COUNT(DISTINCT)`, and joins across committed datasets.
