"""Fast unit tests: no proving.

Covers schema encoding, the SQL parser and its plans, the query evaluation the
guest mirrors, commitments and openings, storage and auth, the registry's
request handling including tenant isolation, and verification. Verification
runs the real verifier on a real receipt (tests/fixtures), so tiresias-prover
must be built; regenerate the fixture with `python3.12 -m tests.make_fixtures`.

  python3.12 -m unittest tests.test_unit
"""

from __future__ import annotations

import base64
import json
import os
import tempfile
import time
import unittest

# Keep the registry database and openings out of the home directory: config reads these at import.
_TMP = tempfile.mkdtemp(prefix="tiresias-test-")
os.environ.setdefault("TIRESIAS_DB", os.path.join(_TMP, "registry.db"))
os.environ.setdefault("TIRESIAS_OPENINGS", os.path.join(_TMP, "openings"))

from tiresias.engine.bundle import ProofBundle
from tiresias.engine.commit import Manifest
from tiresias.engine.schema import Column, ColType, Dataset
from tiresias.query import sql
from tiresias.query.spec import (
    AGG_AVG,
    AGG_COUNT,
    AGG_GROUPBY,
    AGG_MAX,
    AGG_MIN,
    AGG_SUM,
    CohortTooSmall,
    Overflow,
    answer,
)
from tiresias.registry import auth
from tiresias.registry.store import Store

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def _manifest() -> Manifest:
    return Manifest(
        dataset_id="ds_test",
        name="t",
        schema=[
            {"name": "dept", "type": "category", "categories": {"eng": 0, "sales": 1}},
            {"name": "salary", "type": "int", "categories": {}},
            {"name": "remote", "type": "bool", "categories": {}},
        ],
        commitment="ab" * 32,
        row_count=3,
        created_at=time.time(),
    )


def fixture_manifest() -> dict:
    with open(os.path.join(FIXTURES, "payroll.manifest.json")) as f:
        return json.load(f)


def fixture_bundle() -> dict:
    with open(os.path.join(FIXTURES, "payroll.bundle.json")) as f:
        return json.load(f)


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
        self.assertEqual(ci.encode("-5"), -5)
        cb = Column("remote", ColType.BOOL)
        self.assertEqual(cb.encode("true"), 1)
        self.assertEqual(cb.encode("no"), 0)
        cc = Column("dept", ColType.CATEGORY)
        self.assertEqual(cc.encode("eng"), 0)
        self.assertEqual(cc.encode("sales"), 1)
        self.assertEqual(cc.encode("eng"), 0)  # stable

    def test_cells_are_64_bit(self):
        Column("x", ColType.INT).encode(2**63 - 1)
        Column("x", ColType.INT).encode(-(2**63))
        with self.assertRaises(ValueError):
            Column("x", ColType.INT).encode(2**63)
        with self.assertRaises(ValueError):
            Column("x", ColType.INT).encode(-(2**63) - 1)


class TestSqlParser(unittest.TestCase):
    def setUp(self):
        self.m = _manifest()

    def plan(self, q):
        return sql.parse(q, self.m).plan(self.m)

    def test_sum_with_category_filter(self):
        spec = sql.parse("SELECT SUM(salary) WHERE dept = 'eng'", self.m)
        self.assertEqual((spec.agg, spec.column), (AGG_SUM, "salary"))
        self.assertEqual(spec.plan(self.m), {
            "aggregate": {"Sum": {"column": 1}},
            "filter": {"Cmp": {"column": 0, "op": "Eq", "value": 0}},  # 'eng' -> 0
            "min_cohort": 5,
        })

    def test_count_and_avg(self):
        self.assertEqual(sql.parse("SELECT COUNT(*)", self.m).agg, AGG_COUNT)
        self.assertEqual(self.plan("SELECT COUNT(*)")["aggregate"], "Count")
        self.assertEqual(self.plan("SELECT AVG(salary)")["aggregate"], {"Avg": {"column": 1}})
        self.assertEqual(sql.parse("SELECT AVG(salary)", self.m).agg, AGG_AVG)

    def test_operators_and_connectives(self):
        f = self.plan("SELECT SUM(salary) WHERE salary > 100 AND remote = 'true' OR salary <= -3")["filter"]
        self.assertEqual(f, {"Or": [
            {"And": [{"Cmp": {"column": 1, "op": "Gt", "value": 100}},
                     {"Cmp": {"column": 2, "op": "Eq", "value": 1}}]},
            {"Cmp": {"column": 1, "op": "Le", "value": -3}}]})
        for op, name in (("=", "Eq"), ("!=", "Ne"), ("<", "Lt"), (">", "Gt"), ("<=", "Le"), (">=", "Ge")):
            self.assertEqual(self.plan(f"SELECT COUNT(*) WHERE salary {op} 7")["filter"]["Cmp"]["op"], name)

    def test_bad_query(self):
        for q in ("DELETE FROM t", "SELECT SUM(*)", "SELECT SUM(salary) WHERE salary = 99999999999999999999"):
            with self.assertRaises(sql.SqlError, msg=q):
                sql.parse(q, self.m)
        with self.assertRaises(KeyError):
            sql.parse("SELECT SUM(salary) WHERE dept = 'nope'", self.m)

    def test_min_max(self):
        self.assertEqual(sql.parse("SELECT MIN(salary)", self.m).agg, AGG_MIN)
        self.assertEqual(sql.parse("SELECT MAX(salary)", self.m).agg, AGG_MAX)
        self.assertEqual(self.plan("SELECT MAX(salary)")["aggregate"], {"Max": {"column": 1}})

    def test_group_by(self):
        spec = sql.parse("SELECT dept, SUM(salary) GROUP BY dept", self.m)
        self.assertEqual((spec.agg, spec.group_key, spec.column), (AGG_GROUPBY, "dept", "salary"))
        self.assertEqual(spec.plan(self.m)["aggregate"],
                         {"GroupSum": {"column": 1, "key": 0, "codes": [0, 1]}})
        with self.assertRaises(sql.SqlError):  # GROUP BY on a non-categorical column
            sql.parse("SELECT SUM(salary) GROUP BY salary", self.m)

    def test_the_plan_carries_the_cohort_floor(self):
        self.m.min_cohort = 9
        self.assertEqual(self.plan("SELECT COUNT(*)")["min_cohort"], 9)


class TestEvaluation(unittest.TestCase):
    """The Python twin of the guest's `answer` (zkvm/core/src/lib.rs), on the same vectors."""

    ROWS = [[0, 100], [0, 200], [0, 300], [1, -50], [1, 70], [2, 9]]

    def run_(self, aggregate, flt=None, k=1, rows=None):
        return answer({"aggregate": aggregate, "filter": flt, "min_cohort": k}, rows or self.ROWS)

    def eq(self, column, value):
        return {"Cmp": {"column": column, "op": "Eq", "value": value}}

    def test_count_sum_avg_min_max(self):
        self.assertEqual(self.run_("Count"), {"Count": {"count": 6}})
        self.assertEqual(self.run_({"Sum": {"column": 1}}, self.eq(0, 0), 3), {"Sum": {"sum": 600, "cohort": 3}})
        self.assertEqual(self.run_({"Avg": {"column": 1}}, self.eq(0, 1), 2), {"Avg": {"sum": 20, "count": 2, "avg": 10}})
        self.assertEqual(self.run_({"Min": {"column": 1}}), {"Min": {"value": -50, "cohort": 6}})
        self.assertEqual(self.run_({"Max": {"column": 1}}), {"Max": {"value": 300, "cohort": 6}})

    def test_avg_floors_toward_negative_infinity(self):
        self.assertEqual(self.run_({"Avg": {"column": 1}}, None, 1, [[1, -7], [1, 0]]),
                         {"Avg": {"sum": -7, "count": 2, "avg": -4}})

    def test_operators(self):
        for op, n in (("Eq", 1), ("Ne", 5), ("Lt", 4), ("Gt", 1), ("Le", 5), ("Ge", 2)):
            got = self.run_("Count", {"Cmp": {"column": 1, "op": op, "value": 200}})
            self.assertEqual(got, {"Count": {"count": n}}, op)
        lt = {"Cmp": {"column": 1, "op": "Lt", "value": 100}}
        self.assertEqual(self.run_("Count", {"Or": [lt, {"Cmp": {"column": 1, "op": "Ge", "value": 300}}]}),
                         {"Count": {"count": 4}})
        self.assertEqual(self.run_("Count", {"And": [lt, {"Not": self.eq(0, 2)}]}), {"Count": {"count": 2}})

    def test_group_by_withholds_small_groups(self):
        got = self.run_({"GroupSum": {"column": 1, "key": 0, "codes": [0, 1, 2]}}, None, 2)
        self.assertEqual(got, {"Groups": {"groups": [{"code": 0, "sum": 600, "cohort": 3},
                                                     {"code": 1, "sum": 20, "cohort": 2}],
                                          "suppressed": [2]}})

    def test_refusals(self):
        with self.assertRaises(CohortTooSmall):
            self.run_({"Sum": {"column": 1}}, self.eq(0, 2), 2)
        with self.assertRaises(Overflow):
            self.run_({"Sum": {"column": 1}}, None, 1, [[0, 2**63 - 1], [0, 1]])


class TestCommitment(unittest.TestCase):
    def dataset(self):
        return Dataset(columns=[Column("dept", ColType.CATEGORY, {"eng": 0}), Column("salary", ColType.INT)],
                       rows=[[0, 100], [0, 200], [0, 300]])

    def test_a_fresh_salt_hides_identical_rows(self):
        from tiresias.engine.commit import commit_dataset

        a, b = self.dataset(), self.dataset()
        ma, mb = commit_dataset(a, "x", min_cohort=1), commit_dataset(b, "x", min_cohort=1)
        self.assertNotEqual(ma.commitment, mb.commitment)
        self.assertEqual(len(ma.commitment), 64)
        self.assertNotIn("100", ma.to_json().replace(ma.commitment, ""))

    def test_the_commitment_binds_every_cell_and_the_schema(self):
        from tiresias.engine.commit import commitment, schema_of

        ds = self.dataset()
        salt = bytes(32)
        base = commitment(salt, schema_of(ds), ds.rows)
        self.assertNotEqual(base, commitment(salt, schema_of(ds), [[0, 100], [0, 200], [0, 301]]))
        self.assertNotEqual(base, commitment(bytes([1]) + bytes(31), schema_of(ds), ds.rows))
        renamed = schema_of(ds)
        renamed[1]["name"] = "pay"
        self.assertNotEqual(base, commitment(salt, renamed, ds.rows))

    def test_the_opening_is_private_and_must_match(self):
        from tiresias.engine.commit import (OpeningMismatch, check_opening, commit_dataset,
                                            load_opening, save_opening)

        ds = self.dataset()
        m = commit_dataset(ds, "x", min_cohort=1)
        path = save_opening(m.dataset_id, ds.salt)
        self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
        self.assertEqual(load_opening(m.dataset_id), ds.salt)
        check_opening(ds, m)
        ds.rows[0][1] += 1
        with self.assertRaises(OpeningMismatch):
            check_opening(ds, m)
        with self.assertRaises(OpeningMismatch):
            load_opening("ds_never_committed")


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
        man = {"dataset_id": "ds1", "commitment": 9, "schema": [], "name": "x"}
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
        return fixture_manifest()

    def _bundle_dict(self):
        return fixture_bundle()

    def test_register_and_verify(self):
        code, _ = self.server.handle("POST", "/api/manifests", self.org, self._manifest_dict())
        self.assertEqual(code, 200)
        code, payload = self.server.handle("POST", "/api/bundles", self.org, self._bundle_dict())
        self.assertEqual(code, 200)
        self.assertTrue(payload["verification"]["ok"], payload["verification"])
        _, listed = self.server.handle("GET", "/api/bundles", self.org, {})
        self.assertNotIn("receipt", listed["bundles"][0])  # listings stay small
        self.assertTrue(listed["bundles"][0]["_verified"])

    def test_a_bundle_against_another_commitment_fails(self):
        other = dict(self._manifest_dict(), commitment="cd" * 32)
        self.server.handle("POST", "/api/manifests", self.org, other)
        code, payload = self.server.handle("POST", "/api/bundles", self.org, self._bundle_dict())
        self.assertEqual(code, 200)
        self.assertFalse(payload["verification"]["ok"])
        failed = [c["name"] for c in payload["verification"]["checks"] if not c["passed"]]
        self.assertEqual(failed, ["proved over the published commitment"])

    def test_a_bundle_needs_a_receipt_and_an_image_id(self):
        from tiresias.registry.server import ApiError

        self.server.handle("POST", "/api/manifests", self.org, self._manifest_dict())
        for change in ({"receipt": None}, {"receipt": "not base64!"}, {"image_id": "xyz"}):
            with self.assertRaises(ApiError, msg=str(change)):
                self.server.handle("POST", "/api/bundles", self.org, {**self._bundle_dict(), **change})
        with self.assertRaises(ApiError):
            self.server.handle("POST", "/api/manifests", self.org, {**self._manifest_dict(), "commitment": 7})

    def test_bundle_without_manifest_rejected(self):
        from tiresias.registry.server import ApiError

        with self.assertRaises(ApiError):
            self.server.handle("POST", "/api/bundles", self.org, self._bundle_dict())

    def test_a_query_that_is_not_tiresias_sql_is_refused(self):
        # A shared page once wrote a bundle's query into the page as HTML. The registry now
        # stores only queries that parse as Tiresias SQL over the bundle's own dataset.
        from tiresias.registry.server import ApiError

        self.server.handle("POST", "/api/manifests", self.org, self._manifest_dict())
        bad = dict(self._bundle_dict(), query="<img src=x onerror=alert(document.domain)>")
        with self.assertRaises(ApiError) as e:
            self.server.handle("POST", "/api/bundles", self.org, bad)
        self.assertEqual(e.exception.status, 400)
        other = dict(self._bundle_dict(), query="SELECT SUM(nope)")
        with self.assertRaises(ApiError):
            self.server.handle("POST", "/api/bundles", self.org, other)

    def test_markup_in_a_dataset_name_or_label_is_refused(self):
        from tiresias.registry.server import ApiError

        for change in ({"name": "<script>alert(1)</script>"},
                       {"schema": [{"name": "dept", "type": "category", "categories": {"<b>x</b>": 0}}]},
                       {"schema": [{"name": "bad name", "type": "int", "categories": {}}]}):
            with self.assertRaises(ApiError, msg=str(change)):
                self.server.handle("POST", "/api/manifests", self.org, {**self._manifest_dict(), **change})

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
                store.put_manifest(org, {"dataset_id": f"ds{i}", "commitment": i, "schema": [], "name": f"d{i}"})
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
            server.STORE.put_manifest(org, {"dataset_id": "ds0", "commitment": 1, "schema": [], "name": "d"})
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
                server.STORE.put_manifest(org, {"dataset_id": f"ds{i}", "commitment": i, "schema": [], "name": f"d{i}"})
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
        self.bundle = fixture_bundle()
        server.handle("POST", "/api/manifests", self.org, fixture_manifest())
        server.handle("POST", "/api/bundles", self.org, self.bundle)

    def tearDown(self):
        self.server.STORE.close()

    def test_share_and_public_view(self):
        bid = self.bundle["bundle_id"]
        _, resp = self.server.handle("POST", f"/api/bundles/{bid}/share", self.org, {})
        payload = self.server.public_share_payload(resp["token"])  # public, no auth
        self.assertEqual(payload["bundle"]["bundle_id"], bid)
        self.assertTrue(payload["verification"]["ok"])
        self.assertNotIn("rows", payload["bundle"])  # never any rows
        # the whole proof and manifest, so anyone can verify it on their own machine
        from tiresias.engine.verify import verify_bundle
        mine = verify_bundle(ProofBundle(**payload["bundle"]), Manifest(**payload["manifest"]))
        self.assertTrue(mine.ok)

    def test_unknown_share_token(self):
        from tiresias.registry.server import ApiError

        with self.assertRaises(ApiError):
            self.server.public_share_payload("shr_does_not_exist")


class TestConfig(unittest.TestCase):
    """Every setting is declared once; a bad one is named, never a traceback."""

    def setUp(self):
        from tiresias import config
        self.config = config

    def test_defaults_have_no_problems(self):
        values, found = self.config.load({})
        self.assertEqual(found, [])
        self.assertEqual(values["PORT"], 8765)
        self.assertEqual(values["REGISTRY_URL"], "http://127.0.0.1:8765")

    def test_malformed_and_out_of_range_values_are_named_and_defaulted(self):
        values, found = self.config.load({"TIRESIAS_PORT": "abc", "TIRESIAS_RATE_PER_MIN": "-1"})
        self.assertEqual(values["PORT"], 8765)
        self.assertEqual(values["RATE_PER_MIN"], 240)
        self.assertTrue(any(p.startswith("TIRESIAS_PORT:") for p in found))
        self.assertTrue(any(p.startswith("TIRESIAS_RATE_PER_MIN:") for p in found))

    def test_admin_token_must_be_empty_or_strong(self):
        _, weak = self.config.load({"TIRESIAS_ADMIN_TOKEN": "secret"})
        _, strong = self.config.load({"TIRESIAS_ADMIN_TOKEN": "x" * 32})
        self.assertTrue(any("ADMIN_TOKEN" in p for p in weak))
        self.assertEqual(strong, [])

    def test_unknown_setting_is_a_problem(self):
        _, found = self.config.load({"TIRESIAS_ADMN_TOKEN": "typo"})
        self.assertEqual(found, ["TIRESIAS_ADMN_TOKEN: not a Tiresias setting (a typo?)"])

    def test_page_size_ordering(self):
        _, found = self.config.load({"TIRESIAS_PAGE_SIZE": "600", "TIRESIAS_MAX_PAGE_SIZE": "500"})
        self.assertTrue(any("MAX_PAGE_SIZE" in p for p in found))

    def test_problems_are_scoped_to_their_reader(self):
        env = {"TIRESIAS_PORT": "x"}
        self.assertEqual(len(self.config.problems(env, scope="registry")), 1)
        self.assertEqual(self.config.problems(env, scope="prover"), [])

    def test_configuration_doc_is_generated_from_the_schema(self):
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "configuration.md")
        with open(path, encoding="utf-8") as f:
            self.assertEqual(f.read(), self.config.render_markdown(),
                             "docs/configuration.md is stale; regenerate it from tiresias.config.render_markdown()")

    def test_serve_refuses_to_start_on_a_bad_setting(self):
        import io
        from contextlib import redirect_stderr
        from unittest import mock
        from tiresias import cli
        err = io.StringIO()
        with mock.patch.dict(os.environ, {"TIRESIAS_PORT": "not-a-port"}), redirect_stderr(err):
            rc = cli.main(["serve"])
        self.assertEqual(rc, 2)
        self.assertIn("TIRESIAS_PORT", err.getvalue())


class TestRegistryHttp(unittest.TestCase):
    """The registry over real HTTP: malformed requests get a 4xx, never a hang or a leak."""

    @classmethod
    def setUpClass(cls):
        import threading
        from http.server import ThreadingHTTPServer

        from tiresias.registry import server

        cls.server_mod = server
        cls.saved = (server.STORE, server.RL, server.IP_RL)
        cls.tmp = tempfile.mkdtemp(prefix="tiresias-http-")
        server.STORE = Store(os.path.join(cls.tmp, "r.db"))
        cls.org = server.STORE.create_org("Acme")
        cls.key = server.STORE.issue_key(cls.org)
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.server_mod.STORE.close()
        cls.server_mod.STORE, cls.server_mod.RL, cls.server_mod.IP_RL = cls.saved

    def setUp(self):
        from tiresias.registry.server import RateLimiter

        self.server_mod.RL = RateLimiter(1000)
        self.server_mod.IP_RL = RateLimiter(1000)

    def request(self, method, path, headers=None, body=b""):
        import http.client
        import json as _json

        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            conn.putrequest(method, path)
            for name, value in (headers or {}).items():
                conn.putheader(name, value)
            conn.endheaders()
            if body:
                conn.send(body)
            resp = conn.getresponse()
            raw = resp.read()
            return resp.status, (_json.loads(raw) if raw else {}), raw
        finally:
            conn.close()

    def auth(self, extra=None):
        return {"Authorization": f"Bearer {self.key}", **(extra or {})}

    def headers(self, path):
        import http.client

        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            conn.request("GET", path)
            resp = conn.getresponse()
            resp.read()
            return resp.status, {k.lower(): v for k, v in resp.getheaders()}
        finally:
            conn.close()

    def test_every_page_runs_under_a_strict_policy(self):
        for path in ("/", "/console", "/v/shr_anything"):
            status, h = self.headers(path)
            self.assertEqual(status, 200, path)
            csp = h["content-security-policy"]
            self.assertIn("script-src 'self'", csp)
            self.assertNotIn("unsafe-inline", csp)
            self.assertIn("frame-ancestors 'none'", csp)
            self.assertEqual(h["x-content-type-options"], "nosniff")

    def test_static_files_are_served_and_contained(self):
        status, h = self.headers("/static/tiresias.css")
        self.assertEqual((status, h["content-type"]), (200, "text/css; charset=utf-8"))
        status, h = self.headers("/static/tiresias-dark.svg")
        self.assertEqual(h["content-security-policy"], "default-src 'none'; style-src 'unsafe-inline'")
        for path in ("/static/../server.py", "/static/x/../../store.py", "/static/missing.js"):
            self.assertNotEqual(self.headers(path)[0], 200, path)

    def test_a_negative_content_length_is_rejected_without_reading(self):
        status, payload, _ = self.request("POST", "/api/manifests", {"Content-Length": "-1"})
        self.assertEqual(status, 400)
        self.assertIn("negative", payload["error"])

    def test_a_non_numeric_content_length_is_rejected(self):
        status, _, _ = self.request("POST", "/api/manifests", {"Content-Length": "abc"})
        self.assertEqual(status, 400)

    def test_the_body_must_be_a_json_object(self):
        body = b"[1, 2, 3]"
        status, payload, _ = self.request(
            "POST", "/api/manifests", self.auth({"Content-Length": str(len(body))}), body
        )
        self.assertEqual(status, 400)
        self.assertIn("JSON object", payload["error"])

    def test_ids_must_be_short_word_strings(self):
        import json as _json

        body = _json.dumps({"dataset_id": ["x"], "commitment": "ab" * 32, "min_cohort": 1, "schema": []}).encode()
        status, payload, _ = self.request(
            "POST", "/api/manifests", self.auth({"Content-Length": str(len(body))}), body
        )
        self.assertEqual(status, 400)
        self.assertIn("dataset_id", payload["error"])

    def test_an_internal_error_reveals_only_an_id(self):
        from unittest import mock

        def boom(*args, **kwargs):
            raise RuntimeError("SECRET /var/lib/tiresias/registry.db")

        with mock.patch.object(self.server_mod.STORE, "list_manifests", boom), \
                self.assertLogs("tiresias.registry", level="ERROR"):
            status, payload, raw = self.request("GET", "/api/manifests", self.auth())
        self.assertEqual(status, 500)
        self.assertEqual(payload["error"], "internal error")
        self.assertRegex(payload["error_id"], r"^[0-9a-f]{16}$")
        self.assertNotIn(b"SECRET", raw)
        self.assertNotIn(b"RuntimeError", raw)

    def test_public_share_lookups_are_limited_per_client(self):
        from tiresias.registry.server import RateLimiter

        self.server_mod.IP_RL = RateLimiter(2)
        statuses = [self.request("GET", "/share/shr_unknown")[0] for _ in range(3)]
        self.assertEqual(statuses, [404, 404, 429])


class TestVerify(unittest.TestCase):
    """The real verifier on a real receipt: each forgery fails, and names its check."""

    def check(self, bundle_change=None, manifest_change=None):
        from tiresias.engine.verify import verify_bundle

        b, m = fixture_bundle(), fixture_manifest()
        if bundle_change:
            bundle_change(b)
        if manifest_change:
            manifest_change(m)
        r = verify_bundle(ProofBundle(**b), Manifest(**m))
        return r.ok, [name for name, passed, _ in r.checks if not passed]

    def test_the_fixture_verifies(self):
        self.assertEqual(self.check(), (True, []))

    def test_the_fixture_is_this_guest(self):
        # Fails when the guest changed, or was not built reproducibly: rebuild in Docker,
        # or regenerate with `python3.12 -m tests.make_fixtures`.
        from tiresias.engine import zkvm

        self.assertEqual(zkvm.image_id(), fixture_bundle()["image_id"])

    def test_the_prover_trusts_the_pinned_guest(self):
        from tiresias.engine import zkvm

        root = os.path.dirname(FIXTURES)
        with open(os.path.join(root, "..", "zkvm", "pinned", "image-id")) as f:
            self.assertEqual(zkvm.image_id(), f.read().strip())

    def test_a_changed_answer_fails(self):
        def inflate(b):
            b["result"]["groups"]["eng"] += 1
        self.assertEqual(self.check(inflate), (False, ["the stated answer is the proved answer"]))

    def test_a_withheld_group_cannot_be_dropped_or_revealed(self):
        def drop(b):
            b["result"]["suppressed"] = []
        def reveal(b):
            b["result"]["groups"]["ops"] = 1
            b["result"]["cohorts"]["ops"] = 3
            b["result"]["suppressed"] = []
        self.assertFalse(self.check(drop)[0])
        self.assertFalse(self.check(reveal)[0])

    def test_a_changed_cohort_fails(self):
        def lie(b):
            b["result"]["cohorts"]["eng"] = 30
        self.assertEqual(self.check(lie), (False, ["the stated answer is the proved answer"]))

    def test_a_different_query_fails(self):
        def other(b):
            b["query"] = "SELECT dept, SUM(level) GROUP BY dept"
        ok, failed = self.check(other)
        self.assertFalse(ok)
        self.assertIn("proved this query, under this dataset's cohort floor", failed)

    def test_a_laxer_cohort_floor_fails(self):
        def lax(m):
            m["min_cohort"] = 2
        ok, failed = self.check(manifest_change=lax)
        self.assertFalse(ok)
        self.assertIn("proved this query, under this dataset's cohort floor", failed)

    def test_another_schema_fails(self):
        def retype(m):
            m["schema"][3]["type"] = "int"  # remote: not in the query, only in the schema
        self.assertEqual(self.check(manifest_change=retype), (False, ["proved under the published schema"]))

    def test_a_receipt_for_another_dataset_fails_cleanly(self):
        def other(m):
            m["schema"][0]["categories"] = {"x": 7}
        ok, failed = self.check(manifest_change=other)
        self.assertFalse(ok)
        self.assertIn("proved this query, under this dataset's cohort floor", failed)
        self.assertIn("the stated answer is the proved answer", failed)

    def test_another_commitment_fails(self):
        def other(m):
            m["commitment"] = "00" * 32
        self.assertEqual(self.check(manifest_change=other), (False, ["proved over the published commitment"]))

    def test_a_damaged_or_missing_receipt_fails(self):
        def flip(b):
            raw = bytearray(base64.b64decode(b["receipt"]))
            raw[len(raw) // 2] ^= 1
            b["receipt"] = base64.b64encode(bytes(raw)).decode()
        def empty(b):
            b["receipt"] = ""
        def garbled(b):
            b["receipt"] = "not base64!"
        for change in (flip, empty, garbled):
            self.assertEqual(self.check(change), (False, ["the receipt verifies"]), change.__name__)

    def test_the_policy_is_part_of_the_dataset_id(self):
        from tiresias.engine.commit import _dataset_id

        schema = fixture_manifest()["schema"]
        self.assertNotEqual(_dataset_id(schema, "ab" * 32, 5), _dataset_id(schema, "ab" * 32, 3))

    def test_min_cohort_must_be_positive(self):
        from tiresias.engine.commit import commit_dataset

        with self.assertRaises(ValueError):
            commit_dataset(Dataset(columns=[Column("a", ColType.INT)], rows=[[1]]), name="x", min_cohort=0)


class TestPageSources(unittest.TestCase):
    """The pages build every node as text and run nothing inline, so a tenant's dataset
    name or query can never become markup or script, even if validation missed it."""

    WEB = os.path.join(os.path.dirname(__file__), "..", "tiresias", "web")
    REG = os.path.join(os.path.dirname(__file__), "..", "tiresias", "registry")

    def test_scripts_never_write_html(self):
        import glob
        import re

        files = glob.glob(os.path.join(self.WEB, "static", "*.js"))
        self.assertGreaterEqual(len(files), 4)
        for f in files:
            with open(f, encoding="utf-8") as fh:
                src = fh.read()
            for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function"):
                self.assertNotIn(sink, src, f"{os.path.basename(f)} uses {sink}")
            self.assertIsNone(re.search(r"setAttribute\(\s*['\"]on", src), f)

    def test_pages_have_no_inline_script_handler_or_style(self):
        import glob
        import re

        pages = glob.glob(os.path.join(self.WEB, "*.html")) + glob.glob(os.path.join(self.REG, "*.html"))
        self.assertGreaterEqual(len(pages), 4)
        for f in pages:
            with open(f, encoding="utf-8") as fh:
                src = fh.read()
            self.assertIsNone(re.search(r"<script(?![^>]*\bsrc=)[^>]*>", src), f"{f}: inline <script>")
            self.assertIsNone(re.search(r"\son[a-z]+\s*=", src), f"{f}: inline handler")
            self.assertIsNone(re.search(r"\sstyle\s*=", src), f"{f}: inline style")
            self.assertNotIn("<style", src, f)


class TestWorkbench(unittest.TestCase):
    """The workbench's CSV handling, before any proof runs."""

    def setUp(self):
        from tiresias.web import server

        self.w = server

    def test_types_are_guessed_from_the_values(self):
        info = self.w.api_inspect({"csv": "dept,level,remote,flag,delta\neng,5,true,1,-3\nops,2,false,0,4\n"})
        self.assertEqual({c["name"]: c["guess"] for c in info["columns"]},
                         {"dept": "category", "level": "int", "remote": "bool", "flag": "bool", "delta": "int"})
        self.assertEqual(info["rows"], 2)
        self.assertEqual(info["preview"][0], ["eng", "5", "true", "1", "-3"])

    def test_malformed_csv_is_refused_with_a_reason(self):
        for text, reason in (("", "header"), ("a,a\n1,2\n", "duplicate"), ("a,b\n1\n", "number of fields"),
                             ("a,b\n", "no rows"), ("bad name,b\n1,2\n", "letters")):
            with self.assertRaises(ValueError) as e:
                self.w.api_inspect({"csv": text})
            self.assertIn(reason, str(e.exception), text)

    def test_the_minimum_cohort_must_fit_the_dataset(self):
        with self.assertRaises(ValueError):
            self.w.api_commit({"csv": "a\n1\n2\n", "types": {"a": "int"}, "min_cohort": 3})
        with self.assertRaises(ValueError):
            self.w.api_commit({"csv": "a\n1\n2\n", "types": {"a": "int"}, "min_cohort": 0})


if __name__ == "__main__":
    unittest.main()
