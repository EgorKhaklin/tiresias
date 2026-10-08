"""A table-free query specification.

The SQL the analyst writes becomes a QuerySpec: an aggregate over an optional
predicate, with no data attached. The prover (who holds the private rows)
binds the table at proof time via `to_pane_query`. This separation is the whole
point: a query is public; the data it runs over is not.
"""

from __future__ import annotations

from dataclasses import dataclass

from tiresias.query.pane_ast import (
    AndE,
    Col,
    CountQ,
    EqE,
    From,
    GtE,
    LitI,
    LtE,
    MaxQ,
    MinQ,
    NotE,
    OrE,
    PExpr,
    Query,
    SumQ,
    Table,
    Where,
    _Bin,
)

# Aggregates proven over the committed table via the Glass Pane/Frost backend.
AGG_SUM = "sum"
AGG_COUNT = "count"
AGG_AVG = "avg"  # proven as the (sum, count) pair; the verifier divides
AGG_MIN = "min"
AGG_MAX = "max"
AGG_GROUPBY = "groupby"  # proven as one filtered SUM per group


@dataclass
class QuerySpec:
    agg: str
    column: str | None  # None for COUNT(*)
    predicate: PExpr | None
    text: str = ""  # the original SQL, for display/audit
    group_key: str | None = None  # the GROUP BY column (categorical)

    def _wrap(self, table: Table) -> Query:
        base: Query = From(table)
        if self.predicate is not None:
            base = Where(self.predicate, base)
        return base

    def to_pane_query(self, table: Table) -> Query:
        if self.agg == AGG_SUM:
            assert self.column is not None
            return SumQ(self.column, self._wrap(table))
        if self.agg == AGG_COUNT:
            return CountQ(self._wrap(table))
        if self.agg == AGG_MIN:
            assert self.column is not None
            return MinQ(self.column, self._wrap(table))
        if self.agg == AGG_MAX:
            assert self.column is not None
            return MaxQ(self.column, self._wrap(table))
        raise ValueError(
            f"agg {self.agg!r} has no single-query lowering; AVG and GROUP BY "
            "are decomposed by the prover"
        )

    def group_query(self, table: Table, code: int) -> Query:
        """A single group's SUM query: SUM(column) WHERE group_key == code
        (AND any base predicate)."""
        assert self.column is not None and self.group_key is not None
        eq: PExpr = EqE(Col(self.group_key), LitI(code))
        pred: PExpr = AndE(self.predicate, eq) if self.predicate is not None else eq
        return SumQ(self.column, Where(pred, From(table)))

    def comparison_columns(self) -> set[str]:
        """Columns subjected to an ordered comparison (MIN/MAX target, or any
        column inside a < / > filter). These are bounded by RANGE_MAX."""
        cols: set[str] = set()
        if self.agg in (AGG_MIN, AGG_MAX) and self.column:
            cols.add(self.column)

        def cols_in(e: PExpr) -> set[str]:
            if isinstance(e, Col):
                return {e.name}
            if isinstance(e, NotE):
                return cols_in(e.a)
            if isinstance(e, _Bin):
                return cols_in(e.a) | cols_in(e.b)
            return set()

        def walk(e: PExpr) -> None:
            if isinstance(e, (LtE, GtE)):
                cols.update(cols_in(e))
            elif isinstance(e, (AndE, OrE)):
                walk(e.a)
                walk(e.b)
            elif isinstance(e, NotE):
                walk(e.a)

        if self.predicate is not None:
            walk(self.predicate)
        return cols

    def avg_parts(self, table: Table) -> tuple[Query, Query]:
        """AVG is proven as two queries: SUM(col) and COUNT(*) over the same rows."""
        assert self.column is not None
        return (
            SumQ(self.column, self._wrap(table)),
            CountQ(self._wrap(table)),
        )
