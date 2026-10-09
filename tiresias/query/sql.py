"""A deliberately small SQL parser for the supported query subset.

Grammar (case-insensitive keywords):

    SELECT SUM(col) | COUNT(*) | AVG(col)  [ WHERE cond ]
    cond   := orterm ( OR orterm )*
    orterm := factor ( AND factor )*
    factor := col ( = | != | < | > | <= | >= ) value
    value  := number | 'string'

No parentheses, no joins. Category and boolean literals are translated to their
codes through the manifest; integers are 64-bit.
"""

from __future__ import annotations

import re

from tiresias.engine.commit import Manifest
from tiresias.query.spec import (
    AGG_AVG,
    AGG_COUNT,
    AGG_GROUPBY,
    AGG_MAX,
    AGG_MIN,
    AGG_SUM,
    I64_MAX,
    I64_MIN,
    And,
    Cmp,
    Or,
    Pred,
    QuerySpec,
)

_SELECT = re.compile(
    r"""^\s*select\s+
        (?P<agg>sum|count|avg|min|max)\s*\(\s*(?P<col>\*|[A-Za-z_]\w*)\s*\)\s*
        (?:where\s+(?P<where>.+?))?\s*$""",
    re.IGNORECASE | re.VERBOSE,
)
_GROUPBY = re.compile(
    r"""^\s*select\s+
        (?:[A-Za-z_]\w*\s*,\s*)?            # optional "key," projection
        sum\s*\(\s*(?P<col>[A-Za-z_]\w*)\s*\)\s*
        (?:where\s+(?P<where>.+?)\s+)?
        group\s+by\s+(?P<key>[A-Za-z_]\w*)\s*$""",
    re.IGNORECASE | re.VERBOSE,
)
_AGG_MAP = {
    "sum": AGG_SUM, "count": AGG_COUNT, "avg": AGG_AVG,
    "min": AGG_MIN, "max": AGG_MAX,
}
_FACTOR = re.compile(
    r"""^\s*(?P<col>[A-Za-z_]\w*)\s*
        (?P<op><=|>=|!=|=|<|>)\s*
        (?P<val>'[^']*'|"[^"]*"|-?\d+)\s*$""",
    re.VERBOSE,
)


class SqlError(ValueError):
    pass


def _value_to_code(manifest: Manifest, column: str, raw: str) -> int:
    raw = raw.strip()
    if (raw.startswith("'") and raw.endswith("'")) or (
        raw.startswith('"') and raw.endswith('"')
    ):
        return manifest.code_for(column, raw[1:-1])
    value = int(raw)
    if not I64_MIN <= value <= I64_MAX:
        raise SqlError(f"{value} does not fit in 64 bits")
    return manifest.code_for(column, value)


def _factor(manifest: Manifest, text: str) -> Pred:
    m = _FACTOR.match(text)
    if not m:
        raise SqlError(f"cannot parse condition: {text!r}")
    col, op, val = m.group("col"), m.group("op"), m.group("val")
    return Cmp(col, op, _value_to_code(manifest, col, val))


def _orterm(manifest: Manifest, text: str) -> Pred:
    parts = re.split(r"\s+and\s+", text, flags=re.IGNORECASE)
    expr = _factor(manifest, parts[0])
    for p in parts[1:]:
        expr = And(expr, _factor(manifest, p))
    return expr


def _condition(manifest: Manifest, text: str) -> Pred:
    parts = re.split(r"\s+or\s+", text, flags=re.IGNORECASE)
    expr = _orterm(manifest, parts[0])
    for p in parts[1:]:
        expr = Or(expr, _orterm(manifest, p))
    return expr


def parse(sql: str, manifest: Manifest) -> QuerySpec:
    # GROUP BY first (it also contains the word SUM)
    if re.search(r"\bgroup\s+by\b", sql, re.IGNORECASE):
        g = _GROUPBY.match(sql)
        if not g:
            raise SqlError(
                "expected: SELECT [key,] SUM(col) [WHERE ...] GROUP BY key"
            )
        key = g.group("key")
        col = next((c for c in manifest.schema if c["name"] == key), None)
        if col is None:
            raise SqlError(f"GROUP BY column {key!r} is not in the dataset")
        if col["type"] != "category":
            raise SqlError(
                f"GROUP BY is supported on categorical columns only; {key!r} "
                f"is {col['type']}"
            )
        predicate = _condition(manifest, g.group("where")) if g.group("where") else None
        return QuerySpec(
            agg=AGG_GROUPBY, column=g.group("col"), predicate=predicate,
            group_key=key, text=sql.strip(),
        )

    m = _SELECT.match(sql)
    if not m:
        raise SqlError(
            "expected: SELECT SUM|COUNT|AVG|MIN|MAX(col) [WHERE ...]"
        )
    agg = m.group("agg").lower()
    col = m.group("col")
    where = m.group("where")

    if agg == "count":
        if col != "*":
            raise SqlError("only COUNT(*) is supported")
        column = None
    else:
        if col == "*":
            raise SqlError(f"{agg.upper()} needs a column, not *")
        column = col

    predicate = _condition(manifest, where) if where else None
    return QuerySpec(
        agg=_AGG_MAP[agg], column=column, predicate=predicate, text=sql.strip()
    )
