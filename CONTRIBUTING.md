# Contributing

Thanks for your interest in Tiresias.

## Setup

Tiresias needs **Python 3.12**, **Rust** (rustup; `zkvm/rust-toolchain.toml` pins the
version) and RISC Zero's **r0vm 3.0.6**, which does the proving:

```bash
pip install -e .
curl -L https://risczero.com/install | bash && rzup install r0vm 3.0.6
cargo build --release --manifest-path zkvm/Cargo.toml   # tiresias-prover
python3.12 -m unittest tests.test_unit                  # fast, on a committed real receipt
python3.12 -m unittest tests.test_engine                # real proofs, about a minute each
cargo test --manifest-path zkvm/Cargo.toml -p tiresias-core
python3.12 -m tiresias.demo                             # the narrated demo
```

The prover embeds the pinned guest (`zkvm/pinned`), so building it needs no Docker. After
changing the guest (`zkvm/methods/guest` or `zkvm/core`), run `zkvm/pin-guest.sh` (it needs
Docker and `rzup install rust 1.97.0`): it rebuilds the guest in RISC Zero's Docker image,
re-pins it, and rebuilds the prover. Then
regenerate the test fixture with `python3.12 -m tests.make_fixtures`, and commit both.

The Python package itself has **no third-party dependencies**; keep it that way.

## Principles

- **Honesty over hype.** This product sells *verifiability*; never overclaim what a
  proof guarantees. Say what rests on RISC Zero and what rests on Tiresias's own code.
- **The guest is the contract.** Every query semantic lives in `zkvm/core`; the Python in
  `tiresias/query/spec.py` mirrors it for refusals and is checked against it on every proof.
  Change both together, with tests on both sides.
- **The registry never proves.** It stores manifests and bundles and verifies receipts;
  it must never receive raw rows or a commitment's opening.
- **Fail loudly, not silently.** If a query cannot be proven (too few rows, a sum past
  64 bits), refuse with a clear error rather than emit a wrong answer.

## Pull requests

- Add or update tests in `tests/` (CI runs both suites and the guest's Rust tests, and
  rebuilds the pinned guest to check it is byte for byte the same).
- Run the suite and the demo before opening a PR.
- Keep diffs focused; match the existing style.
