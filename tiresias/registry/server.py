"""The Tiresias registry server.

Multi-tenant, API-key authenticated, persistent. It accepts manifests and proof
bundles, verifies each bundle's RISC Zero receipt against its manifest (without
the data), and serves a console. It NEVER receives raw data and never proves, so
a compromised registry cannot leak rows it never had. It needs tiresias-prover,
which it runs only to verify.

  python3.12 -m tiresias.registry.server     # http://127.0.0.1:8765
"""

from __future__ import annotations

import json
import os
import re
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from tiresias import __version__, config
from tiresias.engine import zkvm
from tiresias.engine.bundle import ProofBundle
from tiresias.engine.commit import Manifest
from tiresias.engine.verify import verify_bundle
from tiresias.query import sql
from tiresias.registry import auth
from tiresias.registry.store import Store

log = config.get_logger("tiresias.registry")
HERE = os.path.dirname(__file__)
# The design system and page scripts are shared with the workbench (tiresias/web/static).
STATIC = os.path.join(os.path.dirname(HERE), "web", "static")
_STATIC = re.compile(r"^/static/([A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*\.(?:css|js|svg|woff2|txt))$")
_STATIC_TYPES = {"css": "text/css; charset=utf-8", "js": "text/javascript; charset=utf-8",
                 "svg": "image/svg+xml", "woff2": "font/woff2", "txt": "text/plain; charset=utf-8"}
# Every response: no inline script or style, nothing from another origin, never framed.
# Pages build their content as text nodes, so a tenant's dataset name or query cannot
# become markup; the policy is the second line of defence.
SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'none'; script-src 'self'; style-src 'self'; font-src 'self'; "
        "img-src 'self' data:; connect-src 'self'; base-uri 'none'; form-action 'none'; "
        "frame-ancestors 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}
SVG_CSP = "default-src 'none'; style-src 'unsafe-inline'"
_LABEL = re.compile(r"^[^\x00-\x1f\x7f<>]{1,64}$")   # a category label or dataset name: no control characters, no markup
_COLUMN = re.compile(r"^[A-Za-z_]\w{0,63}$")
MAX_QUERY = 2000
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_BASE64 = re.compile(r"^[A-Za-z0-9+/]+={0,2}$")
STORE = Store(config.DB_PATH)

_BUNDLE_VERIFY = re.compile(r"^/api/bundles/([\w]+)/verify$")
_BUNDLE_SHARE = re.compile(r"^/api/bundles/([\w]+)/share$")
_BUNDLE_GET = re.compile(r"^/api/bundles/([\w]+)$")
_MANIFEST_GET = re.compile(r"^/api/manifests/([\w]+)$")
_SHARE_GET = re.compile(r"^/share/([\w]+)$")
_SHARE_VIEW = re.compile(r"^/v/([\w]+)$")
_KEY_DEL = re.compile(r"^/api/keys/([\w]+)$")
_ADMIN_ORG_KEYS = re.compile(r"^/api/admin/orgs/([\w]+)/keys$")
_ADMIN_KEY_DEL = re.compile(r"^/api/admin/keys/([\w]+)$")

# Dataset and bundle ids name database rows and URL path segments, so they are
# held to the same alphabet the routes accept, with a bounded length.
_ID = re.compile(r"^\w{1,128}$")

_REQUIRED_MANIFEST = {"dataset_id", "commitment", "schema", "min_cohort"}
_REQUIRED_BUNDLE = {"bundle_id", "dataset_id", "commitment", "query", "result", "receipt", "image_id"}


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        self.status = status
        self.message = message


class RateLimiter:
    """Fixed-window per-minute limiter keyed by API key / org. In-memory; the
    server is a single process, so this is exact for this deployment."""

    def __init__(self, per_min: int):
        self.per_min = per_min
        self._lock = threading.Lock()
        self._hits: dict[tuple, int] = {}

    def allow(self, key: str) -> bool:
        if self.per_min <= 0:
            return True
        window = int(time.time() // 60)
        with self._lock:
            if len(self._hits) > 10000:  # prune stale windows
                self._hits = {k: v for k, v in self._hits.items() if k[1] >= window - 1}
            k = (key, window)
            count = self._hits.get(k, 0)
            if count >= self.per_min:
                return False
            self._hits[k] = count + 1
            return True


RL = RateLimiter(config.RATE_PER_MIN)
# The unauthenticated surfaces (public share lookups, admin routes) are limited per
# client address instead, with the same per-minute budget.
IP_RL = RateLimiter(config.RATE_PER_MIN)


def _check_manifest(body: dict) -> None:
    """A manifest's tenant-controlled text must be plain: it is shown to other people."""
    name = body.get("name", "")
    if not isinstance(name, str) or (name and not _LABEL.match(name)):
        raise ApiError(400, "name must be 1 to 64 characters, without control characters or < >")
    if not isinstance(body.get("commitment"), str) or not _HEX64.match(body["commitment"]):
        raise ApiError(400, "commitment must be a SHA-256 digest in lowercase hex")
    min_cohort = body.get("min_cohort")
    if not isinstance(min_cohort, int) or isinstance(min_cohort, bool) or min_cohort < 1:
        raise ApiError(400, "min_cohort must be a whole number of at least 1")
    schema = body.get("schema")
    if not isinstance(schema, list) or not schema:
        raise ApiError(400, "schema must be a non-empty list of columns")
    for col in schema:
        if not isinstance(col, dict) or not isinstance(col.get("name"), str) or not _COLUMN.match(col["name"]):
            raise ApiError(400, "each column name must be letters, digits and underscores")
        if col.get("type") not in ("int", "bool", "category"):
            raise ApiError(400, f"column {col['name']!r} has an unknown type")
        cats = col.get("categories") or {}
        if not isinstance(cats, dict) or not all(
                isinstance(k, str) and _LABEL.match(k) and isinstance(v, int) for k, v in cats.items()):
            raise ApiError(400, f"column {col['name']!r} has a malformed category label")


def _check_bundle_query(body: dict, manifest: dict) -> None:
    """A bundle's query must be a query Tiresias proves, over this dataset's columns."""
    query = body.get("query")
    if not isinstance(query, str) or not query.strip() or len(query) > MAX_QUERY:
        raise ApiError(400, f"query must be a non-empty string of at most {MAX_QUERY} characters")
    try:
        sql.parse(query, _reconstruct(Manifest, manifest))
    except (sql.SqlError, KeyError, ValueError) as e:
        raise ApiError(400, f"query is not a Tiresias query over this dataset: {e}") from None
    known = {c["name"] for c in manifest.get("schema", [])}
    named = set(re.findall(r"\(\s*([A-Za-z_]\w*)\s*\)", query))
    named |= set(re.findall(r"\b([A-Za-z_]\w*)\s*(?:<=|>=|!=|=|<|>)", query))
    named |= set(re.findall(r"(?i)\bgroup\s+by\s+([A-Za-z_]\w*)", query))
    unknown = sorted(named - known)
    if unknown:
        raise ApiError(400, f"query names columns this dataset does not have: {unknown}")
    if not isinstance(body.get("result"), dict):
        raise ApiError(400, "result must be an object")
    receipt = body.get("receipt")
    if not isinstance(receipt, str) or not _BASE64.match(receipt):
        raise ApiError(400, "receipt must be a RISC Zero receipt in base64")
    if not isinstance(body.get("image_id"), str) or not _HEX64.match(body["image_id"]):
        raise ApiError(400, "image_id must be a guest image id in lowercase hex")


def _require_id(body: dict, field: str) -> str:
    value = body.get(field)
    if not isinstance(value, str) or not _ID.match(value):
        raise ApiError(400, f"{field} must be 1 to 128 letters, digits or underscores")
    return value


def metrics_text() -> str:
    """Prometheus text-format exposition of instance-wide gauges."""
    s = STORE.global_stats()
    lines = []
    for key, val in s.items():
        name = f"tiresias_{key}"
        lines.append(f"# HELP {name} Instance-wide count of {key}.")
        lines.append(f"# TYPE {name} gauge")
        lines.append(f"{name} {val}")
    return "\n".join(lines) + "\n"


def _page(query: dict) -> tuple[int, int]:
    try:
        limit = min(int(query.get("limit", config.PAGE_SIZE)), config.MAX_PAGE_SIZE)
        offset = int(query.get("offset", 0))
    except (TypeError, ValueError):
        raise ApiError(400, "limit/offset must be integers")
    return max(1, limit), max(0, offset)


def _verify_payload(result) -> dict:
    return {
        "ok": result.ok,
        "tier": result.tier,
        "checks": [
            {"name": n, "passed": p, "detail": d} for (n, p, d) in result.checks
        ],
        "note": result.note,
    }


def _reconstruct(cls, data: dict):
    """Build a dataclass from a dict, tolerating missing optional fields (the
    registry only needs the binding fields, not every metadata field)."""
    fields = cls.__dataclass_fields__
    kwargs = {k: data[k] for k in fields if k in data}
    # supply harmless defaults for any required field the payload omitted
    import dataclasses

    for name, f in fields.items():
        if name not in kwargs and f.default is dataclasses.MISSING and f.default_factory is dataclasses.MISSING:
            kwargs[name] = 0 if name == "created_at" else ""
    return cls(**kwargs)


def _verify(bundle_dict: dict, manifest_dict: dict) -> dict:
    """Verify the bundle's receipt against its manifest, without the data."""
    bundle = _reconstruct(ProofBundle, bundle_dict)
    manifest = _reconstruct(Manifest, manifest_dict)
    return _verify_payload(verify_bundle(bundle, manifest))


def public_share_payload(token: str) -> dict:
    """Everything a public viewer needs to confirm a shared, attested result.

    No auth: the share token grants read access to exactly one bundle. Contains
    no rows (bundles never do)."""
    share = STORE.get_share(token)
    if not share:
        raise ApiError(404, "share not found")
    bundle = STORE.get_bundle(share["org_id"], share["bundle_id"])
    if not bundle:
        raise ApiError(404, "shared bundle no longer exists")
    manifest = STORE.get_manifest(share["org_id"], bundle["dataset_id"])
    verification = (
        _verify(bundle, manifest)
        if manifest
        else {"ok": False, "tier": "receipt", "checks": [], "note": "manifest missing"}
    )
    # The whole bundle and manifest, so anyone can save them and verify independently.
    pub = {k: v for k, v in bundle.items() if not k.startswith("_")}
    return {
        "org": STORE.org_name(share["org_id"]),
        "bundle": pub,
        "manifest": manifest,
        "dataset": (
            {"dataset_id": manifest["dataset_id"], "name": manifest.get("name"),
             "commitment": manifest["commitment"]}
            if manifest else None
        ),
        "verification": verification,
    }


# --- admin (token-gated) -----------------------------------------------------
def handle_admin(method: str, path: str, body: dict) -> tuple[int, dict]:
    if path == "/api/admin/orgs" and method == "POST":
        name = (body.get("name") or "").strip()
        if not name:
            raise ApiError(400, "org name required")
        org_id = STORE.create_org(name)
        STORE.audit(org_id, "admin.org.create", name)
        log.info("admin created org %s (%s)", org_id, name)
        return 200, {"org_id": org_id, "name": name}

    m = _ADMIN_ORG_KEYS.match(path)
    if m and method == "POST":
        org_id = m.group(1)
        if not STORE.org_exists(org_id):
            raise ApiError(404, "org not found")
        key = STORE.issue_key(org_id, body.get("label", ""))
        STORE.audit(org_id, "admin.key.issue", body.get("label", ""))
        return 200, {"org_id": org_id, "api_key": key,
                     "note": "store now; it is not recoverable"}

    if m and method == "GET":
        org_id = m.group(1)
        if not STORE.org_exists(org_id):
            raise ApiError(404, "org not found")
        return 200, {"keys": STORE.list_keys(org_id)}

    m = _ADMIN_KEY_DEL.match(path)
    if m and method == "DELETE":
        ok = STORE.revoke_key(m.group(1))
        if not ok:
            raise ApiError(404, "key not found or already revoked")
        STORE.audit(None, "admin.key.revoke", m.group(1))
        return 200, {"revoked": True, "key_id": m.group(1)}

    raise ApiError(404, "no such admin route")


# --- request handling --------------------------------------------------------
def handle(
    method: str, path: str, org_id: str | None, body: dict, query: dict | None = None
) -> tuple[int, dict]:
    query = query or {}

    if path == "/api/stats" and method == "GET":
        return 200, STORE.stats(org_id)

    # org self-service: manage one's own API keys
    if path == "/api/keys" and method == "GET":
        return 200, {"keys": STORE.list_keys(org_id)}

    m = _KEY_DEL.match(path)
    if m and method == "DELETE":
        ok = STORE.revoke_key(m.group(1), org_id=org_id)
        if not ok:
            raise ApiError(404, "key not found in your org or already revoked")
        STORE.audit(org_id, "key.revoke", m.group(1))
        return 200, {"revoked": True, "key_id": m.group(1)}

    # manifests
    if path == "/api/manifests" and method == "POST":
        missing = _REQUIRED_MANIFEST - set(body)
        if missing:
            raise ApiError(400, f"manifest missing fields: {sorted(missing)}")
        _require_id(body, "dataset_id")
        _check_manifest(body)
        STORE.put_manifest(org_id, body)
        STORE.audit(org_id, "manifest.register", body["dataset_id"])
        log.info("org=%s registered manifest %s", org_id, body["dataset_id"])
        return 200, {"ok": True, "dataset_id": body["dataset_id"]}

    if path == "/api/manifests" and method == "GET":
        limit, offset = _page(query)
        return 200, {"manifests": STORE.list_manifests(org_id, limit, offset)}

    m = _MANIFEST_GET.match(path)
    if m and method == "GET":
        man = STORE.get_manifest(org_id, m.group(1))
        if not man:
            raise ApiError(404, "manifest not found")
        return 200, {"manifest": man}

    # bundles
    if path == "/api/bundles" and method == "POST":
        missing = _REQUIRED_BUNDLE - set(body)
        if missing:
            raise ApiError(400, f"bundle missing fields: {sorted(missing)}")
        _require_id(body, "bundle_id")
        _require_id(body, "dataset_id")
        manifest = STORE.get_manifest(org_id, body["dataset_id"])
        if not manifest:
            raise ApiError(400, "no manifest for this dataset_id; register it first")
        _check_bundle_query(body, manifest)
        verification = _verify(body, manifest)
        STORE.put_bundle(org_id, body, verification["ok"], verification["tier"])
        STORE.audit(org_id, "bundle.submit", f"{body['bundle_id']} ok={verification['ok']}")
        log.info("org=%s bundle %s verified=%s", org_id, body["bundle_id"], verification["ok"])
        return 200, {"ok": True, "bundle_id": body["bundle_id"], "verification": verification}

    if path == "/api/bundles" and method == "GET":
        limit, offset = _page(query)
        return 200, {"bundles": STORE.list_bundles(org_id, limit, offset)}

    m = _BUNDLE_VERIFY.match(path)
    if m and method == "POST":
        bundle = STORE.get_bundle(org_id, m.group(1))
        if not bundle:
            raise ApiError(404, "bundle not found")
        manifest = STORE.get_manifest(org_id, bundle["dataset_id"])
        if not manifest:
            raise ApiError(400, "manifest for this bundle is missing")
        return 200, {"verification": _verify(bundle, manifest)}

    m = _BUNDLE_SHARE.match(path)
    if m and method == "POST":
        if not STORE.get_bundle(org_id, m.group(1)):
            raise ApiError(404, "bundle not found")
        token = STORE.create_share(org_id, m.group(1))
        STORE.audit(org_id, "bundle.share", m.group(1))
        return 200, {"token": token, "view_path": f"/v/{token}",
                     "json_path": f"/share/{token}"}

    m = _BUNDLE_GET.match(path)
    if m and method == "GET":
        bundle = STORE.get_bundle(org_id, m.group(1))
        if not bundle:
            raise ApiError(404, "bundle not found")
        return 200, {"bundle": bundle}

    if path == "/api/audit" and method == "GET":
        return 200, {"audit": STORE.list_audit(org_id)}

    if path == "/api/whoami" and method == "GET":
        return 200, {"org_id": org_id, "org_name": STORE.org_name(org_id)}

    raise ApiError(404, "no such route")


class Handler(BaseHTTPRequestHandler):
    server_version = f"tiresias-registry/{__version__}"

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in SECURITY_HEADERS.items():
            if k == "Content-Security-Policy" and ctype == "image/svg+xml":
                v = SVG_CSP   # the logos animate with an inline <style>; an SVG image never runs script
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, payload: dict) -> None:
        self._send(code, json.dumps(payload).encode(), "application/json")

    def _bearer(self) -> str:
        h = self.headers.get("Authorization", "")
        return h[len("Bearer "):].strip() if h.startswith("Bearer ") else ""

    def _auth(self) -> str:
        org_id = STORE.org_for_key(self._bearer())
        if not org_id:
            raise ApiError(401, "missing or invalid API key")
        return org_id

    def _read_body(self) -> dict:
        # A negative length would pass the size check and turn into read(-1),
        # which reads until the client closes the connection.
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raise ApiError(400, "Content-Length must be an integer")
        if length < 0:
            raise ApiError(400, "Content-Length must not be negative")
        if length > config.MAX_BODY_BYTES:
            raise ApiError(413, "request body too large")
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        try:
            body = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise ApiError(400, "body is not valid JSON")
        if not isinstance(body, dict):
            raise ApiError(400, "body must be a JSON object")
        return body

    def _client(self) -> str:
        return "ip:" + str(self.client_address[0])

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            with open(os.path.join(HERE, "landing.html"), "rb") as f:
                self._send(200, f.read(), "text/html; charset=utf-8")
            return
        if path in ("/console", "/console.html"):
            with open(os.path.join(HERE, "console.html"), "rb") as f:
                self._send(200, f.read(), "text/html; charset=utf-8")
            return
        m = _STATIC.match(path)
        if m:
            target = os.path.join(STATIC, m.group(1))
            if os.path.isfile(target):
                with open(target, "rb") as f:
                    self._send(200, f.read(), _STATIC_TYPES[target.rsplit(".", 1)[-1]])
                return
        if path == "/healthz":
            self._json(200, {"status": "ok", "service": "tiresias-registry"})
            return
        if path == "/metrics":
            if not auth.admin_token_ok(self._bearer(), config.ADMIN_TOKEN):
                self._json(401, {"error": "admin token required for /metrics"})
                return
            self._send(200, metrics_text().encode(), "text/plain; version=0.0.4")
            return
        # public, no-auth verification views (a share token authorizes one bundle)
        if _SHARE_VIEW.match(path):
            with open(os.path.join(HERE, "public_view.html"), "rb") as f:
                self._send(200, f.read(), "text/html; charset=utf-8")
            return
        m = _SHARE_GET.match(path)
        if m:
            if not IP_RL.allow(self._client()):
                self._json(429, {"error": "rate limit exceeded; slow down"})
                return
            try:
                self._json(200, public_share_payload(m.group(1)))
            except ApiError as e:
                self._json(e.status, {"error": e.message})
            except Exception:  # noqa: BLE001
                self._internal_error("GET")
            return
        self._dispatch("GET")

    def do_POST(self) -> None:
        self._dispatch("POST")

    def do_DELETE(self) -> None:
        self._dispatch("DELETE")

    def _dispatch(self, method: str) -> None:
        try:
            parsed = urlparse(self.path)
            path = parsed.path
            query = {k: v[0] for k, v in parse_qs(parsed.query).items()}
            body = self._read_body()
            if path.startswith("/api/admin/"):
                if not IP_RL.allow(self._client()):
                    raise ApiError(429, "rate limit exceeded; slow down")
                if not auth.admin_token_ok(self._bearer(), config.ADMIN_TOKEN):
                    raise ApiError(401, "admin token required (set TIRESIAS_ADMIN_TOKEN)")
                code, payload = handle_admin(method, path, body)
            else:
                org_id = self._auth()
                if not RL.allow(org_id):
                    raise ApiError(429, "rate limit exceeded; slow down")
                code, payload = handle(method, path, org_id, body, query)
            self._json(code, payload)
        except ApiError as e:
            self._json(e.status, {"error": e.message})
        except Exception:  # noqa: BLE001
            self._internal_error(method)

    def _internal_error(self, method: str) -> None:
        # The exception text can carry paths, SQL or request content, so the
        # client gets only an id that finds the full trace in the server log.
        error_id = secrets.token_hex(8)
        log.exception("unhandled error %s on %s %s", error_id, method, self.path)
        self._json(500, {"error": "internal error", "error_id": error_id})

    def log_message(self, format, *args) -> None:
        pass  # logging handled explicitly


def serve(host: str | None = None, port: int | None = None) -> None:
    host = host or config.REGISTRY_HOST
    port = port or config.REGISTRY_PORT
    log.info("registry listening on http://%s:%s (db=%s)", host, port, config.DB_PATH)
    log.info("this server never receives raw data, only manifests and proof bundles")
    log.info("receipts are verified with %s", zkvm.binary())
    ThreadingHTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    serve()
