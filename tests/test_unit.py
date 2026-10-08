"""Fast unit tests (no Glass engine required).

Covers schema encoding, the SQL parser, storage + auth, and the registry's
request handling including tenant isolation.

  python3.12 -m unittest tests.test_unit
"""

from __future__ import annotations

import os
import tempfile
import time
import unittest

# Keep the registry database out of the home directory: config reads this at import.
os.environ.setdefault("TIRESIAS_DB", os.path.join(tempfile.mkdtemp(prefix="tiresias-test-"), "registry.db"))

from tiresias.engine.commit import Manifest
from tiresias.engine.prover import _check_field_capacity, _check_ranges
from tiresias.engine.schema import (
    Column,
    ColType,
    Dataset,
    TiresiasFieldError,
    TiresiasRangeError,
)
from tiresias.query.pane_ast import Table, _gstr
from tiresias.query import sql
from tiresias.query.pane_ast import Col, GtE, LitI
from tiresias.query.spec import (
    AGG_AVG,
    AGG_COUNT,
    AGG_GROUPBY,
    AGG_MAX,
    AGG_MIN,
    AGG_SUM,
    QuerySpec,
)
from tiresias.registry import auth
from tiresias.registry.store import Store


def _manifest() -> Manifest:
    return Manifest(
        dataset_id="ds_test",
        name="t",
        schema=[
            {"name": "dept", "type": "category", "categories": {"eng": 0, "sales": 1}},
            {"name": "salary", "type": "int", "categories": {}},
            {"name": "remote", "type": "bool", "categories": {}},
        ],
        gamma=918273645,
        commitment=12345,
        row_count=3,
        created_at=time.time(),
    )


class TestInference(unittest.TestCase):
    def test_infer_types(self):
        from tiresias.engine.schema import infer_types

        headers = ["dept", "level", "salary", "remote", "note"]
        rows = [
            {"dept": "eng", "level": "5", "salary": "185000", "remote": "true", "note": ""},
            {"dept": "sales", "level": "3", "salary": "120000", "remote": "no", "note": "x"},
        ]
        t = infer_types(headers, rows)
        self.assertEqual(t["dept"].value, "category")
        self.assertEqual(t["level"].value, "int")
        self.assertEqual(t["salary"].value, "int")
        self.assertEqual(t["remote"].value, "bool")
        self.assertEqual(t["note"].value, "category")  # one non-empty string value

    def test_from_csv_infers(self):
        import os

        ds = Dataset.from_csv(
            os.path.join(os.path.dirname(__file__), "..", "examples", "payroll.csv")
        )
        types = {c.name: c.type.value for c in ds.columns}
        self.assertEqual(types["dept"], "category")
        self.assertEqual(types["remote"], "bool")
        self.assertEqual(types["salary"], "int")


class TestSchema(unittest.TestCase):
    def test_encodings(self):
        ci = Column("salary", ColType.INT)
        self.assertEqual(ci.encode("100"), 100)
        cb = Column("remote", ColType.BOOL)
        self.assertEqual(cb.encode("true"), 1)
        self.assertEqual(cb.encode("no"), 0)
        cc = Column("dept", ColType.CATEGORY)
        self.assertEqual(cc.encode("eng"), 0)
        self.assertEqual(cc.encode("sales"), 1)
        self.assertEqual(cc.encode("eng"), 0)  # stable

    def test_overflow_rejected(self):
        with self.assertRaises(ValueError):
            Column("x", ColType.INT).encode(10**12)
        with self.assertRaises(ValueError):
            Column("x", ColType.INT).encode(-5)


class TestSqlParser(unittest.TestCase):
    def setUp(self):
        self.m = _manifest()

    def test_sum_with_category_filter(self):
        spec = sql.parse("SELECT SUM(salary) WHERE dept = 'eng'", self.m)
        self.assertEqual(spec.agg, AGG_SUM)
        self.assertEqual(spec.column, "salary")
        self.assertIn("EqE", spec.predicate.to_glass())
        self.assertIn("LitI(0)", spec.predicate.to_glass())  # 'eng' -> 0

    def test_count_and_avg(self):
        self.assertEqual(sql.parse("SELECT COUNT(*)", self.m).agg, AGG_COUNT)
        self.assertEqual(sql.parse("SELECT AVG(salary)", self.m).agg, AGG_AVG)

    def test_range_and_boolean(self):
        spec = sql.parse(
            "SELECT SUM(salary) WHERE salary > 100 AND remote = 'true'", self.m
        )
        g = spec.predicate.to_glass()
        self.assertIn("AndE", g)
        self.assertIn("GtE", g)

    def test_bad_query(self):
        with self.assertRaises(sql.SqlError):
            sql.parse("DELETE FROM t", self.m)
        with self.assertRaises(sql.SqlError):
            sql.parse("SELECT SUM(*)", self.m)

    def test_min_max(self):
        self.assertEqual(sql.parse("SELECT MIN(salary)", self.m).agg, AGG_MIN)
        self.assertEqual(sql.parse("SELECT MAX(salary)", self.m).agg, AGG_MAX)

    def test_group_by(self):
        spec = sql.parse("SELECT dept, SUM(salary) GROUP BY dept", self.m)
        self.assertEqual(spec.agg, AGG_GROUPBY)
        self.assertEqual(spec.group_key, "dept")
        self.assertEqual(spec.column, "salary")
        # GROUP BY on a non-categorical column is refused
        with self.assertRaises(sql.SqlError):
            sql.parse("SELECT SUM(salary) GROUP BY salary", self.m)


class TestRangeGuard(unittest.TestCase):
    def _ds(self):
        return Dataset(
            columns=[Column("level", ColType.INT), Column("salary", ColType.INT)],
            rows=[[2, 90000], [6, 210000]],
        )

    def test_comparison_columns(self):
        spec = QuerySpec(agg=AGG_SUM, column="salary",
                         predicate=GtE(Col("salary"), LitI(100)))
        self.assertEqual(spec.comparison_columns(), {"salary"})
        self.assertEqual(
            QuerySpec(agg=AGG_MIN, column="level", predicate=None).comparison_columns(),
            {"level"},
        )

    def test_range_guard(self):
        ds = self._ds()
        # MIN on a small-domain column is fine
        _check_ranges(ds, QuerySpec(agg=AGG_MIN, column="level", predicate=None))
        # MIN on out-of-range values is refused with a clear error
        with self.assertRaises(TiresiasRangeError):
            _check_ranges(ds, QuerySpec(agg=AGG_MIN, column="salary", predicate=None))
        # a > filter on out-of-range values is refused too
        with self.assertRaises(TiresiasRangeError):
            _check_ranges(
                ds, QuerySpec(agg=AGG_SUM, column="level",
                              predicate=GtE(Col("salary"), LitI(100))),
            )


class TestFieldCapacity(unittest.TestCase):
    def test_oversized_sum_refused(self):
        # three values near the safe max -> total exceeds the field prime
        big = 1_000_000_000
        ds = Dataset(columns=[Column("amt", ColType.INT)],
                     rows=[[big], [big], [big]])
        with self.assertRaises(TiresiasFieldError):
            _check_field_capacity(ds, QuerySpec(agg=AGG_SUM, column="amt", predicate=None))

    def test_normal_sum_ok(self):
        ds = Dataset(columns=[Column("amt", ColType.INT)],
                     rows=[[185000], [150000], [210000]])
        _check_field_capacity(ds, QuerySpec(agg=AGG_SUM, column="amt", predicate=None))
        # COUNT has no summed column, so never triggers
        _check_field_capacity(ds, QuerySpec(agg=AGG_COUNT, column=None, predicate=None))


class TestSourceEscaping(unittest.TestCase):
    def test_gstr_escapes_control_and_quotes(self):
        s = _gstr('a"b\\c\nd\te')
        self.assertNotIn("\n", s)  # raw newline must not survive
        self.assertNotIn("\t", s)
        self.assertIn('\\"', s)
        self.assertIn("\\\\", s)
        self.assertIn("\\n", s)

    def test_malicious_column_name_stays_quoted(self):
        # a header trying to break out of the Pair("...", ...) wrapper
        evil = '"),Pair("x'
        glass = Table(columns=[evil], rows=[[1]]).to_glass()
        # the injected quote is escaped, so it cannot start a new Pair
        self.assertIn('\\"', glass)
        self.assertNotIn('"),Pair("x"', glass)


class TestStoreAuth(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.store = Store(os.path.join(self.tmp, "r.db"))

    def tearDown(self):
        self.store.close()

    def test_key_not_stored_plaintext(self):
        org = self.store.create_org("Acme")
        key = self.store.issue_key(org, "laptop")
        self.assertTrue(auth.key_looks_valid(key))
        self.assertEqual(self.store.org_for_key(key), org)
        self.assertIsNone(self.store.org_for_key("tir_live_wrong"))
        # the raw key must not appear anywhere in the DB file
        with open(os.path.join(self.tmp, "r.db"), "rb") as f:
            self.assertNotIn(key.encode(), f.read())

    def test_tenant_isolation(self):
        a = self.store.create_org("A")
        b = self.store.create_org("B")
        man = {"dataset_id": "ds1", "commitment": 9, "gamma": 1, "schema": [], "name": "x"}
        self.store.put_manifest(a, man)
        self.assertIsNotNone(self.store.get_manifest(a, "ds1"))
        self.assertIsNone(self.store.get_manifest(b, "ds1"))  # B cannot see A's data
        self.assertEqual(len(self.store.list_manifests(b)), 0)

    def test_key_revocation(self):
        org = self.store.create_org("Acme")
        key = self.store.issue_key(org, "laptop")
        self.assertEqual(self.store.org_for_key(key), org)

        keys = self.store.list_keys(org)
        self.assertEqual(len(keys), 1)
        self.assertNotIn("key", keys[0])  # never exposes plaintext or hash
        self.assertNotIn("key_hash", keys[0])
        self.assertFalse(keys[0]["revoked"])
        kid = keys[0]["key_id"]

        self.assertTrue(self.store.revoke_key(kid, org_id=org))
        self.assertIsNone(self.store.org_for_key(key))  # revoked key rejected
        self.assertFalse(self.store.revoke_key(kid, org_id=org))  # already revoked

    def test_revoke_is_org_scoped(self):
        a = self.store.create_org("A")
        b = self.store.create_org("B")
        self.store.issue_key(b, "b-key")
        b_kid = self.store.list_keys(b)[0]["key_id"]
        # org A cannot revoke org B's key
        self.assertFalse(self.store.revoke_key(b_kid, org_id=a))


class TestRegistryHandle(unittest.TestCase):
    def setUp(self):
        from tiresias.registry import server

        self.server = server
        self.tmp = tempfile.mkdtemp()
        server.STORE = Store(os.path.join(self.tmp, "r.db"))
        self.org = server.STORE.create_org("Acme")
        self.other = server.STORE.create_org("Other")

    def tearDown(self):
        self.server.STORE.close()

    def _manifest_dict(self):
        return {
            "dataset_id": "ds_x", "name": "x", "commitment": 514343249,
            "gamma": 918273645, "schema": [], "row_count": 8, "created_at": time.time(),
            "engine_version": "t", "crypto_grade": "educational", "disclosure": "d",
        }

    def _bundle_dict(self, commitment=514343249):
        return {
            "bundle_id": "pb_x", "dataset_id": "ds_x", "commitment": commitment,
            "gamma": 918273645, "query": "SELECT SUM(salary)", "result": {"value": 350000},
            "accepted": True, "created_at": time.time(), "engine_version": "t",
            "crypto_grade": "educational", "disclosure": "d",
        }

    def test_register_and_bind(self):
        code, _ = self.server.handle("POST", "/api/manifests", self.org, self._manifest_dict())
        self.assertEqual(code, 200)
        code, payload = self.server.handle("POST", "/api/bundles", self.org, self._bundle_dict())
        self.assertEqual(code, 200)
        self.assertTrue(payload["verification"]["ok"])  # binds to published commitment

    def test_wrong_commitment_rejected(self):
        self.server.handle("POST", "/api/manifests", self.org, self._manifest_dict())
        code, payload = self.server.handle(
            "POST", "/api/bundles", self.org, self._bundle_dict(commitment=999)
        )
        self.assertEqual(code, 200)
        self.assertFalse(payload["verification"]["ok"])  # binding fails

    def test_bundle_without_manifest_rejected(self):
        from tiresias.registry.server import ApiError

        with self.assertRaises(ApiError):
            self.server.handle("POST", "/api/bundles", self.org, self._bundle_dict())

    def test_self_service_keys(self):
        self.server.STORE.issue_key(self.org, "laptop")
        _, listed = self.server.handle("GET", "/api/keys", self.org, {})
        self.assertEqual(len(listed["keys"]), 1)
        kid = listed["keys"][0]["key_id"]
        _, rev = self.server.handle("DELETE", f"/api/keys/{kid}", self.org, {})
        self.assertTrue(rev["revoked"])
        _, again = self.server.handle("GET", "/api/keys", self.org, {})
        self.assertTrue(again["keys"][0]["revoked"])


class TestAdmin(unittest.TestCase):
    def setUp(self):
        from tiresias.registry import server

        self.server = server
        self.tmp = tempfile.mkdtemp()
        server.STORE = Store(os.path.join(self.tmp, "r.db"))

    def tearDown(self):
        self.server.STORE.close()

    def test_admin_token_check(self):
        self.assertFalse(auth.admin_token_ok("anything", ""))  # disabled when blank
        self.assertFalse(auth.admin_token_ok("", "secret"))
        self.assertFalse(auth.admin_token_ok("wrong", "secret"))
        self.assertTrue(auth.admin_token_ok("secret", "secret"))

    def test_admin_provision_and_revoke(self):
        _, org = self.server.handle_admin("POST", "/api/admin/orgs", {"name": "Acme"})
        org_id = org["org_id"]
        _, k = self.server.handle_admin(
            "POST", f"/api/admin/orgs/{org_id}/keys", {"label": "ci"}
        )
        key = k["api_key"]
        self.assertEqual(self.server.STORE.org_for_key(key), org_id)

        _, listing = self.server.handle_admin(
            "GET", f"/api/admin/orgs/{org_id}/keys", {}
        )
        kid = listing["keys"][0]["key_id"]

        _, rev = self.server.handle_admin("DELETE", f"/api/admin/keys/{kid}", {})
        self.assertTrue(rev["revoked"])
        self.assertIsNone(self.server.STORE.org_for_key(key))  # revoked key dead

    def test_admin_unknown_org(self):
        from tiresias.registry.server import ApiError

        with self.assertRaises(ApiError):
            self.server.handle_admin("POST", "/api/admin/orgs/org_nope/keys", {})


class TestHardening(unittest.TestCase):
    def test_rate_limiter(self):
        from tiresias.registry.server import RateLimiter

        rl = RateLimiter(2)
        self.assertTrue(rl.allow("k"))
        self.assertTrue(rl.allow("k"))
        self.assertFalse(rl.allow("k"))          # third in window denied
        self.assertTrue(rl.allow("other"))       # limit is per-key
        self.assertTrue(RateLimiter(0).allow("x"))  # 0 disables limiting

    def test_pagination_and_stats(self):
        tmp = tempfile.mkdtemp()
        store = Store(os.path.join(tmp, "r.db"))
        try:
            org = store.create_org("Acme")
            for i in range(3):
                store.put_manifest(org, {"dataset_id": f"ds{i}", "commitment": i,
                                         "gamma": 1, "schema": [], "name": f"d{i}"})
            self.assertEqual(len(store.list_manifests(org, limit=2)), 2)
            self.assertEqual(len(store.list_manifests(org, limit=2, offset=2)), 1)
            self.assertEqual(store.stats(org)["datasets"], 3)
        finally:
            store.close()

    def test_global_stats_and_metrics(self):
        from tiresias.registry import server

        tmp = tempfile.mkdtemp()
        server.STORE = Store(os.path.join(tmp, "r.db"))
        try:
            org = server.STORE.create_org("Acme")
            server.STORE.put_manifest(org, {"dataset_id": "ds0", "commitment": 1,
                                            "gamma": 1, "schema": [], "name": "d"})
            gs = server.STORE.global_stats()
            self.assertEqual(gs["orgs"], 1)
            self.assertEqual(gs["datasets"], 1)
            text = server.metrics_text()
            self.assertIn("# TYPE tiresias_datasets gauge", text)
            self.assertIn("tiresias_datasets 1", text)
        finally:
            server.STORE.close()

    def test_handle_pagination_query(self):
        from tiresias.registry import server

        tmp = tempfile.mkdtemp()
        server.STORE = Store(os.path.join(tmp, "r.db"))
        try:
            org = server.STORE.create_org("Acme")
            for i in range(3):
                server.STORE.put_manifest(org, {"dataset_id": f"ds{i}", "commitment": i,
                                                "gamma": 1, "schema": [], "name": f"d{i}"})
            _, payload = server.handle("GET", "/api/manifests", org, {}, {"limit": "1"})
            self.assertEqual(len(payload["manifests"]), 1)
        finally:
            server.STORE.close()


class TestShares(unittest.TestCase):
    def setUp(self):
        from tiresias.registry import server

        self.server = server
        self.tmp = tempfile.mkdtemp()
        server.STORE = Store(os.path.join(self.tmp, "r.db"))
        self.org = server.STORE.create_org("Acme")
        man = {
            "dataset_id": "ds_x", "name": "x", "commitment": 514343249,
            "gamma": 918273645, "schema": [], "row_count": 8, "created_at": time.time(),
            "engine_version": "t", "crypto_grade": "educational", "disclosure": "d",
        }
        bundle = {
            "bundle_id": "pb_x", "dataset_id": "ds_x", "commitment": 514343249,
            "gamma": 918273645, "query": "SELECT SUM(salary)", "result": {"value": 350000},
            "accepted": True, "created_at": time.time(), "engine_version": "t",
            "crypto_grade": "educational", "disclosure": "d",
        }
        server.handle("POST", "/api/manifests", self.org, man)
        server.handle("POST", "/api/bundles", self.org, bundle)

    def tearDown(self):
        self.server.STORE.close()

    def test_share_and_public_view(self):
        _, resp = self.server.handle("POST", "/api/bundles/pb_x/share", self.org, {})
        token = resp["token"]
        payload = self.server.public_share_payload(token)  # public, no auth
        self.assertEqual(payload["bundle"]["bundle_id"], "pb_x")
        self.assertTrue(payload["verification"]["ok"])  # binding holds
        self.assertNotIn("rows", payload["bundle"])  # never any rows

    def test_unknown_share_token(self):
        from tiresias.registry.server import ApiError

        with self.assertRaises(ApiError):
            self.server.public_share_payload("shr_does_not_exist")


if __name__ == "__main__":
    unittest.main()
