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

        manifest = commit_dataset(ds, name="t", gamma=918273645)
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


if __name__ == "__main__":
    unittest.main()
