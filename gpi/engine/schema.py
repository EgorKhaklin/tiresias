"""Dataset schema and field encoding.

Glass's proving field is Baby Bear (2^31 - 1) on the Pane path, so every value
that enters a circuit must be a small non-negative integer. This module maps a
human dataset (ints, booleans, categorical strings) onto that field and records
the encoding so queries can be written in human terms ("dept = 'eng'") and
lowered to field terms ("dept == 0").
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from enum import Enum

# Baby Bear prime used by examples/prove/prove_pane.glass.
FIELD_PRIME = 2147483647
# Headroom: aggregates (sums) must also stay below the prime. We warn well before.
SAFE_VALUE_MAX = FIELD_PRIME // 2
# Glass's comparison gadget (lt_gadget) assumes operands in [0, 2^16). So MIN/MAX
# and < / > range filters only work on columns whose values stay under this.
# Equality filters and SUM/COUNT/AVG have no such limit.
RANGE_MAX = 65536


class GpiRangeError(ValueError):
    """A comparison (MIN/MAX or < / >) was requested on values that exceed the
    educational comparison gadget's range."""


class GpiFieldError(ValueError):
    """An aggregate could exceed the proving field, so the proof would be over
    modular (wrapped) arithmetic rather than the exact integer — unsound."""


class ColType(str, Enum):
    INT = "int"  # non-negative integer, used directly as a field element
    BOOL = "bool"  # 0 / 1
    CATEGORY = "category"  # small set of labels, encoded to integer codes


_BOOL_WORDS = {"true", "false", "yes", "no"}


def _is_int(s: str) -> bool:
    s = s.strip()
    if s.startswith("-"):
        s = s[1:]
    return s.isdigit()


def infer_types(headers: list[str], rows: list[dict]) -> dict[str, "ColType"]:
    """Infer a ColType per column from its values:

      - bool     : every value is true/false/yes/no
      - int      : every value parses as an integer
      - category : otherwise (string labels)

    Empty cells are ignored; an all-empty column defaults to int.
    """
    out: dict[str, ColType] = {}
    for h in headers:
        vals = [r[h].strip() for r in rows if r.get(h, "").strip() != ""]
        if not vals:
            out[h] = ColType.INT
        elif all(v.lower() in _BOOL_WORDS for v in vals):
            out[h] = ColType.BOOL
        elif all(_is_int(v) for v in vals):
            out[h] = ColType.INT
        else:
            out[h] = ColType.CATEGORY
    return out


@dataclass
class Column:
    name: str
    type: ColType
    # for CATEGORY: label -> integer code (public; labels are not the secret data)
    categories: dict[str, int] = field(default_factory=dict)

    def encode(self, raw: str | int | bool) -> int:
        if self.type is ColType.BOOL:
            if isinstance(raw, bool):
                return 1 if raw else 0
            return 1 if str(raw).strip().lower() in ("1", "true", "yes") else 0
        if self.type is ColType.CATEGORY:
            key = str(raw).strip()
            if key not in self.categories:
                self.categories[key] = len(self.categories)
            return self.categories[key]
        # INT
        v = int(raw)
        if v < 0:
            raise ValueError(
                f"column {self.name!r}: negative values unsupported on the field path ({v})"
            )
        if v > SAFE_VALUE_MAX:
            raise ValueError(
                f"column {self.name!r}: value {v} exceeds safe field range "
                f"(< {SAFE_VALUE_MAX}); educational Baby Bear field cannot hold it"
            )
        return v

    def code_for(self, label: str | int | bool) -> int:
        """Translate a query literal in human terms to its field code."""
        if self.type is ColType.CATEGORY:
            key = str(label).strip()
            if key not in self.categories:
                raise KeyError(
                    f"column {self.name!r} has no category {label!r}; "
                    f"known: {sorted(self.categories)}"
                )
            return self.categories[key]
        if self.type is ColType.BOOL:
            return 1 if str(label).strip().lower() in ("1", "true", "yes") else 0
        return int(label)


@dataclass
class Dataset:
    """A private table: an ordered schema plus encoded integer rows.

    The rows are the secret. Only the schema, category maps, and (later) the
    commitment are ever made public.
    """

    columns: list[Column]
    rows: list[list[int]] = field(default_factory=list)

    @property
    def column_names(self) -> list[str]:
        return [c.name for c in self.columns]

    def column(self, name: str) -> Column:
        for c in self.columns:
            if c.name == name:
                return c
        raise KeyError(f"no column {name!r}; have {self.column_names}")

    @classmethod
    def from_csv(
        cls, path: str, types: dict[str, ColType] | None = None
    ) -> "Dataset":
        """Load a CSV. Column types are inferred from the data unless given in
        `types` (explicit types override inference, per column)."""
        types = dict(types or {})
        with open(path, newline="") as f:
            reader = csv.DictReader(f)
            headers = list(reader.fieldnames or [])
            raw_rows = list(reader)
        inferred = infer_types(headers, raw_rows)
        cols = [Column(h, types.get(h, inferred[h])) for h in headers]
        by_name = {c.name: c for c in cols}
        ds = cls(columns=cols)
        for raw in raw_rows:
            ds.rows.append([by_name[h].encode(raw[h]) for h in headers])
        return ds

    def to_pane_table(self):
        """Project onto the Pane AST (all cells are encoded ints)."""
        from gpi.query.pane_ast import Table

        return Table(columns=self.column_names, rows=[list(r) for r in self.rows])
