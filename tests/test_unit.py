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
            "gamma": 918273645, "schema": [{"name": "salary", "type": "int", "categories": {}}], "row_count": 8, "created_at": time.time(),
            "engine_version": "t", "crypto_grade": "educational", "disclosure": "d",
        }

    def _bundle_dict(self, commitment=514343249):
        return {
            "bundle_id": "pb_x", "dataset_id": "ds_x", "commitment": commitment,
            "gamma": 918273645, "query": "SELECT SUM(salary)", "result": {"value": 350000, "cohort": 8},
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
            "gamma": 918273645, "schema": [{"name": "salary", "type": "int", "categories": {}}], "row_count": 8, "created_at": time.time(),
            "engine_version": "t", "crypto_grade": "educational", "disclosure": "d",
        }
        bundle = {
            "bundle_id": "pb_x", "dataset_id": "ds_x", "commitment": 514343249,
            "gamma": 918273645, "query": "SELECT SUM(salary)", "result": {"value": 350000, "cohort": 8},
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
        env = {"TIRESIAS_GAMMA": "1"}
        self.assertEqual(self.config.problems(env, scope="registry"), [])
        self.assertEqual(len(self.config.problems(env, scope="prover")), 1)

    def test_gamma_bound_matches_the_commitment_field(self):
        from tiresias.engine.schema import FIELD_PRIME
        self.assertEqual(self.config._FIELD_PRIME, FIELD_PRIME)

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


class TestGlassPin(unittest.TestCase):
    """Tiresias proves only with the Glass files it pins."""

    def setUp(self):
        from unittest import mock

        from tiresias.engine import glass_pin

        self.pin = glass_pin
        self.tmp = tempfile.mkdtemp(prefix="tiresias-glass-")
        os.makedirs(os.path.join(self.tmp, "examples", "prove"))
        self.files = {"glass.py": b"MARKER = 'pinned'\n", "examples/prove/prove_pane.glass": b"0\n"}
        for rel, data in self.files.items():
            with open(os.path.join(self.tmp, rel), "wb") as f:
                f.write(data)
        import hashlib

        pins = {rel: hashlib.sha256(data).hexdigest() for rel, data in self.files.items()}
        self.patches = [
            mock.patch.object(glass_pin, "PINNED_FILES", pins),
            mock.patch.object(glass_pin, "_verified_root", None),
            mock.patch.object(glass_pin, "_glass_module", None),
            mock.patch.dict(os.environ, {"TIRESIAS_GLASS_DIR": self.tmp, "TIRESIAS_GLASS_UNPINNED": "0"}),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()

    def test_a_matching_checkout_is_accepted(self):
        self.assertEqual(self.pin.mismatches(self.tmp), [])
        self.assertEqual(self.pin.glass_root(), self.tmp)

    def test_a_changed_file_is_refused_by_name(self):
        with open(os.path.join(self.tmp, "examples", "prove", "prove_pane.glass"), "ab") as f:
            f.write(b"# changed\n")
        with self.assertRaises(self.pin.GlassPinError) as ctx:
            self.pin.glass_root()
        self.assertIn("prove_pane.glass", str(ctx.exception))

    def test_unpinned_allows_a_changed_checkout(self):
        from unittest import mock

        with open(os.path.join(self.tmp, "glass.py"), "ab") as f:
            f.write(b"# changed\n")
        with mock.patch.dict(os.environ, {"TIRESIAS_GLASS_UNPINNED": "1"}):
            self.assertEqual(self.pin.glass_root(), self.tmp)

    def test_the_verified_file_is_loaded_even_if_another_glass_is_imported(self):
        import sys
        import types
        from unittest import mock

        impostor = types.ModuleType("glass")
        impostor.MARKER = "impostor"
        with mock.patch.dict(sys.modules, {"glass": impostor}):
            self.assertEqual(self.pin.load_glass().MARKER, "pinned")

    def test_fetch_clones_the_pinned_tag(self):
        import shutil
        import subprocess

        if shutil.which("git") is None:
            self.skipTest("git not installed")
        env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
        for cmd in (["git", "init", "-q"], ["git", "add", "-A"], ["git", "commit", "-qm", "glass"], ["git", "tag", "v-test"]):
            subprocess.run(cmd, cwd=self.tmp, check=True, env=env, capture_output=True)
        target = os.path.join(tempfile.mkdtemp(prefix="tiresias-fetch-"), "glass", "v-test")
        self.pin.fetch_release(target, repository=self.tmp, tag="v-test")
        self.assertEqual(self.pin.mismatches(target), [])

    def test_an_unreachable_release_is_a_clear_error(self):
        import shutil

        if shutil.which("git") is None:
            self.skipTest("git not installed")
        target = os.path.join(tempfile.mkdtemp(prefix="tiresias-fetch-"), "glass", "v-none")
        with self.assertRaises(self.pin.GlassPinError):
            self.pin.fetch_release(target, repository=os.path.join(self.tmp, "no-such-repo"), tag="v-none")


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

        body = _json.dumps({"dataset_id": ["x"], "commitment": 1, "gamma": 1, "schema": []}).encode()
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


class TestCohortPolicy(unittest.TestCase):
    """Tier 1 checks, from public data alone, that every answer meets min_cohort."""

    def manifest(self, k=5):
        return Manifest(
            dataset_id="ds_c", name="c",
            schema=[
                {"name": "dept", "type": "category", "categories": {"eng": 0, "ops": 1}},
                {"name": "salary", "type": "int", "categories": {}},
            ],
            gamma=918273645, commitment=7, row_count=12, created_at=0.0, min_cohort=k,
        )

    def bundle(self, query, result):
        from tiresias.engine.bundle import ProofBundle

        return ProofBundle(
            bundle_id="pb_c", dataset_id="ds_c", commitment=7, gamma=918273645,
            query=query, result=result, accepted=True, created_at=0.0,
        )

    def tier1(self, query, result, k=5):
        from tiresias.engine.verify import verify_bundle

        return verify_bundle(self.bundle(query, result), self.manifest(k))

    def test_a_large_enough_cohort_passes(self):
        self.assertTrue(self.tier1("SELECT SUM(salary)", {"value": 10, "cohort": 5}).ok)

    def test_a_small_or_missing_cohort_fails(self):
        self.assertFalse(self.tier1("SELECT SUM(salary)", {"value": 10, "cohort": 4}).ok)
        self.assertFalse(self.tier1("SELECT SUM(salary)", {"value": 10}).ok)

    def test_a_count_must_equal_its_cohort(self):
        self.assertTrue(self.tier1("SELECT COUNT(*)", {"value": 6, "cohort": 6}).ok)
        self.assertFalse(self.tier1("SELECT COUNT(*)", {"value": 6, "cohort": 9}).ok)

    def test_group_by_must_partition_the_categories(self):
        q = "SELECT dept, SUM(salary) GROUP BY dept"
        good = {"group_by": "dept", "column": "salary", "groups": {"eng": 50},
                "cohorts": {"eng": 7}, "suppressed": ["ops"]}
        self.assertTrue(self.tier1(q, good).ok)
        dropped = dict(good, suppressed=[])  # ops silently missing
        self.assertFalse(self.tier1(q, dropped).ok)
        small = dict(good, cohorts={"eng": 2})
        self.assertFalse(self.tier1(q, small).ok)

    def test_the_policy_is_part_of_the_dataset_id(self):
        from tiresias.engine.commit import _dataset_id

        schema = self.manifest().schema
        self.assertNotEqual(_dataset_id(schema, 7, 5), _dataset_id(schema, 7, 3))

    def test_min_cohort_must_be_positive(self):
        from tiresias.engine.commit import commit_dataset

        with self.assertRaises(ValueError):
            commit_dataset(Dataset(columns=[]), name="x", gamma=1, min_cohort=0)


if __name__ == "__main__":
    unittest.main()
