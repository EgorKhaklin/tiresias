"""The Glass engine adapter.

Imports the Glass reference interpreter (glass.py) directly and runs generated
drivers, capturing stdout and parsing the GPI_* result lines. This is the single
point where Tiresias touches Glass; everything above it works in Python.
"""

from __future__ import annotations

import contextlib
import io
import os
import sys
from dataclasses import dataclass

from gpi.engine.drivers import (
    build_commit_driver,
    build_minmax_driver,
    build_query_driver,
    glass_dir,
)
from gpi.query.pane_ast import Query, Table

_glass = None


def _load_glass():
    global _glass
    if _glass is None:
        gd = glass_dir()
        if gd not in sys.path:
            sys.path.insert(0, gd)
        # Glass programs recurse deeply (lists, folds); the interpreter is
        # itself recursive, so lift Python's limit before running drivers.
        sys.setrecursionlimit(1_000_000)
        import glass  # type: ignore

        _glass = glass
    return _glass


def run_driver(driver_src: str) -> str:
    """Run a Glass driver string through the reference interpreter, returning
    everything it printed to stdout."""
    glass = _load_glass()
    base_dir = os.path.join(glass_dir(), "examples", "prove")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        glass.run_source(driver_src, verbose=False, base_dir=base_dir)
    return buf.getvalue()


def _parse(out: str) -> dict:
    fields: dict[str, str] = {}
    for line in out.splitlines():
        if line.startswith("GPI_") and "=" in line:
            k, v = line.split("=", 1)
            fields[k] = v.strip()
    return fields


@dataclass
class ProofResult:
    result: int  # the true aggregate answer (run_query)
    commitment: int  # binding commitment to the private table
    accepted: bool  # did the ZK proof verify for the claimed answer?
    raw: str  # full interpreter output (for debugging)

    # Honest framing, per Glass docs/soundness.md: the cryptography here is
    # educational-grade (Baby Bear field, unaudited hash). The proof structure
    # is real and checked; the parameters are not production-sound.
    crypto_grade: str = "educational"


def prove_query(query: Query, gamma: int) -> ProofResult:
    """Run + prove an honest query over its committed private table."""
    out = run_driver(build_query_driver(query, gamma))
    f = _parse(out)
    if "GPI_RESULT" not in f or "GPI_PROOF" not in f:
        raise RuntimeError(f"driver did not emit expected output:\n{out}")
    return ProofResult(
        result=int(f["GPI_RESULT"]),
        commitment=int(f["GPI_COMMIT"]),
        accepted=(f["GPI_PROOF"] == "ACCEPT"),
        raw=out,
    )


def commit_table(table: Table, gamma: int) -> int:
    """Compute the binding commitment of a table (the public manifest value)."""
    out = run_driver(build_commit_driver(table, gamma))
    f = _parse(out)
    if "GPI_COMMIT" not in f:
        raise RuntimeError(f"commit driver did not emit a commitment:\n{out}")
    return int(f["GPI_COMMIT"])


def prove_claim(query: Query, gamma: int, claimed_r: int) -> bool:
    """Prove a *specific* claimed result. Returns whether it verified.

    A correct claim verifies; any wrong claim is rejected — the end-to-end
    soundness check."""
    out = run_driver(build_query_driver(query, gamma, claimed_r=claimed_r))
    return _parse(out).get("GPI_PROOF") == "ACCEPT"


def prove_minmax_query(query: Query, gamma: int) -> ProofResult:
    """Run + prove an honest MIN/MAX query over its committed table."""
    out = run_driver(build_minmax_driver(query, gamma))
    f = _parse(out)
    if "GPI_RESULT" not in f or "GPI_PROOF" not in f:
        raise RuntimeError(f"minmax driver did not emit expected output:\n{out}")
    return ProofResult(
        result=int(f["GPI_RESULT"]),
        commitment=int(f["GPI_COMMIT"]),
        accepted=(f["GPI_PROOF"] == "ACCEPT"),
        raw=out,
    )


def prove_minmax_claim(query: Query, gamma: int, claimed_m: int) -> bool:
    out = run_driver(build_minmax_driver(query, gamma, claimed_m=claimed_m))
    return _parse(out).get("GPI_PROOF") == "ACCEPT"
