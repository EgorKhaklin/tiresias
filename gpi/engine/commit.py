"""Dataset commitment and the public manifest.

Committing a dataset produces a Manifest: the *only* thing an organization
publishes. It binds the data (a commitment), declares the schema and category
codes so queries are writable, and never contains a single row.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass

import csv

from gpi.engine.adapter import commit_table
from gpi.engine.schema import Column, ColType, Dataset

ENGINE_VERSION = "gpi-0.0.1 / glass-pane"
CRYPTO_GRADE = "educational"  # per Glass docs/soundness.md — not production crypto


@dataclass
class Manifest:
    dataset_id: str  # stable id derived from schema + commitment
    name: str
    schema: list[dict]  # [{name, type, categories}]
    gamma: int  # public Fiat-Shamir point used by the commitment
    commitment: int  # binding fingerprint of the private rows
    row_count: int
    created_at: float
    engine_version: str = ENGINE_VERSION
    crypto_grade: str = CRYPTO_GRADE
    # Honest disclosure surfaced on every public artifact.
    disclosure: str = (
        "Commitment binds the rows; queries prove answers against it without "
        "revealing rows. Cryptographic parameters are educational-grade "
        "(Baby Bear field, unaudited hash) — a demonstration, not production "
        "security. See Glass docs/soundness.md."
    )

    def code_for(self, column: str, label) -> int:
        for c in self.schema:
            if c["name"] == column:
                if c["type"] == "category":
                    cats = c["categories"]
                    if str(label) not in cats:
                        raise KeyError(
                            f"column {column!r} has no category {label!r}; "
                            f"known: {sorted(cats)}"
                        )
                    return cats[str(label)]
                if c["type"] == "bool":
                    return 1 if str(label).lower() in ("1", "true", "yes") else 0
                return int(label)
        raise KeyError(f"manifest has no column {column!r}")

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)

    @classmethod
    def load(cls, path: str) -> "Manifest":
        with open(path) as f:
            return cls(**json.load(f))

    def save(self, path: str) -> None:
        with open(path, "w") as f:
            f.write(self.to_json())


def load_aligned(path: str, manifest: Manifest) -> Dataset:
    """Load a CSV using the manifest's column types and pinned category codes,
    so the data-holder's encoding matches what was committed."""
    cols = [
        Column(c["name"], ColType(c["type"]), categories=dict(c["categories"]))
        for c in manifest.schema
    ]
    by_name = {c.name: c for c in cols}
    ds = Dataset(columns=cols)
    with open(path, newline="") as f:
        for raw in csv.DictReader(f):
            ds.rows.append([by_name[c.name].encode(raw[c.name]) for c in cols])
    return ds


def _dataset_id(schema: list[dict], commitment: int) -> str:
    blob = json.dumps(schema, sort_keys=True) + f"|{commitment}"
    return "ds_" + hashlib.sha256(blob.encode()).hexdigest()[:16]


def commit_dataset(dataset: Dataset, name: str, gamma: int) -> Manifest:
    """Run the Glass engine to commit the dataset, returning its public manifest."""
    commitment = commit_table(dataset.to_pane_table(), gamma)
    schema = [
        {"name": c.name, "type": c.type.value, "categories": dict(c.categories)}
        for c in dataset.columns
    ]
    return Manifest(
        dataset_id=_dataset_id(schema, commitment),
        name=name,
        schema=schema,
        gamma=gamma,
        commitment=commitment,
        row_count=len(dataset.rows),
        created_at=time.time(),
    )
