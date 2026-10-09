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

## Registry review, October 2026

What was checked in the registry (`tiresias/registry/`) and what changed:

- **Authentication.** API keys are 256 random bits, shown once and stored as SHA-256 hashes; the admin token is compared in constant time and, when set, must be at least 32 characters or the registry refuses to start. No change.
- **Tenant isolation.** Every store query that reads tenant data is scoped by the caller's organization, and a test asserts one organization cannot read another's manifests, bundles or keys. No change.
- **Request bodies.** A negative `Content-Length` passed the size check and became an unbounded read; a non-numeric one, or a body that was not a JSON object, raised an unhandled error. All are now rejected with 400, and dataset and bundle ids must be strings of 1 to 128 letters, digits or underscores.
- **Error responses.** An unhandled error returned its exception type and message, which can carry file paths, SQL or request content. The client now receives only an error id; the trace is in the server log under that id.
- **Rate limits.** Authenticated routes were limited per organization; the public share lookups and the admin routes were not limited at all. They are now limited per client address, with the same per-minute budget.

Known limits: the rate limiter is in memory and per process, so it does not span replicas; TLS is expected to terminate at a reverse proxy in front of the registry; failed authentication is not throttled separately, since a 256-bit key cannot be guessed.

## Pages review, October 2026

Redesigning the web pages surfaced a stored cross-site scripting hole in the registry, now closed:

- **The shared-answer page wrote tenant text as HTML.** `/v/<token>` set a bundle's query, the organization name, the dataset name and the check names through `innerHTML`, unescaped, and the registry stored any query string a tenant uploaded. A tenant could publish a share link whose page ran script on the registry's origin, where the console kept API keys in `localStorage`; anyone signed in to the console who opened the link could lose their key.
- **The fix, in layers.** Every page now builds its content as text nodes; a test fails if a page script uses `innerHTML`, `outerHTML`, `insertAdjacentHTML`, `document.write` or `eval`. Every registry and workbench response carries a Content-Security-Policy that allows script only from the server's own files and forbids inline script, inline handlers and framing; a test fails if a page carries an inline script, handler or style. The registry refuses, with `400`, a bundle whose query is not Tiresias SQL over its own dataset's columns, and a manifest whose name or category labels contain markup or control characters. The console keeps the API key in `sessionStorage`, for the tab only.

Each fix has a regression test, and undoing any one of them fails its test.

## Reporting an issue

This is a research/demonstration project. If you find a correctness or security
issue, please open an issue on the GitHub repository describing it. Given the
explicit educational-grade status, cryptographic weaknesses in the underlying
primitives are expected and documented; reports about the *product layer*
(auth, tenant isolation, source-generation, data handling) are most useful.
