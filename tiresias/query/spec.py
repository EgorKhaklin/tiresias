"""A table-free query specification, and the plan the zkVM guest proves.

The SQL the analyst writes becomes a QuerySpec: an aggregate over an optional
predicate, with no data attached. `plan` compiles it against a dataset's public
manifest into the exact structure the guest evaluates and commits to its
journal (zkvm/core/src/lib.rs); a verifier compiles the same SQL and requires
that plan. `answer` is the same evaluation in Python, run before proving so a
refusal is immediate and the proved answer can be checked against it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Union

AGG_SUM = "sum"
AGG_COUNT = "count"
AGG_AVG = "avg"
AGG_MIN = "min"
AGG_MAX = "max"
AGG_GROUPBY = "groupby"  # SUM(column) per category of a categorical column

OPS = {"=": "Eq", "!=": "Ne", "<": "Lt", ">": "Gt", "<=": "Le", ">=": "Ge"}

I64_MIN, I64_MAX = -(2**63), 2**63 - 1


class CohortTooSmall(ValueError):
    """The query describes fewer rows than the dataset's minimum cohort, so its
    answer could single someone out. Refused rather than proven."""


class Overflow(ValueError):
    """A sum does not fit in 64 bits, so the guest cannot prove it."""


# --- predicates ---------------------------------------------------------------
@dataclass(frozen=True)
class Cmp:
    column: str
    op: str  # one of OPS
    value: int  # the literal, already encoded through the manifest


@dataclass(frozen=True)
class And:
    a: "Pred"
    b: "Pred"


@dataclass(frozen=True)
class Or:
    a: "Pred"
    b: "Pred"


@dataclass(frozen=True)
class Not:
    a: "Pred"


Pred = Union[Cmp, And, Or, Not]


def _index(columns: list[str], name: str) -> int:
    if name not in columns:
        raise KeyError(f"no column {name!r}; the dataset has {columns}")
    return columns.index(name)


def _pred_plan(p: Pred, columns: list[str]) -> dict:
    if isinstance(p, Cmp):
        return {"Cmp": {"column": _index(columns, p.column), "op": OPS[p.op], "value": p.value}}
    if isinstance(p, And):
        return {"And": [_pred_plan(p.a, columns), _pred_plan(p.b, columns)]}
    if isinstance(p, Or):
        return {"Or": [_pred_plan(p.a, columns), _pred_plan(p.b, columns)]}
    return {"Not": _pred_plan(p.a, columns)}


@dataclass
class QuerySpec:
    agg: str
    column: str | None  # None for COUNT(*)
    predicate: Pred | None
    text: str = ""  # the original SQL, for display and audit
    group_key: str | None = None  # the GROUP BY column (categorical)

    def plan(self, manifest) -> dict:
        """The guest's Plan (serde's JSON form), compiled against the manifest."""
        columns = [c["name"] for c in manifest.schema]
        if self.agg == AGG_COUNT:
            aggregate: dict | str = "Count"
        elif self.agg == AGG_GROUPBY:
            assert self.column is not None and self.group_key is not None
            codes = next(c["categories"] for c in manifest.schema if c["name"] == self.group_key)
            if not codes:
                raise ValueError(f"GROUP BY column {self.group_key!r} has no categories")
            aggregate = {"GroupSum": {
                "column": _index(columns, self.column),
                "key": _index(columns, self.group_key),
                "codes": sorted(codes.values()),
            }}
        else:
            assert self.column is not None
            name = {AGG_SUM: "Sum", AGG_AVG: "Avg", AGG_MIN: "Min", AGG_MAX: "Max"}[self.agg]
            aggregate = {name: {"column": _index(columns, self.column)}}
        return {
            "aggregate": aggregate,
            "filter": None if self.predicate is None else _pred_plan(self.predicate, columns),
            "min_cohort": manifest.min_cohort,
        }


# --- evaluation (zkvm/core/src/lib.rs `answer`, in Python) --------------------
def _holds(p: dict, row: list[int]) -> bool:
    (kind, body), = p.items()
    if kind == "Cmp":
        v, x = row[body["column"]], body["value"]
        return {"Eq": v == x, "Ne": v != x, "Lt": v < x, "Gt": v > x, "Le": v <= x, "Ge": v >= x}[body["op"]]
    if kind == "And":
        return _holds(body[0], row) and _holds(body[1], row)
    if kind == "Or":
        return _holds(body[0], row) or _holds(body[1], row)
    return not _holds(body, row)


def _total(rows: list[list[int]], column: int) -> int:
    s = 0
    for r in rows:
        s += r[column]
        if not I64_MIN <= s <= I64_MAX:
            raise Overflow("the sum does not fit in 64 bits; scale the column down before committing")
    return s


def _require(n: int, plan: dict) -> None:
    if n < plan["min_cohort"]:
        raise CohortTooSmall(
            f"the query describes {n} rows; this dataset answers only about cohorts "
            f"of at least {plan['min_cohort']}"
        )


def answer(plan: dict, rows: list[list[int]]) -> dict:
    """The guest's Answer (serde's JSON form) for the plan over the rows."""
    flt = plan["filter"]
    sel = [r for r in rows if flt is None or _holds(flt, r)]
    n = len(sel)
    agg = plan["aggregate"]
    if agg == "Count":
        _require(n, plan)
        return {"Count": {"count": n}}
    (kind, body), = agg.items()
    if kind == "GroupSum":
        groups, suppressed = [], []
        for code in body["codes"]:
            g = [r for r in sel if r[body["key"]] == code]
            if len(g) < plan["min_cohort"]:
                suppressed.append(code)
            else:
                groups.append({"code": code, "sum": _total(g, body["column"]), "cohort": len(g)})
        return {"Groups": {"groups": groups, "suppressed": suppressed}}
    _require(n, plan)
    col = body["column"]
    if kind == "Sum":
        return {"Sum": {"sum": _total(sel, col), "cohort": n}}
    if kind == "Avg":
        s = _total(sel, col)
        return {"Avg": {"sum": s, "count": n, "avg": s // n}}
    values = [r[col] for r in sel]
    return {kind: {"value": min(values) if kind == "Min" else max(values), "cohort": n}}


def result(spec: QuerySpec, manifest, ans: dict) -> dict:
    """The bundle's human-facing result for a proved Answer: labels, not codes."""
    (kind, body), = ans.items()
    if kind == "Groups":
        labels = {}
        for c in manifest.schema:
            if c["name"] == spec.group_key:
                labels = {code: label for label, code in c["categories"].items()}
        return {
            "group_by": spec.group_key,
            "column": spec.column,
            "groups": {labels[g["code"]]: g["sum"] for g in body["groups"]},
            "cohorts": {labels[g["code"]]: g["cohort"] for g in body["groups"]},
            "suppressed": [labels[c] for c in body["suppressed"]],
        }
    if kind == "Count":
        return {"value": body["count"], "cohort": body["count"]}
    if kind == "Avg":
        return {"sum": body["sum"], "count": body["count"], "avg": body["avg"], "cohort": body["count"]}
    if kind == "Sum":
        return {"value": body["sum"], "cohort": body["cohort"]}
    return {"value": body["value"], "cohort": body["cohort"]}
