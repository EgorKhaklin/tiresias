"""End-to-end engine test (requires the Glass engine + python3.12).

Slow: each case runs a real Glass proof. Skipped automatically if the Glass
engine cannot be found.

  python3.12 -m unittest tests.test_engine
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

# Keep the registry database out of the home directory: config reads this at import.
os.environ.setdefault("TIRESIAS_DB", os.path.join(tempfile.mkdtemp(prefix="tiresias-test-"), "registry.db"))

from tiresias.engine import glass_pin

# Runs only against a Glass checkout that is already present and matches the pins;
# the test never fetches.
_GLASS_ROOT = glass_pin.resolve(fetch=False)
GLASS_OK = (
    _GLASS_ROOT is not None
    and sys.version_info >= (3, 10)
    and (not glass_pin.mismatches(_GLASS_ROOT) or os.environ.get("TIRESIAS_GLASS_UNPINNED") == "1")
)


@unittest.skipUnless(GLASS_OK, "pinned Glass checkout not present (run `tiresias glass --fetch`)")
class TestEngineRoundtrip(unittest.TestCase):
    def test_commit_prove_verify_tamper(self):
        from tiresias.engine.commit import commit_dataset
        from tiresias.engine.prover import prove
        from tiresias.engine.schema import Column, ColType, Dataset
        from tiresias.engine.verify import verify_bundle
        from tiresias.query import sql

        ds = Dataset(
            columns=[
                Column("dept", ColType.CATEGORY),
                Column("salary", ColType.INT),
            ],
            rows=[],
        )
        for dept, sal in [("eng", 100), ("sales", 90), ("eng", 150)]:
            ds.rows.append([ds.columns[0].encode(dept), ds.columns[1].encode(sal)])

        manifest = commit_dataset(ds, name="t", gamma=918273645, min_cohort=2)
        spec = sql.parse("SELECT SUM(salary) WHERE dept = 'eng'", manifest)
        bundle = prove(ds, spec, manifest)

        self.assertEqual(bundle.result["value"], 250)  # 100 + 150
        self.assertTrue(bundle.accepted)
        self.assertEqual(bundle.commitment, manifest.commitment)

        # honest bundle verifies (both tiers)
        res = verify_bundle(bundle, manifest, dataset=ds)
        self.assertTrue(res.ok)

        # forged answer is rejected
        import copy

        forged = copy.deepcopy(bundle)
        forged.result["value"] = 999
        self.assertFalse(verify_bundle(forged, manifest, dataset=ds).ok)


def _payroll():
    from tiresias.engine.schema import Column, ColType, Dataset

    ds = Dataset(columns=[Column("dept", ColType.CATEGORY), Column("salary", ColType.INT)], rows=[])
    for dept, sal in [("eng", 100), ("eng", 150), ("eng", 200), ("sales", 90)]:
        ds.rows.append([ds.columns[0].encode(dept), ds.columns[1].encode(sal)])
    return ds


@unittest.skipUnless(GLASS_OK, "pinned Glass checkout not present (run `tiresias glass --fetch`)")
class TestEngineCohorts(unittest.TestCase):
    def setUp(self):
        from tiresias.engine.commit import commit_dataset

        self.ds = _payroll()
        self.manifest = commit_dataset(self.ds, name="p", gamma=918273645, min_cohort=2)

    def test_a_query_about_too_few_rows_is_refused(self):
        from tiresias.engine.prover import prove
        from tiresias.engine.schema import CohortTooSmall
        from tiresias.query import sql

        spec = sql.parse("SELECT MAX(salary) WHERE dept = 'sales'", self.manifest)
        with self.assertRaises(CohortTooSmall):
            prove(self.ds, spec, self.manifest)

    def test_small_groups_are_suppressed_and_verified(self):
        from tiresias.engine.prover import prove
        from tiresias.engine.verify import verify_bundle
        from tiresias.query import sql

        spec = sql.parse("SELECT dept, SUM(salary) GROUP BY dept", self.manifest)
        bundle = prove(self.ds, spec, self.manifest)
        self.assertEqual(bundle.result["groups"], {"eng": 450})
        self.assertEqual(bundle.result["cohorts"], {"eng": 3})
        self.assertEqual(bundle.result["suppressed"], ["sales"])
        self.assertTrue(verify_bundle(bundle, self.manifest, dataset=self.ds).ok)

    def test_a_forged_avg_count_is_rejected(self):
        import copy

        from tiresias.engine.prover import prove
        from tiresias.engine.verify import verify_bundle
        from tiresias.query import sql

        spec = sql.parse("SELECT AVG(salary) WHERE dept = 'eng'", self.manifest)
        bundle = prove(self.ds, spec, self.manifest)
        self.assertEqual((bundle.result["count"], bundle.result["avg"]), (3, 150))
        self.assertTrue(verify_bundle(bundle, self.manifest, dataset=self.ds).ok)
        # A consistent lie about the count: Tier 1 cannot see it, Tier 2 must.
        forged = copy.deepcopy(bundle)
        forged.result.update(count=4, cohort=4, avg=450 // 4)
        self.assertTrue(verify_bundle(forged, self.manifest).ok)
        self.assertFalse(verify_bundle(forged, self.manifest, dataset=self.ds).ok)


if __name__ == "__main__":
    unittest.main()
