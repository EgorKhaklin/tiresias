"""The end-to-end Tiresias demo.

Scenario: a company holds a confidential payroll. It wants to let an auditor (or
a benchmarking consortium, or a regulator) ask *aggregate* questions and trust
the answers, without ever exposing a single person's salary.

Run:  python3.12 -m tiresias.demo     (or: tiresias demo)
"""

from __future__ import annotations

import copy
import os
import time

from tiresias.engine.commit import commit_dataset
from tiresias.engine.prover import prove
from tiresias.engine.schema import ColType, Dataset
from tiresias.engine.verify import verify_bundle
from tiresias.query import sql
from tiresias.query.spec import CohortTooSmall

CSV = os.path.join(os.path.dirname(__file__), "..", "examples", "payroll.csv")
TYPES = {"dept": ColType.CATEGORY, "remote": ColType.BOOL}

RULE = "=" * 74


def _h(title: str) -> None:
    print("\n" + RULE)
    print(title)
    print(RULE)


def _checks(result) -> None:
    for name, passed, _ in result.checks:
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}")


def run_demo() -> int:
    print(RULE)
    print(" TIRESIAS: verifiable analytics over private data")
    print(RULE)
    print(
        "A company holds a confidential payroll. It wants others to be able to ask\n"
        "aggregate questions and TRUST the answers, without revealing any salary."
    )

    # --- 1. Commit (the company, once) ---------------------------------------
    _h("1. COMMIT: the company publishes a manifest (no rows)")
    ds = Dataset.from_csv(CSV, TYPES)
    # The toy payroll has 8 rows, so its cohort floor is 3 (the default is 5).
    manifest = commit_dataset(ds, name="acme-payroll-2026", min_cohort=3)
    print(f"rows committed : {manifest.row_count}  (the rows themselves stay private)")
    print(f"dataset_id     : {manifest.dataset_id}")
    print(f"commitment     : {manifest.commitment}")
    print(f"schema         : {[c['name'] for c in manifest.schema]}")
    print(f"min cohort     : {manifest.min_cohort} rows per answer")
    print("PUBLISHED: the manifest above. It contains no salary, and the salted")
    print("commitment reveals nothing about them.")

    # --- 2. Query + prove (the data holder) ----------------------------------
    _h("2. QUERY: each answer ships with a RISC Zero receipt")
    queries = [
        "SELECT AVG(salary) WHERE dept = 'eng'",
        "SELECT dept, SUM(salary) GROUP BY dept",
        "SELECT COUNT(*) WHERE remote = 'true'",
    ]
    by_query = {}
    for s in queries:
        t = time.time()
        b = prove(ds, sql.parse(s, manifest), manifest)
        by_query[s] = b
        print(f"  {s}")
        print(f"      -> {b.result}   proved in {time.time() - t:.0f}s")
    print("\nEach result is a proof BUNDLE: {commitment, query, answer, receipt}.")
    print("It travels to anyone; the rows never do. The 2-row 'ops' group is withheld.")
    small = "SELECT MAX(level) WHERE dept = 'ops'"
    try:
        prove(ds, sql.parse(small, manifest), manifest)
        print(f"  {small}\n      -> answered (unexpected)")
    except CohortTooSmall as e:
        print(f"  {small}\n      -> refused: {e}")

    # --- 3. Verify (the auditor) ---------------------------------------------
    _h("3. VERIFY: an auditor checks a bundle with the manifest, without the data")
    avg = by_query["SELECT AVG(salary) WHERE dept = 'eng'"]
    print(f"Auditor receives the bundle for: {avg.query}")
    r = verify_bundle(avg, manifest)
    _checks(r)
    print(f"  => {'VERIFIED' if r.ok else 'FAILED'}")

    # --- 4. Tamper (the attacker) --------------------------------------------
    _h("4. TAMPER: a forged answer cannot pass")
    forged = copy.deepcopy(avg)
    real = forged.result["avg"]
    forged.result["avg"] = real + 50000
    print(f"Attacker edits the bundle's answer: {real} -> {forged.result['avg']}")
    rt = verify_bundle(forged, manifest)
    _checks(rt)
    print(f"  => {'VERIFIED' if rt.ok else 'REJECTED (as it should be)'}")

    # --- 5. What it rests on -------------------------------------------------
    _h("5. WHAT IT RESTS ON")
    print(
        "  - soundness: the RISC Zero zkVM (audited by Hexens and Veridise) proves the\n"
        "               guest ran on the committed rows; a wrong answer has no receipt\n"
        "  - privacy:   receipts are zero-knowledge (RISC Zero's design; it has not\n"
        "               published a proof of it), the commitment is salted, and no\n"
        "               answer describes fewer rows than the dataset's minimum cohort\n"
        "  - Tiresias's own guest and integration are not yet independently audited\n"
        "               (SECURITY.md)"
    )
    print("\nWho this is for: audits, regulatory reporting, cross-org benchmarking,")
    print("data clean-rooms (anywhere you must SHARE a number but not the data).")
    print(RULE)
    return 0


if __name__ == "__main__":
    raise SystemExit(run_demo())
