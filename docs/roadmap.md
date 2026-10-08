# Roadmap

Tiresias stands on Glass, and the two are raised together as one temple. The full staged plan, with the exit gate of every step, is in the [Glass roadmap](https://github.com/EgorKhaklin/Glass/blob/main/docs/roadmap.md). This page lists the parts that are Tiresias's own.

| Stage | Temple part | For Tiresias |
|---|---|---|
| I | Euthynteria, the leveling course | The `tiresias` name in code, 1.0.0, a lean tree. Done. |
| II | Stylobate, the platform | Glass pinned by tag and SHA-256, fetched and verified (done); registry settings validated at boot (done); release automation (done). |
| III | Peristyle, the columns | The engine, the privacy of the answer, the registry as a service (below). |
| IV | Architrave, the beam | End to end on the audited backend with zero-knowledge, verified without the data. |
| V | Frieze, the carved story | Docs, a ten-minute walkthrough, a design partner on notional data. |
| VI | Pediment, the gable | External audit of the query circuits and the registry; 2.0.0. |
| VII | Acroterion, the apex | One recursive proof over many datasets. |

## The engine

Tiresias proves today through Glass's older query path: a 31-bit field (2^31 − 1), comparisons below 65,536, sums below the field, and a proof that only someone holding the data can re-check.

- [ ] Move onto Glass's sound Goldilocks path (`verify_b3`, 64-bit field, wider comparisons). Gate: every query type round-trips.
- [ ] Witness-free verification: `tiresias verify <bundle>` checks the proof itself with no data and no account, and Lens, Glass's independent verifier, agrees. Gate: the public link runs this check.
- [ ] Move onto the audited backend with zero-knowledge once Glass's Column 1 lands. Tiresias never ships a proof mode that is not zero-knowledge.

## The privacy of the answer

A true average can still leak a person: two queries that differ by one row reveal that row.

- [ ] A minimum cohort size: no aggregate over fewer than k rows, with the count bound in the proof.
- [ ] Query auditing against differencing, per dataset.
- [ ] A per-dataset privacy budget, with optional differential-privacy noise whose sampling is proven.
- [ ] A written privacy model beside the soundness model.

## The registry as a service

- [ ] PostgreSQL behind the store, with migrations; SQLite for local use.
- [ ] Data holders sign their manifests (ML-DSA), so a commitment names who made it.
- [ ] Versioned datasets: a new version does not invalidate proofs on the old one.
- [ ] Operations: a structured audit log, a backup and restore drill, a Helm chart.
- [ ] A security review: authentication, tenant isolation, rate limits, input bounds.

## Wider questions

- [ ] Large-value comparisons, multi-key `GROUP BY`, `HAVING`, `COUNT(DISTINCT)`, and joins across committed datasets.
