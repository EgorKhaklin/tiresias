"""The end-to-end Tiresias demo.

Scenario: a company holds a confidential payroll. It wants to let an auditor (or
a benchmarking consortium, or a regulator) ask *aggregate* questions and trust
the answers, without ever exposing a single person's salary.

Run:  python3.12 -m tiresias.demo     (or: tiresias demo)
"""

from __future__ import annotations

import copy
import os

from tiresias.engine.commit import commit_dataset, load_aligned
from tiresias.engine.prover import prove
from tiresias.engine.schema import CohortTooSmall, ColType, Dataset
from tiresias.engine.verify import verify_bundle
from tiresias.query import sql

GAMMA = 918273645
CSV = os.path.join(os.path.dirname(__file__), "..", "examples", "payroll.csv")
TYPES = {"dept": ColType.CATEGORY, "remote": ColType.BOOL}

RULE = "=" * 74


def _h(title: str) -> None:
    print("\n" + RULE)
    print(title)
    print(RULE)


def run_demo() -> int:
    print(RULE)
    print(" TIRESIAS: verifiable analytics over private data")
    print(RULE)
    print(
        "A company holds a confidential payroll. It wants others to be able to ask\n"
        "aggregate questions and TRUST the answers, without revealing any salary."
    )

    # --- 1. Commit (the company, once) ---------------------------------------
    _h("1. COMMIT: the company publishes a binding manifest (no rows)")
    ds = Dataset.from_csv(CSV, TYPES)
    # The toy payroll has 8 rows, so its cohort floor is 3 (the default is 5).
    manifest = commit_dataset(ds, name="acme-payroll-2026", gamma=GAMMA, min_cohort=3)
    print(f"rows committed : {manifest.row_count}  (the rows themselves stay private)")
    print(f"dataset_id     : {manifest.dataset_id}")
    print(f"commitment     : {manifest.commitment}")
    print(f"schema         : {[c['name'] for c in manifest.schema]}")
    print(f"min cohort     : {manifest.min_cohort} rows per answer")
    print("PUBLISHED: the manifest above. Notice it contains zero salaries.")

    # --- 2. Query + prove (the data-holder) ----------------------------------
    _h("2. QUERY: each answer ships with a proof and its proven cohort")
    queries = [
        "SELECT AVG(salary) WHERE dept = 'eng'",
        "SELECT COUNT(*) WHERE remote = 'true'",
        "SELECT SUM(salary) WHERE level > 3",
        "SELECT dept, SUM(salary) GROUP BY dept",
        "SELECT MAX(level) WHERE dept = 'eng'",
    ]
    by_query = {}
    for s in queries:
        spec = sql.parse(s, manifest)
        b = prove(ds, spec, manifest)
        by_query[s] = b
        verdict = "ACCEPT" if b.accepted else "REJECT"
        print(f"  {s}")
        print(f"      -> {b.result}   proof: {verdict}")
    print("\nEach result is a proof BUNDLE: {commitment, query, answer, cohort, proof}.")
    print("It travels to anyone; the rows never do. The 2-row 'ops' group is suppressed.")
    small = "SELECT MAX(level) WHERE dept = 'ops'"
    try:
        prove(ds, sql.parse(small, manifest), manifest)
        print(f"  {small}\n      -> answered (unexpected)")
    except CohortTooSmall as e:
        print(f"  {small}\n      -> refused: {e}")

    # --- 3. Verify (the auditor) ---------------------------------------------
    _h("3. VERIFY: an auditor checks a bundle against the public manifest")
    sum_bundle = by_query["SELECT SUM(salary) WHERE level > 3"]
    print(f"Auditor receives the bundle for: {sum_bundle.query}")
    print("Tier 1 (binding, no data needed):")
    r1 = verify_bundle(sum_bundle, manifest, dataset=None)
    for name, passed, _ in r1.checks:
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
    print("Tier 2 (reproducible soundness, auditor has the committed data):")
    r2 = verify_bundle(sum_bundle, manifest, dataset=load_aligned(CSV, manifest))
    for name, passed, _ in r2.checks:
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
    print(f"  => {'VERIFIED' if r2.ok else 'FAILED'}")

    # --- 4. Tamper (the attacker) --------------------------------------------
    _h("4. TAMPER: a forged answer cannot pass")
    forged = copy.deepcopy(sum_bundle)
    real = forged.result["value"]
    forged.result["value"] = real + 50000  # inflate the reported payroll
    print(f"Attacker edits the bundle answer: {real} -> {forged.result['value']}")
    rt = verify_bundle(forged, manifest, dataset=load_aligned(CSV, manifest))
    for name, passed, _ in rt.checks:
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
    print(f"  => {'VERIFIED' if rt.ok else 'REJECTED (as it should be)'}")

    # --- 5. Honest maturity + value ------------------------------------------
    _h("5. WHAT THIS IS  (and is not, yet)")
    print(
        "Proven today:\n"
        "  - soundness: the prover cannot lie about an aggregate over committed data\n"
        "  - privacy:   answers reveal the aggregate only, never a row, and never\n"
        "               describe fewer rows than the dataset's minimum cohort\n"
        "  - binding:   every answer is tied to a published, immutable commitment\n"
        "Next (docs/roadmap.md):\n"
        "  - witness-free verification: anyone checks the proof itself, without the data\n"
        "  - an audited proving backend with zero-knowledge; an external audit\n"
        "Cryptography is EDUCATIONAL-GRADE: a working demonstration of the idea,\n"
        "not yet a vault for real secrets. We say so on every artifact, by design."
    )
    print("\nWho this is for: audits, regulatory reporting, cross-org benchmarking,")
    print("data clean-rooms (anywhere you must SHARE a number but not the data).")
    print(RULE)
    return 0


if __name__ == "__main__":
    raise SystemExit(run_demo())
