"""Embedding Glass Private Intelligence in your own code (local, no server).

    python3.12 examples/integration_example.py

This is the snippet a client copies to integrate GPI: commit a private dataset,
prove aggregate queries, and verify the proofs — all in a few calls.
"""

from gpi.sdk import ColType, LocalEngine

CSV = "examples/payroll.csv"
TYPES = {"dept": ColType.CATEGORY, "remote": ColType.BOOL}


def main() -> None:
    eng = LocalEngine()

    # 1. Commit the private dataset -> a public manifest (no rows).
    ds, manifest = eng.commit_csv(CSV, TYPES, name="acme-payroll")
    print(f"committed {manifest.row_count} rows  commitment={manifest.commitment}")

    # 2. Ask aggregate questions; each answer comes with a proof.
    queries = [
        "SELECT SUM(salary) WHERE dept = 'eng'",
        "SELECT COUNT(*) WHERE remote = 'true'",
        "SELECT dept, SUM(salary) GROUP BY dept",
        "SELECT MAX(level)",
    ]
    for q in queries:
        bundle = eng.query(ds, q, manifest)
        ok = eng.verify(bundle, manifest, ds).ok  # reproducible soundness (Tier 2)
        verdict = "ACCEPT" if bundle.accepted else "REJECT"
        print(f"  {q}\n      {bundle.result}  proof={verdict}  verified={ok}")

    print("\nEvery answer is provable and re-verifiable; the rows never left this process.")


if __name__ == "__main__":
    main()
