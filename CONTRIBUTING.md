# Contributing

Thanks for your interest in Tiresias.

## Setup

Tiresias needs **Python 3.12** and the pinned [Glass](https://github.com/EgorKhaklin/Glass)
release, which does all the proving:

```bash
pip install -e .
tiresias glass --fetch                       # the pinned Glass, fetched and verified
python3.12 -m unittest discover -s tests     # unit tests, plus the engine round trip
python3.12 -m tiresias.demo                  # full narrated demo
```

To prove with a Glass checkout of your own, set `TIRESIAS_GLASS_DIR`. It must match the
pinned files (`tiresias glass` shows which differ); `TIRESIAS_GLASS_UNPINNED=1` allows a
differing checkout while you develop both. Moving to a new Glass release means updating
`GLASS_TAG` and `PINNED_FILES` in `tiresias/engine/glass_pin.py` and rerunning the tests.

Tiresias itself has **no third-party Python dependencies**; keep it that way.

## Principles

- **Honesty over hype.** This product sells *verifiability*; never overclaim what a
  proof guarantees. The cryptography is educational-grade: say so. Every artifact
  carries `crypto-grade: educational`.
- **Never modify the Glass repo.** Extend via Tiresias-owned drivers; slice Glass
  functions at runtime rather than copying them, and prove only with the pinned files.
- **The registry stays engine-free.** It stores and verifies bindings; it must never
  receive raw rows or run the prover.
- **Fail loudly, not silently.** If a query can't be proven soundly (e.g. a sum that
  overflows the field, a comparison out of range), refuse with a clear error rather
  than emit a wrong/unsound result.

## Pull requests

- Add or update tests in `tests/` (CI runs `tests.test_unit`).
- Run the suite and the demo before opening a PR.
- Keep diffs focused; match the existing style.
