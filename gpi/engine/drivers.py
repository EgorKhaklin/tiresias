"""Generates Glass driver programs for the Tiresias engine.

A driver is: the self-contained Pane+Frost machinery from
~/Desktop/Glass/examples/prove/prove_pane.glass (everything before its demo
section), followed by a generated tail that binds a *programmatic* table and
query and prints structured GPI_* lines the adapter parses.

The Glass repo is treated as read-only: we read prove_pane.glass, never write it.
"""

from __future__ import annotations

import os

from gpi.query.pane_ast import CountQ, From, Query, Table

# The demo marker that prove_pane.glass uses to separate reusable machinery from
# its hardcoded demo (mirrors how `glass prove` cuts the source bridge).
_DEMO_MARKER = "# --- demo"


def glass_dir() -> str:
    return os.environ.get(
        "GPI_GLASS_DIR", os.path.expanduser("~/Desktop/Glass")
    )


def _machinery() -> str:
    path = os.path.join(glass_dir(), "examples", "prove", "prove_pane.glass")
    with open(path) as f:
        src = f.read()
    cut = src.find(_DEMO_MARKER)
    if cut < 0:
        raise RuntimeError(
            f"could not find demo marker in {path}; prove_pane.glass layout changed"
        )
    return src[:cut]


def build_query_driver(
    query: Query,
    gamma: int,
    claimed_r: int | None = None,
    claimed_c: int | None = None,
) -> str:
    """A driver that proves `query` over its (embedded) committed table.

    Emits, on stdout:
      GPI_RESULT=<the true result, from run_query>
      GPI_COMMIT=<the binding commitment to the table>
      GPI_PROOF=ACCEPT|REJECT  (for the *claimed* R/C; defaults to the honest ones)

    Pass claimed_r / claimed_c to prove a *lie* and observe REJECT — the
    soundness check that mirrors Glass's own differential discipline.
    """
    q_glass = query.to_glass()
    r_expr = "__want" if claimed_r is None else str(claimed_r)
    c_expr = "__cc" if claimed_c is None else str(claimed_c)
    tail = f"""
let __q : Query = {q_glass}
let __gamma : Int = {gamma}
let __want : Int = result_int(run_query(__q))
let __cc : Int = commit_of(__q, __gamma)
let __ok : Bool = prove_pane(__q, __gamma, {c_expr}, {r_expr})
let _ : String = print("GPI_RESULT=" ++ int_to_string(__want))
let _ : String = print("GPI_COMMIT=" ++ int_to_string(__cc))
let _ : String = print("GPI_PROOF=" ++ (if __ok then "ACCEPT" else "REJECT"))
"gpi"
"""
    return _machinery() + tail


def _minmax_fns() -> str:
    """Extract the MIN/MAX prover functions from prove_pane.glass.

    These live *after* the demo marker, so the base machinery omits them; we
    slice them out at runtime (no copying — stays in sync with the Glass source).
    Their dependencies are all in the base machinery.
    """
    path = os.path.join(glass_dir(), "examples", "prove", "prove_pane.glass")
    with open(path) as f:
        src = f.read()
    start = src.find("fn minmax_loop")
    end = src.find("fn mm_line")
    if start < 0 or end < 0 or end <= start:
        raise RuntimeError("could not locate MIN/MAX functions in prove_pane.glass")
    return src[start:end]


def build_minmax_driver(query: Query, gamma: int, claimed_m: int | None = None) -> str:
    """A driver that proves a MIN/MAX query over its committed table."""
    q_glass = query.to_glass()
    m_expr = "__want" if claimed_m is None else str(claimed_m)
    tail = f"""
let __q : Query = {q_glass}
let __sub : Query = mm_sub(__q)
let __rows : List<Row> = rows_of(table_of(__sub))
let __want : Int = result_int(run_query(__q))
let __cc : Int = ref_commit(flatten_table(schema_of(__rows), __rows), {gamma}, 1)
let __ok : Bool = prove_minmax(__rows, mm_col(__q), pred_of(__sub), {gamma}, __cc, {m_expr}, mm_is_max(__q))
let _ : String = print("GPI_RESULT=" ++ int_to_string(__want))
let _ : String = print("GPI_COMMIT=" ++ int_to_string(__cc))
let _ : String = print("GPI_PROOF=" ++ (if __ok then "ACCEPT" else "REJECT"))
"gpi"
"""
    return _machinery() + "\n" + _minmax_fns() + tail


def build_commit_driver(table: Table, gamma: int) -> str:
    """A driver that prints only the binding commitment of `table`.

    Uses the same `commit_of` the prover uses, so the manifest's commitment is
    by construction identical to the one every later proof binds against.
    """
    q_glass = CountQ(From(table)).to_glass()
    tail = f"""
let __q : Query = {q_glass}
let __cc : Int = commit_of(__q, {gamma})
let _ : String = print("GPI_COMMIT=" ++ int_to_string(__cc))
"gpi"
"""
    return _machinery() + tail
