"""Dataset commitment, its opening, and the public manifest.

Committing a dataset produces a Manifest: the only thing an organization
publishes. It binds the rows (a commitment), declares the schema and category
codes so queries are writable, and never contains a row.

The commitment is SHA-256 over a random 32-byte salt, the schema, and every
cell (the layout in zkvm/core/src/lib.rs `commitment_preimage`). The salt is
the opening: it stays with the data, and it is what makes the commitment hide
the rows, so no one can test a guess at them against it. The guest recomputes
the commitment inside every proof.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import secrets
import struct
import time
from dataclasses import asdict, dataclass

from tiresias import __version__, config
from tiresias.engine.schema import Column, ColType, Dataset
from tiresias.engine.zkvm import RISC0_VERSION

ENGINE_VERSION = f"tiresias-{__version__} / risc0-zkvm-{RISC0_VERSION}"
DOMAIN = b"tiresias.commitment.v1\0"

# The smallest number of rows an answer may describe. An aggregate over one or two
# rows is that person's value; five is a common floor for published statistics.
DEFAULT_MIN_COHORT = 5


class OpeningMismatch(ValueError):
    """The rows, or the opening, are not the ones the manifest committed to."""


@dataclass
class Manifest:
    dataset_id: str  # stable id derived from schema + commitment + policy
    name: str
    schema: list[dict]  # [{name, type, categories}]
    commitment: str  # SHA-256, hex: binds and hides the rows
    row_count: int
    created_at: float
    # Answers must describe at least this many rows; proven with every answer.
    min_cohort: int = DEFAULT_MIN_COHORT
    engine_version: str = ENGINE_VERSION
    disclosure: str = (
        "A salted SHA-256 commitment to the rows: it binds them and reveals nothing "
        "about them. Answers are proved against it in the RISC Zero zkVM."
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


def schema_of(dataset: Dataset) -> list[dict]:
    return [
        {"name": c.name, "type": c.type.value, "categories": dict(c.categories)}
        for c in dataset.columns
    ]


def schema_digest(schema: list[dict]) -> bytes:
    return hashlib.sha256(json.dumps(schema, sort_keys=True, separators=(",", ":")).encode()).digest()


def commitment(salt: bytes, schema: list[dict], rows: list[list[int]]) -> str:
    """The commitment to the rows under this salt and schema, as hex."""
    h = hashlib.sha256()
    h.update(DOMAIN + salt + schema_digest(schema) + struct.pack("<QQ", len(schema), len(rows)))
    for row in rows:
        h.update(struct.pack(f"<{len(row)}q", *row))
    return h.hexdigest()


def _dataset_id(schema: list[dict], commitment_hex: str, min_cohort: int) -> str:
    # The cohort policy is part of the identity, so re-registering the same rows
    # under a laxer policy yields a different dataset, not a quiet change.
    blob = json.dumps(schema, sort_keys=True) + f"|{commitment_hex}|{min_cohort}"
    return "ds_" + hashlib.sha256(blob.encode()).hexdigest()[:16]


def commit_dataset(dataset: Dataset, name: str, min_cohort: int = DEFAULT_MIN_COHORT) -> Manifest:
    """Commit the dataset under a fresh salt (kept on `dataset.salt`), returning its manifest."""
    if min_cohort < 1:
        raise ValueError("min_cohort must be at least 1")
    if not dataset.rows:
        raise ValueError("the dataset has no rows")
    dataset.salt = secrets.token_bytes(32)
    schema = schema_of(dataset)
    c = commitment(dataset.salt, schema, dataset.rows)
    return Manifest(
        dataset_id=_dataset_id(schema, c, min_cohort),
        name=name,
        schema=schema,
        commitment=c,
        row_count=len(dataset.rows),
        created_at=time.time(),
        min_cohort=min_cohort,
    )


def check_opening(dataset: Dataset, manifest: Manifest) -> None:
    """Refuse, before any proving, rows or a salt that do not open the commitment."""
    if dataset.salt is None or commitment(dataset.salt, manifest.schema, dataset.rows) != manifest.commitment:
        raise OpeningMismatch(
            "the data and its opening do not match the published commitment: this is "
            "not the dataset the manifest committed to, or not its opening"
        )


# --- the opening, kept beside the data -----------------------------------------
def opening_path(dataset_id: str, directory: str | None = None) -> str:
    return os.path.join(directory or config.OPENINGS, f"{dataset_id}.opening")


def save_opening(dataset_id: str, salt: bytes, directory: str | None = None) -> str:
    """Write the salt where only this user can read it. Returns the path."""
    path = opening_path(dataset_id, directory)
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(salt.hex() + "\n")
    return path


def load_opening(dataset_id: str, path: str | None = None) -> bytes:
    path = path or opening_path(dataset_id)
    try:
        with open(path) as f:
            salt = bytes.fromhex(f.read().strip())
    except FileNotFoundError:
        raise OpeningMismatch(
            f"no opening for {dataset_id} at {path}. It is written when the dataset is "
            "committed; without it no answer over this dataset can be proved."
        ) from None
    if len(salt) != 32:
        raise OpeningMismatch(f"{path} is not an opening (32 bytes of hex)")
    return salt


def load_aligned(path: str, manifest: Manifest, opening: str | None = None) -> Dataset:
    """Load a CSV using the manifest's column types and pinned category codes,
    so the data holder's encoding matches what was committed, with its opening."""
    cols = [
        Column(c["name"], ColType(c["type"]), categories=dict(c["categories"]))
        for c in manifest.schema
    ]
    by_name = {c.name: c for c in cols}
    ds = Dataset(columns=cols, salt=load_opening(manifest.dataset_id, opening))
    with open(path, newline="") as f:
        for raw in csv.DictReader(f):
            ds.rows.append([by_name[c.name].encode(raw[c.name]) for c in cols])
    return ds
