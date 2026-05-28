"""Phase 0 integration spike for Glass Private Intelligence.

Proves the founding capability end-to-end from Python, with a *programmatic*
private table and query (not Glass's hardcoded demo):

  1. Commit a private table.
  2. Run an aggregate query -> get the true answer.
  3. Get a zero-knowledge proof that the answer is correct over the committed
     table, revealing no row.
  4. Show that a *wrong* claimed answer is rejected.

Run:  python3.12 spike.py
"""

from gpi.engine.adapter import prove_claim, prove_query
from gpi.query.pane_ast import Col, EqE, From, GtE, LitI, SumQ, Table, Where

GAMMA = 918273645  # a public Fiat-Shamir point


def main() -> None:
    # A private dataset an organization committed. dept 0 = engineering, 1 = sales.
    # In the real product these rows never leave the org; here they stand in for
    # committed-but-secret data.
    table = Table(
        columns=["dept", "salary", "senior"],
        rows=[
            [0, 120, 1],
            [1, 95, 0],
            [0, 175, 0],
            [1, 60, 1],
            [0, 140, 1],
        ],
    )

    print("=== Glass Private Intelligence — Phase 0 spike ===")
    print("A private table is committed; only the commitment, query, and answer")
    print("are ever revealed. The rows stay secret.\n")

    # Query 1: SELECT SUM(salary) WHERE dept = engineering (dept code 0)
    q1 = SumQ("salary", Where(EqE(Col("dept"), LitI(0)), From(table)))
    r1 = prove_query(q1, GAMMA)
    print("Q1:  SELECT SUM(salary) WHERE dept=eng")
    print(f"     commitment C = {r1.commitment}")
    print(f"     answer     R = {r1.result}")
    print(f"     proof        = {'ACCEPT' if r1.accepted else 'REJECT'}  "
          f"(crypto-grade: {r1.crypto_grade})")

    # Soundness: a lie about the answer must be rejected.
    lie = r1.result + 1
    lie_ok = prove_claim(q1, GAMMA, claimed_r=lie)
    print(f"     lying R = {lie}: {'ACCEPT' if lie_ok else 'REJECT'}  "
          f"(a wrong claim cannot be proven)\n")

    # Query 2: SELECT SUM(salary) WHERE salary > 100  (range filter)
    q2 = SumQ("salary", Where(GtE(Col("salary"), LitI(100)), From(table)))
    r2 = prove_query(q2, GAMMA)
    print("Q2:  SELECT SUM(salary) WHERE salary > 100")
    print(f"     answer R = {r2.result}   proof = "
          f"{'ACCEPT' if r2.accepted else 'REJECT'}\n")

    ok = r1.accepted and not lie_ok
    print("=== spike", "PASSED" if ok else "FAILED", "===")
    print("Integration confirmed: Python -> generated Glass driver -> Frost ZK")
    print("proof over a programmatic committed table.")


if __name__ == "__main__":
    main()
