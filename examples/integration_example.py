"""Embedding Tiresias in your own code (local, no server).

    python3.12 examples/integration_example.py

This is the snippet a client copies to integrate Tiresias: commit a private dataset,
prove aggregate queries, and verify the proofs, all in a few calls.
"""

from tiresias.sdk import ColType, LocalEngine

CSV = "examples/payroll.csv"
TYPES = {"dept": ColType.CATEGORY, "remote": ColType.BOOL}


def main() -> None:
    eng = LocalEngine()

    # 1. Commit the private dataset -> a public manifest (no rows). The salt that
    #    opens the commitment stays on `ds`, in this process.
    ds, manifest = eng.commit_csv(CSV, TYPES, name="acme-payroll", min_cohort=3)
    print(f"committed {manifest.row_count} rows  commitment={manifest.commitment[:16]}")

    # 2. Ask aggregate questions; each answer comes with a RISC Zero receipt.
    queries = [
        "SELECT COUNT(*) WHERE remote = 'true'",
        "SELECT dept, SUM(salary) GROUP BY dept",
    ]
    for q in queries:
        bundle = eng.query(ds, q, manifest)
        ok = eng.verify(bundle, manifest).ok  # with the manifest only, no data
        print(f"  {q}\n      {bundle.result}  verified={ok}")

    print("\nAnyone with a bundle and the manifest can verify it; the rows never left this process.")


if __name__ == "__main__":
    main()
