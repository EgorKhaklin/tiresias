"""The Tiresias workbench: a local, stdlib-only web app for the data holder.

    tiresias app            (or: python3.12 -m tiresias.web.server)

It runs where the data lives. A CSV is read in this process and never leaves it; what
the workbench produces is a commitment (the manifest) and proofs (bundles), which are
what travels. Proofs are RISC Zero receipts, made on this machine by tiresias-prover.
It binds to 127.0.0.1 by default.

The page is static (index.html and static/), served under a strict Content-Security-
Policy: no inline script or style, nothing loaded from another origin. The JSON API:

    GET  /api/state             the session's datasets and proofs
    POST /api/sample            the bundled sample dataset
    POST /api/inspect           a CSV's columns, guessed types and a preview
    POST /api/commit            commit a CSV: returns the manifest
    POST /api/query             prove an answer: returns the bundle
    POST /api/verify            verify a bundle's receipt, without the data
    POST /api/tamper            forge a bundle's answer and verify the forgery
    GET  /api/bundles/<id>.json download a bundle, receipt included
"""

from __future__ import annotations

import copy
import csv
import io
import json
import mimetypes
import os
import re
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from tiresias.engine import zkvm
from tiresias.engine.bundle import ProofBundle
from tiresias.engine.commit import Manifest, commit_dataset
from tiresias.engine.prover import prove
from tiresias.engine.schema import ColType, Column, Dataset
from tiresias.engine.verify import verify_bundle
from tiresias.query import sql
from tiresias.query.spec import CohortTooSmall, Overflow

HERE = os.path.dirname(__file__)
STATIC = os.path.join(HERE, "static")
SAMPLE_CSV = os.path.join(HERE, "..", "..", "examples", "payroll.csv")
MAX_BODY = 20 * 1024 * 1024  # a CSV upload, as JSON
PREVIEW_ROWS = 8
CATEGORY_LIMIT = 64  # more distinct labels than this is probably not a category

HEADERS = {
    "Content-Security-Policy": (
        "default-src 'none'; script-src 'self'; style-src 'self'; font-src 'self'; "
        "img-src 'self' data:; connect-src 'self'; base-uri 'none'; form-action 'none'; "
        "frame-ancestors 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}

# This session's datasets and proofs. The workbench is one person's local tool.
_datasets: dict[str, tuple[Manifest, Dataset]] = {}
_bundles: dict[str, ProofBundle] = {}

_BOOL_TRUE = {"true", "yes", "1"}
_BOOL_FALSE = {"false", "no", "0"}


class Refused(ValueError):
    """A principled refusal (too few rows, a sum past 64 bits), not a mistake."""


def _read_csv(text: str) -> tuple[list[str], list[dict[str, str]]]:
    reader = csv.DictReader(io.StringIO(text.strip()))
    headers = [h.strip() for h in (reader.fieldnames or [])]
    if not headers:
        raise ValueError("the CSV has no header row")
    if len(set(headers)) != len(headers):
        raise ValueError("the CSV has duplicate column names")
    for h in headers:
        if not re.fullmatch(r"[A-Za-z_]\w*", h):
            raise ValueError(f"column name {h!r} must be letters, digits and underscores, not starting with a digit")
    rows = []
    for i, raw in enumerate(reader, start=2):
        if any(v is None for v in raw.values()) or None in raw:
            raise ValueError(f"line {i} has a different number of fields than the header")
        rows.append({h.strip(): (v or "").strip() for h, v in raw.items()})
    if not rows:
        raise ValueError("the CSV has a header but no rows")
    return headers, rows


def _guess(values: list[str]) -> tuple[str, str]:
    """A column's likely type, and a one-line reason."""
    low = {v.lower() for v in values}
    if low <= (_BOOL_TRUE | _BOOL_FALSE) and len(low) <= 2 and not low <= {"0", "1"}:
        return "bool", "yes/no values"
    if all(re.fullmatch(r"-?\d+", v) for v in values):
        if low <= {"0", "1"}:
            return "bool", "only 0 and 1"
        return "int", "whole numbers"
    distinct = len(low)
    if distinct <= CATEGORY_LIMIT:
        return "category", f"{distinct} distinct labels"
    return "category", f"{distinct} distinct labels: probably an identifier, consider dropping it"


def _dataset(headers: list[str], rows: list[dict[str, str]], types: dict[str, str]) -> Dataset:
    cols = [Column(h, ColType(types.get(h, "int"))) for h in headers]
    ds = Dataset(columns=cols)
    for i, raw in enumerate(rows, start=2):
        try:
            ds.rows.append([c.encode(raw[c.name]) for c in cols])
        except (ValueError, KeyError) as e:
            raise ValueError(f"line {i}: {e}") from None
    return ds


# --- API ---------------------------------------------------------------------
def api_state(_body: dict) -> dict:
    return {
        "datasets": [asdict(m) for m, _ in _datasets.values()],
        "bundles": [b.public() for b in _bundles.values()],
    }


def api_sample(_body: dict) -> dict:
    with open(SAMPLE_CSV) as f:
        return {"csv": f.read(), "name": "payroll"}


def api_inspect(body: dict) -> dict:
    headers, rows = _read_csv(str(body.get("csv", "")))
    columns = []
    for h in headers:
        values = [r[h] for r in rows]
        guess, why = _guess(values)
        columns.append({
            "name": h, "guess": guess, "why": why,
            "distinct": len({v.lower() for v in values}),
            "labels": sorted({v for v in values})[:CATEGORY_LIMIT] if guess != "int" else [],
        })
    preview = [[r[h] for h in headers] for r in rows[:PREVIEW_ROWS]]
    return {"columns": columns, "rows": len(rows), "headers": headers, "preview": preview}


def api_commit(body: dict) -> dict:
    headers, rows = _read_csv(str(body.get("csv", "")))
    types = body.get("types") or {}
    if not isinstance(types, dict):
        raise ValueError("types must map each column to int, bool or category")
    min_cohort = int(body.get("min_cohort", 5))
    if min_cohort < 1:
        raise ValueError("the minimum cohort must be at least 1")
    if min_cohort > len(rows):
        raise ValueError(f"the minimum cohort ({min_cohort}) is larger than the dataset ({len(rows)} rows)")
    name = re.sub(r"\s+", " ", str(body.get("name") or "dataset")).strip()[:80] or "dataset"
    ds = _dataset(headers, rows, types)
    manifest = commit_dataset(ds, name=name, min_cohort=min_cohort)
    _datasets[manifest.dataset_id] = (manifest, ds)
    return {"manifest": asdict(manifest)}


def _session(dataset_id: str) -> tuple[Manifest, Dataset]:
    if dataset_id not in _datasets:
        raise ValueError("that dataset is not committed in this session")
    return _datasets[dataset_id]


def _bundle(bundle_id: str) -> ProofBundle:
    if bundle_id not in _bundles:
        raise ValueError("that proof is not in this session")
    return _bundles[bundle_id]


def api_query(body: dict) -> dict:
    manifest, ds = _session(str(body.get("dataset_id", "")))
    try:
        spec = sql.parse(str(body.get("sql", "")), manifest)
        bundle = prove(ds, spec, manifest)
    except (CohortTooSmall, Overflow, zkvm.Refused) as e:
        raise Refused(str(e)) from None
    _bundles[bundle.bundle_id] = bundle
    return {"bundle": bundle.public(), "receipt_bytes": len(bundle.receipt) * 3 // 4}


def _verify_payload(result) -> dict:
    return {
        "ok": result.ok,
        "tier": result.tier,
        "checks": [{"name": n, "passed": p, "detail": d} for (n, p, d) in result.checks],
        "note": result.note,
    }


def api_verify(body: dict) -> dict:
    bundle = _bundle(str(body.get("bundle_id", "")))
    manifest, _ = _session(bundle.dataset_id)
    return {"result": _verify_payload(verify_bundle(bundle, manifest))}


def api_tamper(body: dict) -> dict:
    bundle = _bundle(str(body.get("bundle_id", "")))
    manifest, _ = _session(bundle.dataset_id)
    forged = copy.deepcopy(bundle)
    if "groups" in forged.result:
        key = next(iter(forged.result["groups"]))
        original = forged.result["groups"][key]
        forged.result["groups"][key] = original + 50000
    else:
        key = "value" if "value" in forged.result else "avg"
        original = forged.result[key]
        forged.result[key] = original + 50000
    return {
        "original": original,
        "forged": original + 50000,
        "result": _verify_payload(verify_bundle(forged, manifest)),
    }


ROUTES = {
    ("GET", "/api/state"): api_state,
    ("POST", "/api/sample"): api_sample,
    ("POST", "/api/inspect"): api_inspect,
    ("POST", "/api/commit"): api_commit,
    ("POST", "/api/query"): api_query,
    ("POST", "/api/verify"): api_verify,
    ("POST", "/api/tamper"): api_tamper,
}
_DOWNLOAD = re.compile(r"^/api/bundles/([A-Za-z0-9_-]{1,128})\.json$")
_STATIC = re.compile(r"^/static/([A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*\.(?:css|js|svg|woff2|txt))$")


class Handler(BaseHTTPRequestHandler):
    server_version = "tiresias"
    sys_version = ""

    def _send(self, code: int, body: bytes, ctype: str, extra: dict | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in {**HEADERS, **(extra or {})}.items():
            if k == "Content-Security-Policy" and ctype == "image/svg+xml":
                v = "default-src 'none'; style-src 'unsafe-inline'"   # an SVG image never runs script
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, payload: dict) -> None:
        self._send(code, json.dumps(payload).encode(), "application/json")

    def _file(self, path: str, ctype: str) -> None:
        with open(path, "rb") as f:
            self._send(200, f.read(), ctype)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            self._file(os.path.join(HERE, "index.html"), "text/html; charset=utf-8")
            return
        m = _STATIC.match(path)
        if m:
            target = os.path.join(STATIC, m.group(1))
            if os.path.isfile(target):
                ctype = {"woff2": "font/woff2", "svg": "image/svg+xml"}.get(
                    target.rsplit(".", 1)[-1], mimetypes.guess_type(target)[0] or "application/octet-stream")
                if ctype.startswith("text/") or ctype == "application/javascript":
                    ctype += "; charset=utf-8"
                self._file(target, ctype)
                return
        m = _DOWNLOAD.match(path)
        if m and m.group(1) in _bundles:
            body = json.dumps(asdict(_bundles[m.group(1)]), indent=2).encode()
            self._send(200, body, "application/json",
                       {"Content-Disposition": f'attachment; filename="tiresias-proof-{m.group(1)}.json"'})
            return
        if ("GET", path) in ROUTES:
            self._run(ROUTES[("GET", path)], {})
            return
        self._json(404, {"error": "not found"})

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        handler = ROUTES.get(("POST", path))
        if handler is None:
            self._json(404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if length < 0 or length > MAX_BODY:
            self._json(413 if length > MAX_BODY else 400, {"error": "the request body is too large or malformed", "kind": "invalid"})
            return
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            self._json(400, {"error": "the request body is not valid JSON", "kind": "invalid"})
            return
        if not isinstance(body, dict):
            self._json(400, {"error": "the request body must be a JSON object", "kind": "invalid"})
            return
        self._run(handler, body)

    def _run(self, handler, body: dict) -> None:
        try:
            self._json(200, handler(body))
        except Refused as e:
            self._json(422, {"error": str(e), "kind": "refused"})
        except (sql.SqlError, ValueError, KeyError) as e:
            msg = e.args[0] if isinstance(e, KeyError) and e.args else str(e)
            self._json(400, {"error": str(msg), "kind": "invalid"})
        except Exception as e:  # noqa: BLE001 - a local tool: show the engine's message
            self._json(500, {"error": f"{type(e).__name__}: {e}", "kind": "error"})

    def log_message(self, format, *args) -> None:  # quiet
        pass


def serve(host: str = "127.0.0.1", port: int = 8765) -> None:
    try:
        print(f"prover: {zkvm.binary()}")
    except zkvm.ProverUnavailable as e:
        print(f"warning: {e} Committing works; proving does not.")
    print(f"Tiresias workbench: http://{host}:{port}")
    ThreadingHTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    serve()
