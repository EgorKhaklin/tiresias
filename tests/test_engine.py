"""End-to-end engine tests: real proofs in the RISC Zero zkVM.

Slow: each proof takes about a minute. Needs tiresias-prover (cargo build
--release in zkvm/) and RISC Zero's r0vm (rzup install r0vm 3.0.6).

  python3.12 -m unittest tests.test_engine
"""

from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout

_TMP = tempfile.mkdtemp(prefix="tiresias-test-")
os.environ.setdefault("TIRESIAS_DB", os.path.join(_TMP, "registry.db"))
os.environ.setdefault("TIRESIAS_OPENINGS", os.path.join(_TMP, "openings"))

from tiresias.engine import zkvm
from tiresias.engine.commit import commit_dataset, schema_digest
from tiresias.engine.prover import prove
from tiresias.engine.schema import Column, ColType, Dataset
from tiresias.engine.verify import verify_bundle
from tiresias.query import sql


def _dataset() -> Dataset:
    # dept, delta: negative values, and a group too small to answer about
    rows = [[0, 120], [0, -30], [0, 75], [1, -40], [1, -41], [1, 7], [2, 5]]
    return Dataset(
        columns=[Column("dept", ColType.CATEGORY, {"eng": 0, "ops": 1, "hr": 2}), Column("delta", ColType.INT)],
        rows=[list(r) for r in rows],
    )


class TestEngine(unittest.TestCase):
    """prove() checks the guest's commitment and answer against Python's own, so
    every proof here is also a check that the two implementations agree."""

    def test_sum_with_negatives_verifies_and_a_forgery_fails(self):
        ds = _dataset()
        m = commit_dataset(ds, "deltas", min_cohort=3)
        b = prove(ds, sql.parse("SELECT SUM(delta) WHERE dept != 'hr' AND delta <= 75", m), m)
        self.assertEqual(b.result, {"value": -29, "cohort": 5})
        self.assertTrue(verify_bundle(b, m).ok)
        b.result["value"] = 0
        self.assertFalse(verify_bundle(b, m).ok)

    def test_avg_floors_like_the_plain_evaluation(self):
        ds = _dataset()
        m = commit_dataset(ds, "deltas", min_cohort=3)
        b = prove(ds, sql.parse("SELECT AVG(delta) WHERE dept = 'ops'", m), m)
        self.assertEqual(b.result, {"sum": -74, "count": 3, "avg": -25, "cohort": 3})
        self.assertTrue(verify_bundle(b, m).ok)

    def test_the_guest_refuses_a_small_cohort_itself(self):
        # Straight to the guest, past the Python check: no receipt can be made.
        ds = _dataset()
        m = commit_dataset(ds, "deltas", min_cohort=3)
        plan = sql.parse("SELECT MAX(delta) WHERE dept = 'hr'", m).plan(m)
        cells = [c for r in ds.rows for c in r]
        with self.assertRaises(zkvm.Refused) as e:
            zkvm.prove(ds.salt, schema_digest(m.schema), 2, cells, plan)
        self.assertIn("minimum cohort", str(e.exception))


class TestCli(unittest.TestCase):
    def test_commit_query_verify(self):
        from tiresias import cli

        tmp = tempfile.mkdtemp()
        csv = os.path.join(os.path.dirname(__file__), "..", "examples", "payroll.csv")
        man = os.path.join(tmp, "m.json")
        out = os.path.join(tmp, "b.json")
        with redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(["commit", csv, "--types", "dept=category,remote=bool",
                                       "--min-cohort", "3", "-o", man]), 0)
            self.assertEqual(cli.main(["query", man, "SELECT COUNT(*) WHERE level >= 3", "--data", csv, "-o", out]), 0)
            self.assertEqual(cli.main(["verify", out, "--manifest", man]), 0)
        with open(out) as f:
            bundle = json.load(f)
        bundle["result"]["value"] += 1
        forged = os.path.join(tmp, "forged.json")
        with open(forged, "w") as f:
            json.dump(bundle, f)
        with redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(["verify", forged, "--manifest", man]), 1)


if __name__ == "__main__":
    unittest.main()
