"""RESEARCH SPIKE — witness-free re-verification of a serialized FRI proof.

This is NOT a shipped product feature and is NOT claimed to be sound third-party
verification. It is a deliberately-scoped experiment toward the roadmap item
"Tier 3 — witness-free verification," kept out of the gpi product package.

What it demonstrates (honestly):

  1. SPLIT.  A prover (with the private witness) builds a real blinded F_{p^4}
     FRI STARK over a committed-table SUM statement (Glass's prove_query_zk path),
     and serializes the proof transcript — the FRI layer codewords, domains,
     Merkle roots, fold challenges, and the final codeword — to a flat string.

  2. WITNESS-FREE RE-EXECUTION.  A separate verifier program reconstructs that
     transcript from the serialized bytes alone — with NO access to the witness
     or the table — and re-runs Glass's `fri_verify` low-degree test over it.
     Honest proof verifies (ACCEPT); a corrupted transcript is rejected (REJECT).

What it does NOT yet prove (the gap, stated plainly):

  `fri_verify` confirms the committed codeword is *low-degree*. It does NOT bind
  that codeword to the claimed public statement (commitment C, result R) or to
  the circuit — the verifier here never even consults C/R. A cheating prover
  could submit a low-degree codeword unrelated to the statement and this check
  alone would pass. SOUND witness-free verification additionally needs a trace
  commitment + query openings + an out-of-circuit evaluation of the gate
  identity binding the quotient to the trace and to (C, R). That is the real
  remaining work (Glass "Track R"), and it is bounded by the educational-grade
  primitives regardless.

So: this spike proves out the *serialization + witness-free re-execution
mechanics* and pins down exactly what's missing — it is a stepping stone, not a
verifier you should trust.

TOWARD SOUNDNESS — the specific blocker (worked out while extending this spike):

  A sound out-of-circuit verifier would, at each FRI query point x_j: open the
  trace columns l/r/o (from a trace commitment), recompute the *public* selector
  polynomials from the circuit, evaluate the gate identity G(x_j), and check that
  the opened quotient equals G(x_j)/Z_H(x_j). The trace-commitment + openings part
  is ordinary plumbing (reuses the existing F4 Merkle helpers).

  The real blocker is the ZK blinding. `qcode` commits q(x) + blind(x), where
  q = G/Z_H and `blind` is the prover's secret randomness. The verifier cannot
  recover G(x_j) from the opened value without blind(x_j), and revealing blind at
  the query points would break zero-knowledge (the educational blind is only
  degree 2, so a few openings over-determine it). A *sound + ZK* verifier
  therefore needs a corrected construction — e.g. a vanishing blind (commit
  q + Z_H*blind so the blind cancels on the trace domain), or a separate blind
  commitment with a low-degree-enough blind. That changes the prover's quotient
  construction, i.e. it is a protocol-design change to Glass's STARK (or a
  GPI-owned reimplementation) — genuine zk-STARK research, still educational-grade
  in its primitives. It is NOT mere verifier plumbing, which is why this stays a
  spike rather than a shipped verifier.

Run:  python3.12 research/witness_free_spike.py
"""

from __future__ import annotations

import os

from gpi.engine.adapter import run_driver
from gpi.engine.drivers import glass_dir

PROVE_QUERY_ZK = "prove_query_zk.glass"


def _machinery() -> str:
    path = os.path.join(glass_dir(), "examples", "prove", PROVE_QUERY_ZK)
    with open(path) as f:
        src = f.read()
    cut = src.find("# --- demo")
    if cut < 0:
        raise RuntimeError("demo marker not found in prove_query_zk.glass")
    return src[:cut]


# --- prover: build the proof and serialize the transcript --------------------
_PROVER_TAIL = """
# --- research spike: split prove/verify and serialize the FRI transcript -----
type SpikeProof = | SpikeProof(List<Layer>, List<F4>, Int)

fn f2s(x: F2) : String = match x { F2(a, b) => int_to_string(a) ++ "," ++ int_to_string(b) }
fn f4s(x: F4) : String = match x { F4(c0, c1) => f2s(c0) ++ "," ++ f2s(c1) }
fn f4ls(xs: List<F4>) : String = match xs { [] => ""; [x, ...r] => f4s(x) ++ (match r { [] => ""; _ => ";" ++ f4ls(r) }) }
fn ils(xs: List<Int>) : String = match xs { [] => ""; [x, ...r] => int_to_string(x) ++ (match r { [] => ""; _ => ";" ++ ils(r) }) }
fn layer_s(l: Layer) : String = match l { Layer(cw, dom, root, beta) => f4ls(cw) ++ "#" ++ ils(dom) ++ "#" ++ int_to_string(root) ++ "#" ++ f4s(beta) }
fn layers_s(ls: List<Layer>) : String = match ls { [] => ""; [x, ...r] => layer_s(x) ++ (match r { [] => ""; _ => "||" ++ layers_s(r) }) }

# mirrors stark_ok up to the FRI commit, but returns (layers, final, 4n)
fn stark_proof(gates: List<Gate>, w: List<Int>, seed: Int, nv: F2, nw: Int) : SpikeProof =
  let n : Int = ng(gates) in
  let qa : List<Int> = interpolate(pad(vqa(gates), n)) in let qm : List<Int> = interpolate(pad(vqm(gates), n)) in
  let qs : List<Int> = interpolate(pad(vqs(gates), n)) in let qc : List<Int> = interpolate(pad(vqc(gates), n)) in
  let qx : List<Int> = interpolate(pad(vqx(gates), n)) in let cc : List<Int> = interpolate(pad(vc(gates), n)) in
  let ll : List<Int> = interpolate(pad(vl(gates, w), n)) in let rr : List<Int> = interpolate(pad(vr(gates, w), n)) in
  let oo : List<Int> = interpolate(pad(vo(gates, w), n)) in
  let coset : List<Int> = coset_domain(4 * n) in
  let qcw : List<F4> = qcode(qa, qm, qs, qc, qx, ll, rr, oo, cc, rand_poly(seed), coset, n) in
  match commit(qcw, coset, [], nv, nw) { (layers, final) => SpikeProof(layers, final, 4 * n) }

fn bq_gates(b: Build) : List<Gate> = match b { Build(n, g, w) => g }
fn bq_w(b: Build) : List<Int> = match b { Build(n, g, w) => w }

let __bbw : Int = find_nonres_b(2)
let __bbv : F2 = find_v(0, __bbw)
let __vals : List<Int> = [100, 150]
let __gamma : Int = 1234567
let __comm : Int = ref_commit(__vals, __gamma, 1)
let __res : Int = ref_sum(__vals)
let __b : Build = build_query(__vals, __gamma, __comm, __res)
let __pf : SpikeProof = stark_proof(bq_gates(__b), bq_w(__b), 11111, __bbv, __bbw)
let __layers : List<Layer> = match __pf { SpikeProof(l, f, d) => l }
let __final : List<F4> = match __pf { SpikeProof(l, f, d) => f }
let __dsize : Int = match __pf { SpikeProof(l, f, d) => d }
let _ : String = print("PUBLIC_C=" ++ int_to_string(__comm))
let _ : String = print("PUBLIC_R=" ++ int_to_string(__res))
let _ : String = print("DSIZE=" ++ int_to_string(__dsize))
let _ : String = print("NW=" ++ int_to_string(__bbw))
let _ : String = print("NV=" ++ f2s(__bbv))
let _ : String = print("FINAL=" ++ f4ls(__final))
let _ : String = print("LAYERS=" ++ layers_s(__layers))
"spike-prover"
"""


def prover_driver() -> str:
    return _machinery() + _PROVER_TAIL


# --- parse the serialized transcript -----------------------------------------
def _parse_fields(out: str) -> dict:
    f = {}
    for line in out.splitlines():
        if "=" in line and line.split("=", 1)[0] in (
            "PUBLIC_C", "PUBLIC_R", "DSIZE", "NW", "NV", "FINAL", "LAYERS"
        ):
            k, v = line.split("=", 1)
            f[k] = v
    return f


def _f4_lit(g: list[int]) -> str:
    return f"F4(F2({g[0]},{g[1]}),F2({g[2]},{g[3]}))"


def _f4list_lit(s: str) -> str:
    groups = [g for g in s.split(";") if g]
    return "[" + ", ".join(_f4_lit([int(x) for x in g.split(",")]) for g in groups) + "]"


def _intlist_lit(s: str) -> str:
    return "[" + ", ".join(x for x in s.split(";") if x) + "]"


def _layer_lit(layer_s: str) -> str:
    cw_s, dom_s, root_s, beta_s = layer_s.split("#")
    beta = [int(x) for x in beta_s.split(",")]
    return f"Layer({_f4list_lit(cw_s)}, {_intlist_lit(dom_s)}, {root_s}, {_f4_lit(beta)})"


# --- verifier: reconstruct from the transcript ONLY, re-run fri_verify --------
def verifier_driver(fields: dict, public_c: str | None = None) -> str:
    nv = [int(x) for x in fields["NV"].split(",")]
    layers_lit = "[" + ", ".join(
        _layer_lit(l) for l in fields["LAYERS"].split("||") if l
    ) + "]"
    final_lit = _f4list_lit(fields["FINAL"])
    c = public_c if public_c is not None else fields["PUBLIC_C"]
    tail = f"""
# --- research spike VERIFIER: reconstructed from the serialized proof only ---
# No witness, no table, no circuit — only the transcript the prover published.
let __nv : F2 = F2({nv[0]}, {nv[1]})
let __nw : Int = {fields["NW"]}
let __layers : List<Layer> = {layers_lit}
let __final : List<F4> = {final_lit}
let __qs : List<Int> = sample_queries(transcript_seed(__layers, 0), 24, {fields["DSIZE"]})
let _ : String = print("CLAIMED_C={c}  CLAIMED_R={fields["PUBLIC_R"]}")
let _ : String = print("GPI_VERIFY=" ++ (if fri_verify(__layers, __final, __qs, __nv, __nw) then "ACCEPT" else "REJECT"))
"spike-verifier"
"""
    return _machinery() + tail


def _verdict(out: str) -> str:
    for line in out.splitlines():
        if line.startswith("GPI_VERIFY="):
            return line.split("=", 1)[1]
    return "?"


def main() -> None:
    print("=== Witness-free FRI re-verification — RESEARCH SPIKE ===")
    print("(demonstration of mechanics; NOT sound third-party verification — see module docstring)\n")

    print("1. PROVER builds a blinded F_{p^4} FRI STARK for SUM over a committed")
    print("   private column, and serializes the proof transcript...")
    out = run_driver(prover_driver())
    fields = _parse_fields(out)
    nlayers = len([x for x in fields["LAYERS"].split("||") if x])
    size = len(fields["LAYERS"]) + len(fields["FINAL"])
    print(f"   public: C={fields['PUBLIC_C']}  R={fields['PUBLIC_R']}")
    print(f"   serialized proof: {nlayers} FRI layers, ~{size} bytes (witness NOT included)\n")

    print("2. VERIFIER reconstructs the transcript from those bytes ONLY (no witness)")
    print("   and re-runs Glass's fri_verify low-degree test...")
    vout = run_driver(verifier_driver(fields))
    print(f"   witness-free verdict: {_verdict(vout)}\n")

    print("3. INTEGRITY: corrupt one field element in the serialized proof -> expect REJECT")
    bad = dict(fields)
    # flip the first coordinate of the final codeword's first element
    parts = bad["FINAL"].split(";")
    g = parts[0].split(",")
    g[0] = str((int(g[0]) + 1))
    parts[0] = ",".join(g)
    bad["FINAL"] = ";".join(parts)
    bout = run_driver(verifier_driver(bad))
    print(f"   corrupted verdict: {_verdict(bout)}\n")

    print("4. THE GAP (honest): the verifier never consulted C or R. Re-run it with a")
    print("   DIFFERENT claimed commitment — the FRI low-degree test is unchanged...")
    gout = run_driver(verifier_driver(fields, public_c="999999999"))
    print(f"   verdict with a bogus claimed C: {_verdict(gout)}")
    print("   -> a low-degree codeword is necessary but NOT sufficient: this check does")
    print("      not bind the proof to (C, R). Sound witness-free verification needs a")
    print("      trace commitment + query openings + out-of-circuit gate-identity checks.\n")

    print("5. THE BLOCKER toward soundness (worked out here):")
    print("   The trace commitment + openings are ordinary plumbing (reuse the F4 Merkle).")
    print("   The hard part is the ZK blinding: qcode commits q(x)+blind(x), and the")
    print("   verifier can't recover the gate value G(x) without the secret blind(x) —")
    print("   while revealing blind would break zero-knowledge. A sound+ZK verifier needs")
    print("   a corrected construction (e.g. a vanishing blind q + Z_H*blind), which is a")
    print("   protocol change to the STARK — genuine zk-STARK research, not just plumbing.\n")

    ok = _verdict(vout) == "ACCEPT" and _verdict(bout) == "REJECT"
    print("=== spike", "DEMONSTRATED" if ok else "INCONCLUSIVE", "===")


if __name__ == "__main__":
    main()
