# Contributing

Thanks for your interest in Glass Private Intelligence.

## Setup

GPI needs **Python 3.12** and the [Glass](https://github.com/EgorKhaklin/Glass)
engine on disk (it does all the proving):

```bash
git clone https://github.com/EgorKhaklin/Glass ~/Desktop/Glass
export GPI_GLASS_DIR=~/Desktop/Glass
pip install -e .
python3.12 -m unittest discover -s tests     # fast suite; engine test self-skips without Glass
python3.12 -m gpi.demo                         # full narrated demo
```

GPI itself has **no third-party Python dependencies** — keep it that way.

## Principles

- **Honesty over hype.** This product sells *verifiability*; never overclaim what a
  proof guarantees. The cryptography is educational-grade — say so. Every artifact
  carries `crypto-grade: educational`.
- **Never modify the Glass repo.** Extend via GPI-owned drivers; slice Glass
  functions at runtime rather than copying them.
- **The registry stays engine-free.** It stores and verifies bindings; it must never
  receive raw rows or run the prover.
- **Fail loudly, not silently.** If a query can't be proven soundly (e.g. a sum that
  overflows the field, a comparison out of range), refuse with a clear error rather
  than emit a wrong/unsound result.

## Pull requests

- Add or update tests in `tests/` (CI runs `tests.test_unit`).
- Run the suite and the demo before opening a PR.
- Keep diffs focused; match the existing style.
