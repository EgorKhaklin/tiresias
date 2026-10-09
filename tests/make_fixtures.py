"""Regenerate tests/fixtures: a manifest and a real proof bundle over the sample payroll.

The unit tests verify this receipt instead of proving one, so they stay fast. Its
image id is the guest's: rebuild the prover reproducibly (the default Docker build)
and the receipt still verifies; change the guest and this must be run again.

  python3.12 -m tests.make_fixtures
"""

from __future__ import annotations

import os

from tiresias.engine.commit import commit_dataset
from tiresias.engine.prover import prove
from tiresias.engine.schema import ColType, Dataset
from tiresias.query import sql

HERE = os.path.dirname(__file__)
CSV = os.path.join(HERE, "..", "examples", "payroll.csv")
OUT = os.path.join(HERE, "fixtures")


def main() -> None:
    ds = Dataset.from_csv(CSV, {"dept": ColType.CATEGORY, "remote": ColType.BOOL})
    manifest = commit_dataset(ds, name="payroll", min_cohort=3)
    bundle = prove(ds, sql.parse("SELECT dept, SUM(salary) GROUP BY dept", manifest), manifest)
    os.makedirs(OUT, exist_ok=True)
    manifest.save(os.path.join(OUT, "payroll.manifest.json"))
    bundle.save(os.path.join(OUT, "payroll.bundle.json"))
    print(f"{manifest.dataset_id}: {bundle.result} (guest {bundle.image_id})")


if __name__ == "__main__":
    main()
