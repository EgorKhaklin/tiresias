"""A stdlib-only web server for the Tiresias dashboard.

No external dependencies (mirrors Glass's own stdlib-only discipline). It serves
a single-page dashboard and a small JSON API that drives the real engine:
commit -> manifest, query -> proof bundle, verify, and a tamper check.

  python3.12 -m gpi.web.server          # then open http://127.0.0.1:8765

NOTE: in production the prover runs where the data lives; this demo server plays
both the data-holder (proving) and the registry (verifying) for a single-screen
story. Each query runs a real Glass proof and takes a few seconds.
"""

from __future__ import annotations

import copy
import io
import json
import os
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from gpi.engine.bundle import ProofBundle
from gpi.engine.commit import Manifest, commit_dataset
from gpi.engine.prover import prove
from gpi.engine.schema import ColType, Dataset
from gpi.engine.verify import verify_bundle
from gpi.query import sql

HERE = os.path.dirname(__file__)
SAMPLE_CSV = os.path.join(HERE, "..", "..", "examples", "payroll.csv")
GAMMA = 918273645

# In-memory demo stores.
_datasets: dict[str, tuple[Manifest, Dataset]] = {}
_bundles: dict[str, ProofBundle] = {}


def _parse_types(spec: str) -> dict[str, ColType]:
    out: dict[str, ColType] = {}
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        name, _, t = part.partition("=")
        out[name.strip()] = ColType(t.strip())
    return out


def _dataset_from_csv_text(text: str, types: dict[str, ColType]) -> Dataset:
    import csv

    reader = csv.DictReader(io.StringIO(text))
    headers = reader.fieldnames or []
    from gpi.engine.schema import Column

    cols = [Column(h, types.get(h, ColType.INT)) for h in headers]
    by_name = {c.name: c for c in cols}
    ds = Dataset(columns=cols)
    for raw in reader:
        ds.rows.append([by_name[h].encode(raw[h]) for h in headers])
    return ds


def _verify_payload(result) -> dict:
    return {
        "ok": result.ok,
        "tier": result.tier,
        "checks": [
            {"name": n, "passed": p, "detail": d} for (n, p, d) in result.checks
        ],
        "note": result.note,
    }


# --- API handlers ------------------------------------------------------------
def api_sample(_body: dict) -> dict:
    with open(SAMPLE_CSV) as f:
        return {"csv": f.read(), "types": "dept=category,remote=bool"}


def api_commit(body: dict) -> dict:
    ds = _dataset_from_csv_text(body["csv"], _parse_types(body.get("types", "")))
    manifest = commit_dataset(ds, name=body.get("name", "dataset"), gamma=GAMMA)
    _datasets[manifest.dataset_id] = (manifest, ds)
    return {"manifest": asdict(manifest)}


def api_query(body: dict) -> dict:
    manifest, ds = _datasets[body["dataset_id"]]
    spec = sql.parse(body["sql"], manifest)
    bundle = prove(ds, spec, manifest)
    _bundles[bundle.bundle_id] = bundle
    return {"bundle": asdict(bundle)}


def api_verify(body: dict) -> dict:
    bundle = _bundles[body["bundle_id"]]
    manifest, ds = _datasets[bundle.dataset_id]
    use_data = ds if body.get("with_data") else None
    return {"result": _verify_payload(verify_bundle(bundle, manifest, use_data))}


def api_tamper(body: dict) -> dict:
    bundle = _bundles[body["bundle_id"]]
    manifest, ds = _datasets[bundle.dataset_id]
    forged = copy.deepcopy(bundle)
    key = "value" if "value" in forged.result else "sum"
    original = forged.result[key]
    forged.result[key] = original + int(body.get("delta", 50000))
    return {
        "original": original,
        "forged": forged.result[key],
        "result": _verify_payload(verify_bundle(forged, manifest, ds)),
    }


ROUTES = {
    "/api/sample": api_sample,
    "/api/commit": api_commit,
    "/api/query": api_query,
    "/api/verify": api_verify,
    "/api/tamper": api_tamper,
}


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path in ("/", "/index.html"):
            with open(os.path.join(HERE, "index.html"), "rb") as f:
                self._send(200, f.read(), "text/html; charset=utf-8")
        else:
            self._send(404, b"not found", "text/plain")

    def do_POST(self) -> None:
        handler = ROUTES.get(self.path)
        if handler is None:
            self._send(404, b'{"error":"no such route"}', "application/json")
            return
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw or b"{}")
            payload = handler(body)
            self._send(200, json.dumps(payload).encode(), "application/json")
        except Exception as e:  # noqa: BLE001 - surface engine errors to the UI
            self._send(
                400,
                json.dumps({"error": f"{type(e).__name__}: {e}"}).encode(),
                "application/json",
            )

    def log_message(self, format, *args) -> None:  # quiet
        pass


def serve(host: str = "127.0.0.1", port: int = 8765) -> None:
    print(f"Tiresias dashboard -> http://{host}:{port}")
    ThreadingHTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    serve()
