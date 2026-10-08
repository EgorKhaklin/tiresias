# Security policy

## Cryptographic maturity: read this first

Tiresias is, today, a **working demonstration** of verifiable
private analytics. Its cryptography is **educational-grade**, inherited from
[Glass](https://github.com/EgorKhaklin/Glass):

- Field: the 31-bit prime field 2³¹−1 (Mersenne-31) on the Pane path; values and sums are bounded accordingly.
- Hash: MiMC / a reduced-round Poseidon (**unaudited**).
- No parameter analysis, no constant-time guarantees, **no external audit**.

**Do not use Tiresias to protect real secrets or real value.** Every artifact it
produces is stamped `crypto-grade: educational`. What *is* rigorous is the
structural completeness of the zk-STARK and the differential-testing discipline
behind Glass, not the production-strength of the primitives.

The path to production cryptography (a real field end-to-end, an audited hash,
parameter analysis, witness-free third-party verification, and an external audit)
is tracked in the README roadmap and in Glass's `docs/security/soundness.md`. Until those
land, treat all "proofs" here as demonstrations of the *idea*, not guarantees.

## What the architecture does protect (by design)

- The **registry never receives raw rows**: proving runs on the data-holder's
  machine; only manifests (commitments) and proof bundles (public results) are uploaded.
- **API keys** are stored only as SHA-256 hashes and can be revoked.
- Aggregates that would exceed the field, and comparisons outside the gadget's
  range, are **refused** rather than silently producing an unsound result.

These are real engineering properties; they are independent of the
(educational-grade) cryptographic strength above.

## Reporting an issue

This is a research/demonstration project. If you find a correctness or security
issue, please open an issue on the GitHub repository describing it. Given the
explicit educational-grade status, cryptographic weaknesses in the underlying
primitives are expected and documented; reports about the *product layer*
(auth, tenant isolation, source-generation, data handling) are most useful.
