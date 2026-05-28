"""Python representation of Glass's Pane query algebra.

Mirrors the `Query` / `PExpr` / `Table` ADTs in ~/Desktop/Glass/examples/pane/pane.glass
one-to-one. Each node knows how to emit itself as Glass source, so the engine can
template a real Pane value into a driver that the Glass interpreter (run_query) and
the Frost prover (prove_pane) both consume from the same AST.
"""

from __future__ import annotations

from dataclasses import dataclass, field


def _gstr(s: str) -> str:
    """A Glass string literal. Escapes quotes, backslashes, and control chars so
    column names / category labels coming from data cannot break the generated
    Glass source or inject into it."""
    return (
        '"'
        + s.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
        + '"'
    )


# --- scalar values (cells) ---------------------------------------------------
class Val:
    def to_glass(self) -> str:  # pragma: no cover - interface
        raise NotImplementedError


@dataclass(frozen=True)
class VInt(Val):
    n: int

    def to_glass(self) -> str:
        return f"VInt({self.n})"


@dataclass(frozen=True)
class VStr(Val):
    s: str

    def to_glass(self) -> str:
        return f"VStr({_gstr(self.s)})"


@dataclass(frozen=True)
class VBool(Val):
    b: bool

    def to_glass(self) -> str:
        return f"VBool({'true' if self.b else 'false'})"


# --- predicate / scalar expressions ------------------------------------------
class PExpr:
    def to_glass(self) -> str:  # pragma: no cover - interface
        raise NotImplementedError


@dataclass(frozen=True)
class Col(PExpr):
    name: str

    def to_glass(self) -> str:
        return f"Col({_gstr(self.name)})"


@dataclass(frozen=True)
class LitI(PExpr):
    n: int

    def to_glass(self) -> str:
        return f"LitI({self.n})"


@dataclass(frozen=True)
class LitS(PExpr):
    s: str

    def to_glass(self) -> str:
        return f"LitS({_gstr(self.s)})"


@dataclass(frozen=True)
class LitB(PExpr):
    b: bool

    def to_glass(self) -> str:
        return f"LitB({'true' if self.b else 'false'})"


@dataclass(frozen=True)
class _Bin(PExpr):
    a: PExpr
    b: PExpr
    _ctor = ""

    def to_glass(self) -> str:
        return f"{self._ctor}({self.a.to_glass()}, {self.b.to_glass()})"


class EqE(_Bin):
    _ctor = "EqE"


class LtE(_Bin):
    _ctor = "LtE"


class GtE(_Bin):
    _ctor = "GtE"


class AndE(_Bin):
    _ctor = "AndE"


class OrE(_Bin):
    _ctor = "OrE"


class AddE(_Bin):
    _ctor = "AddE"


class SubE(_Bin):
    _ctor = "SubE"


class MulE(_Bin):
    _ctor = "MulE"


@dataclass(frozen=True)
class NotE(PExpr):
    a: PExpr

    def to_glass(self) -> str:
        return f"NotE({self.a.to_glass()})"


# --- table -------------------------------------------------------------------
@dataclass
class Table:
    """An in-memory table: ordered column names + rows of Python scalars.

    Scalars are coerced to Val automatically: int -> VInt, bool -> VBool,
    str -> VStr. The column order is fixed and shared by every row.
    """

    columns: list[str]
    rows: list[list] = field(default_factory=list)

    @staticmethod
    def _coerce(v) -> Val:
        if isinstance(v, bool):
            return VBool(v)
        if isinstance(v, int):
            return VInt(v)
        if isinstance(v, str):
            return VStr(v)
        if isinstance(v, Val):
            return v
        raise TypeError(f"unsupported cell type: {type(v).__name__}")

    def _row_glass(self, row: list) -> str:
        if len(row) != len(self.columns):
            raise ValueError(
                f"row has {len(row)} cells, expected {len(self.columns)}"
            )
        cells = ", ".join(
            f"Pair({_gstr(c)}, {self._coerce(v).to_glass()})"
            for c, v in zip(self.columns, row)
        )
        return f"Row([{cells}])"

    def to_glass(self) -> str:
        rows = ",\n    ".join(self._row_glass(r) for r in self.rows)
        return f"Table([\n    {rows}\n  ])"


# --- queries -----------------------------------------------------------------
class Query:
    def to_glass(self) -> str:  # pragma: no cover - interface
        raise NotImplementedError


@dataclass
class From(Query):
    table: Table

    def to_glass(self) -> str:
        return f"From({self.table.to_glass()})"


@dataclass
class Where(Query):
    pred: PExpr
    sub: Query

    def to_glass(self) -> str:
        return f"Where({self.pred.to_glass()}, {self.sub.to_glass()})"


@dataclass
class SumQ(Query):
    col: str
    sub: Query

    def to_glass(self) -> str:
        return f"SumQ({_gstr(self.col)}, {self.sub.to_glass()})"


@dataclass
class CountQ(Query):
    sub: Query

    def to_glass(self) -> str:
        return f"CountQ({self.sub.to_glass()})"


@dataclass
class AvgQ(Query):
    col: str
    sub: Query

    def to_glass(self) -> str:
        return f"AvgQ({_gstr(self.col)}, {self.sub.to_glass()})"


@dataclass
class MinQ(Query):
    col: str
    sub: Query

    def to_glass(self) -> str:
        return f"MinQ({_gstr(self.col)}, {self.sub.to_glass()})"


@dataclass
class MaxQ(Query):
    col: str
    sub: Query

    def to_glass(self) -> str:
        return f"MaxQ({_gstr(self.col)}, {self.sub.to_glass()})"


@dataclass
class GroupByQ(Query):
    key_col: str
    sum_col: str
    groups: list[int]
    sub: Query

    def to_glass(self) -> str:
        gs = "[" + ", ".join(str(g) for g in self.groups) + "]"
        return (
            f"GroupByQ({_gstr(self.key_col)}, {_gstr(self.sum_col)}, "
            f"{gs}, {self.sub.to_glass()})"
        )
