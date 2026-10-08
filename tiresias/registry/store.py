"""Persistent, multi-tenant storage for the registry (stdlib sqlite3, no deps).

Stores orgs, hashed API keys, manifests, proof bundles, and an audit log. Every
read and write is scoped by org id, so tenants are isolated. No raw dataset rows
are ever stored here: only manifests (commitments) and bundles (public results).
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import uuid

from tiresias.registry.auth import generate_key, hash_key

_SCHEMA = """
CREATE TABLE IF NOT EXISTS orgs (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS api_keys (
  key_hash TEXT PRIMARY KEY, key_id TEXT NOT NULL, org_id TEXT NOT NULL,
  label TEXT, revoked INTEGER NOT NULL DEFAULT 0, created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS manifests (
  dataset_id TEXT PRIMARY KEY, org_id TEXT NOT NULL, name TEXT,
  commitment TEXT NOT NULL, json TEXT NOT NULL, created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS bundles (
  bundle_id TEXT PRIMARY KEY, org_id TEXT NOT NULL, dataset_id TEXT NOT NULL,
  query TEXT, accepted INTEGER, commitment TEXT, verified INTEGER,
  verify_tier TEXT, json TEXT NOT NULL, created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS audit (
  id INTEGER PRIMARY KEY AUTOINCREMENT, org_id TEXT, action TEXT,
  detail TEXT, ts REAL NOT NULL);
CREATE TABLE IF NOT EXISTS shares (
  token TEXT PRIMARY KEY, org_id TEXT NOT NULL, bundle_id TEXT NOT NULL,
  created_at REAL NOT NULL);
"""


class Store:
    def __init__(self, db_path: str):
        if os.path.dirname(db_path):
            os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._db = sqlite3.connect(db_path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            # WAL: concurrent reads alongside a writer, fewer lock stalls under
            # the threaded server.
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("PRAGMA synchronous=NORMAL")
            self._db.executescript(_SCHEMA)
            self._db.commit()

    # --- orgs + keys ---------------------------------------------------------
    def create_org(self, name: str) -> str:
        org_id = "org_" + uuid.uuid4().hex[:12]
        with self._lock:
            self._db.execute(
                "INSERT INTO orgs(id, name, created_at) VALUES (?,?,?)",
                (org_id, name, time.time()),
            )
            self._db.commit()
        return org_id

    def issue_key(self, org_id: str, label: str = "") -> str:
        key = generate_key()
        key_id = "key_" + uuid.uuid4().hex[:12]
        with self._lock:
            self._db.execute(
                "INSERT INTO api_keys(key_hash, key_id, org_id, label, revoked, created_at)"
                " VALUES (?,?,?,?,0,?)",
                (hash_key(key), key_id, org_id, label, time.time()),
            )
            self._db.commit()
        return key  # returned once; only the hash is persisted

    def org_for_key(self, key: str) -> str | None:
        with self._lock:
            row = self._db.execute(
                "SELECT org_id FROM api_keys WHERE key_hash=? AND revoked=0",
                (hash_key(key),),
            ).fetchone()
        return row["org_id"] if row else None

    def list_keys(self, org_id: str) -> list[dict]:
        """Key metadata only, never the key or its hash."""
        with self._lock:
            rows = self._db.execute(
                "SELECT key_id, label, revoked, created_at FROM api_keys"
                " WHERE org_id=? ORDER BY created_at DESC",
                (org_id,),
            ).fetchall()
        return [
            {"key_id": r["key_id"], "label": r["label"],
             "revoked": bool(r["revoked"]), "created_at": r["created_at"]}
            for r in rows
        ]

    def revoke_key(self, key_id: str, org_id: str | None = None) -> bool:
        """Revoke a key by id. If org_id is given, only revoke if it belongs to
        that org (tenant-scoped self-service). Returns True if a key was revoked."""
        sql = "UPDATE api_keys SET revoked=1 WHERE key_id=? AND revoked=0"
        args: tuple = (key_id,)
        if org_id is not None:
            sql += " AND org_id=?"
            args = (key_id, org_id)
        with self._lock:
            cur = self._db.execute(sql, args)
            self._db.commit()
            return cur.rowcount > 0

    def org_exists(self, org_id: str) -> bool:
        with self._lock:
            return self._db.execute(
                "SELECT 1 FROM orgs WHERE id=?", (org_id,)
            ).fetchone() is not None

    def org_name(self, org_id: str) -> str | None:
        with self._lock:
            row = self._db.execute(
                "SELECT name FROM orgs WHERE id=?", (org_id,)
            ).fetchone()
        return row["name"] if row else None

    # --- manifests -----------------------------------------------------------
    def put_manifest(self, org_id: str, manifest: dict) -> None:
        with self._lock:
            self._db.execute(
                "INSERT OR REPLACE INTO manifests"
                "(dataset_id, org_id, name, commitment, json, created_at)"
                " VALUES (?,?,?,?,?,?)",
                (
                    manifest["dataset_id"],
                    org_id,
                    manifest.get("name"),
                    str(manifest["commitment"]),
                    json.dumps(manifest),
                    time.time(),
                ),
            )
            self._db.commit()

    def get_manifest(self, org_id: str, dataset_id: str) -> dict | None:
        with self._lock:
            row = self._db.execute(
                "SELECT json FROM manifests WHERE org_id=? AND dataset_id=?",
                (org_id, dataset_id),
            ).fetchone()
        return json.loads(row["json"]) if row else None

    def list_manifests(self, org_id: str, limit: int = 50, offset: int = 0) -> list[dict]:
        with self._lock:
            rows = self._db.execute(
                "SELECT json FROM manifests WHERE org_id=? ORDER BY created_at DESC"
                " LIMIT ? OFFSET ?",
                (org_id, limit, offset),
            ).fetchall()
        return [json.loads(r["json"]) for r in rows]

    # --- bundles -------------------------------------------------------------
    def put_bundle(
        self, org_id: str, bundle: dict, verified: bool, tier: str
    ) -> None:
        with self._lock:
            self._db.execute(
                "INSERT OR REPLACE INTO bundles"
                "(bundle_id, org_id, dataset_id, query, accepted, commitment,"
                " verified, verify_tier, json, created_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    bundle["bundle_id"],
                    org_id,
                    bundle["dataset_id"],
                    bundle.get("query"),
                    1 if bundle.get("accepted") else 0,
                    str(bundle["commitment"]),
                    1 if verified else 0,
                    tier,
                    json.dumps(bundle),
                    time.time(),
                ),
            )
            self._db.commit()

    def get_bundle(self, org_id: str, bundle_id: str) -> dict | None:
        with self._lock:
            row = self._db.execute(
                "SELECT json, verified, verify_tier FROM bundles"
                " WHERE org_id=? AND bundle_id=?",
                (org_id, bundle_id),
            ).fetchone()
        if not row:
            return None
        b = json.loads(row["json"])
        b["_verified"] = bool(row["verified"])
        b["_verify_tier"] = row["verify_tier"]
        return b

    def list_bundles(self, org_id: str, limit: int = 50, offset: int = 0) -> list[dict]:
        with self._lock:
            rows = self._db.execute(
                "SELECT json, verified, verify_tier FROM bundles"
                " WHERE org_id=? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (org_id, limit, offset),
            ).fetchall()
        out = []
        for r in rows:
            b = json.loads(r["json"])
            b["_verified"] = bool(r["verified"])
            b["_verify_tier"] = r["verify_tier"]
            out.append(b)
        return out

    # --- shares (public verification links) ----------------------------------
    def create_share(self, org_id: str, bundle_id: str) -> str:
        token = "shr_" + uuid.uuid4().hex
        with self._lock:
            self._db.execute(
                "INSERT INTO shares(token, org_id, bundle_id, created_at) VALUES (?,?,?,?)",
                (token, org_id, bundle_id, time.time()),
            )
            self._db.commit()
        return token

    def get_share(self, token: str) -> dict | None:
        with self._lock:
            row = self._db.execute(
                "SELECT org_id, bundle_id FROM shares WHERE token=?", (token,)
            ).fetchone()
        return {"org_id": row["org_id"], "bundle_id": row["bundle_id"]} if row else None

    # --- audit ---------------------------------------------------------------
    def audit(self, org_id: str | None, action: str, detail: str = "") -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO audit(org_id, action, detail, ts) VALUES (?,?,?,?)",
                (org_id, action, detail, time.time()),
            )
            self._db.commit()

    def list_audit(self, org_id: str, limit: int = 100) -> list[dict]:
        with self._lock:
            rows = self._db.execute(
                "SELECT action, detail, ts FROM audit WHERE org_id=?"
                " ORDER BY ts DESC LIMIT ?",
                (org_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def stats(self, org_id: str) -> dict:
        with self._lock:
            datasets = self._db.execute(
                "SELECT COUNT(*) c FROM manifests WHERE org_id=?", (org_id,)
            ).fetchone()["c"]
            bundles = self._db.execute(
                "SELECT COUNT(*) c FROM bundles WHERE org_id=?", (org_id,)
            ).fetchone()["c"]
            verified = self._db.execute(
                "SELECT COUNT(*) c FROM bundles WHERE org_id=? AND verified=1",
                (org_id,),
            ).fetchone()["c"]
            last = self._db.execute(
                "SELECT MAX(ts) t FROM audit WHERE org_id=?", (org_id,)
            ).fetchone()["t"]
        return {
            "datasets": datasets,
            "bundles": bundles,
            "verified_bundles": verified,
            "last_activity": last,
        }

    def global_stats(self) -> dict:
        """Instance-wide counts (all tenants) for ops/metrics."""
        with self._lock:
            c = self._db.execute
            return {
                "orgs": c("SELECT COUNT(*) n FROM orgs").fetchone()["n"],
                "datasets": c("SELECT COUNT(*) n FROM manifests").fetchone()["n"],
                "bundles": c("SELECT COUNT(*) n FROM bundles").fetchone()["n"],
                "bundles_verified": c(
                    "SELECT COUNT(*) n FROM bundles WHERE verified=1"
                ).fetchone()["n"],
                "shares": c("SELECT COUNT(*) n FROM shares").fetchone()["n"],
            }

    def close(self) -> None:
        with self._lock:
            self._db.close()
