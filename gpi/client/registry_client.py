"""HTTP client for the registry API.

Used by the local prover CLI and by tests. Talks to the registry with an API
key; sends only manifests and proof bundles — never raw data.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request


class RegistryError(Exception):
    pass


class RegistryClient:
    def __init__(self, base_url: str, api_key: str, timeout: float = 60.0):
        self.base = base_url.rstrip("/")
        self.key = api_key
        self.timeout = timeout

    def _req(self, method: str, path: str, body: dict | None = None) -> dict:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method)
        req.add_header("Authorization", f"Bearer {self.key}")
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")
            try:
                detail = json.loads(detail).get("error", detail)
            except Exception:
                pass
            raise RegistryError(f"{e.code}: {detail}") from None
        except urllib.error.URLError as e:
            raise RegistryError(f"cannot reach registry at {self.base}: {e.reason}") from None

    def whoami(self) -> dict:
        return self._req("GET", "/api/whoami")

    def register_manifest(self, manifest: dict) -> dict:
        return self._req("POST", "/api/manifests", manifest)

    def list_manifests(self) -> list[dict]:
        return self._req("GET", "/api/manifests")["manifests"]

    def get_manifest(self, dataset_id: str) -> dict:
        return self._req("GET", f"/api/manifests/{dataset_id}")["manifest"]

    def submit_bundle(self, bundle: dict) -> dict:
        return self._req("POST", "/api/bundles", bundle)

    def list_bundles(self) -> list[dict]:
        return self._req("GET", "/api/bundles")["bundles"]

    def get_bundle(self, bundle_id: str) -> dict:
        return self._req("GET", f"/api/bundles/{bundle_id}")["bundle"]

    def verify_bundle(self, bundle_id: str) -> dict:
        return self._req("POST", f"/api/bundles/{bundle_id}/verify")["verification"]

    def share_bundle(self, bundle_id: str) -> dict:
        return self._req("POST", f"/api/bundles/{bundle_id}/share")

    def list_keys(self) -> list[dict]:
        return self._req("GET", "/api/keys")["keys"]

    def revoke_key(self, key_id: str) -> dict:
        return self._req("DELETE", f"/api/keys/{key_id}")

    def stats(self) -> dict:
        return self._req("GET", "/api/stats")
