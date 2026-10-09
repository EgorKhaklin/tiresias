# Security policy

## What a proof rests on

Tiresias does no cryptography of its own beyond SHA-256 commitments. Every proof is a receipt from the [RISC Zero zkVM](https://github.com/risc0/risc0), release 3.0.6, for one guest program: Tiresias's, built reproducibly and pinned in `zkvm/pinned` (its image id is printed by `tiresias prover`).

- **Soundness.** A receipt shows the guest ran to completion on some input and produced its journal: the dataset's commitment, the digest of the schema it was made under, the compiled query with its cohort floor, and the answer. The guest recomputes the commitment from the rows and salt it was given, so the answer is the answer over the committed rows. RISC Zero states 96 to 99 bits of conjectured security for its STARK provers, under the random oracle model and the toy problem conjecture.
- **Zero knowledge.** Tiresias publishes only succinct receipts (the verifier refuses any other kind), which RISC Zero designs to reveal nothing beyond the journal; the guest commits no row, no salt and no intermediate value. RISC Zero has not published a mathematical proof that its receipts are zero-knowledge (advisory GHSA-5xgj-pmjj-gw49; the prover's zero-knowledge noise was strengthened in 1.1).
- **Hiding.** The commitment is SHA-256 over a fresh random 32-byte salt and the cells, so it reveals nothing about the rows, even to someone who can guess them.
- **Audits.** RISC Zero's zkVM was audited by Hexens (the RISC-V and recursion provers, 2023; the STARK-to-SNARK prover, 2024) and by Veridise (the circuits, Zirgen and the recursive verifier, 2024 to 2025). The audits covered earlier releases; 3.0.6 includes the fixes for every soundness issue RISC Zero has disclosed since, among them GHSA-g3qg-6746-3mg9, GHSA-f6rc-24x4-ppxp and GHSA-jqq4-c7wq-36h7.
- **Not yet audited.** Tiresias's guest program (`zkvm/methods/guest`, `zkvm/core`), the prover binary (`zkvm/host`), and the Python that compiles queries and checks journals have not had an independent audit. The guest is short and its query logic is tested in Rust and, in mirror, in Python.

## The trust boundary

- **The data holder is not trusted by a verifier.** It proves on its own machine and could run anything there; what it cannot do is produce a receipt for a wrong answer, another query, a laxer cohort floor or other rows than the commitment binds.
- **What is not proved is where the rows came from.** A commitment shows the answers are consistent with the rows committed, not that those rows are true. Signed manifests are on the roadmap.
- **The registry is not trusted with data.** It never receives a row or a salt. It verifies every receipt it stores and every shared answer it shows, and anyone can download a shared answer and verify it independently.
- **The salt is the data holder's to keep.** With it and the rows, anyone can prove; without it, no one can, the holder included.

## What the architecture does protect (by design)

- The **registry never receives raw rows**: proving runs on the data holder's
  machine; only manifests (commitments) and proof bundles (answers and receipts) are uploaded.
- **Proving never leaves the machine**: `tiresias-prover` links no remote prover and
  refuses RISC Zero's development mode, so it neither makes nor accepts a fake receipt.
- **API keys** are stored only as SHA-256 hashes and can be revoked.
- An answer about fewer rows than the dataset's floor, and a sum that does not fit in
  64 bits, are **refused**, in the guest itself, rather than proved.

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

Please do not put the details of a security issue in a public issue. Open one that asks
for a private channel, and the details will be taken there. Reports about the guest program, the checks
`tiresias verify` makes, the registry (authentication, tenant isolation, data handling)
and the pages are all in scope. An issue in the RISC Zero zkVM itself belongs with RISC
Zero: see their security policy.
