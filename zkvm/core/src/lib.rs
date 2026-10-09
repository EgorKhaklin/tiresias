//! What the guest proves, as plain types: the query plan, the answer, and the
//! journal that binds them to a commitment. The guest and the host share these,
//! and `answer` is the whole of the query semantics.

use serde::{Deserialize, Serialize};

/// The journal format. A verifier refuses any other.
pub const JOURNAL_VERSION: u32 = 1;

/// Prefixed to everything the commitment hashes, so a commitment can never be
/// mistaken for the hash of anything else.
pub const COMMITMENT_DOMAIN: &[u8] = b"tiresias.commitment.v1\0";

#[derive(Serialize, Deserialize, Clone, Copy, Debug, PartialEq, Eq)]
pub enum Op {
    Eq,
    Ne,
    Lt,
    Gt,
    Le,
    Ge,
}

#[derive(Serialize, Deserialize, Clone, Debug, PartialEq, Eq)]
pub enum Pred {
    Cmp { column: u32, op: Op, value: i64 },
    And(Box<Pred>, Box<Pred>),
    Or(Box<Pred>, Box<Pred>),
    Not(Box<Pred>),
}

#[derive(Serialize, Deserialize, Clone, Debug, PartialEq, Eq)]
pub enum Aggregate {
    Count,
    Sum {
        column: u32,
    },
    Avg {
        column: u32,
    },
    Min {
        column: u32,
    },
    Max {
        column: u32,
    },
    /// SUM(column) for each code of the categorical `key` column, in order.
    GroupSum {
        column: u32,
        key: u32,
        codes: Vec<i64>,
    },
}

/// A query, compiled against a dataset's public schema. The verifier compiles
/// the same SQL itself and requires this exact plan in the journal.
#[derive(Serialize, Deserialize, Clone, Debug, PartialEq, Eq)]
pub struct Plan {
    pub aggregate: Aggregate,
    pub filter: Option<Pred>,
    /// No answer may describe fewer rows than this.
    pub min_cohort: u64,
}

#[derive(Serialize, Deserialize, Clone, Debug, PartialEq, Eq)]
pub struct Group {
    pub code: i64,
    pub sum: i64,
    pub cohort: u64,
}

#[derive(Serialize, Deserialize, Clone, Debug, PartialEq, Eq)]
pub enum Answer {
    Count {
        count: u64,
    },
    Sum {
        sum: i64,
        cohort: u64,
    },
    Avg {
        sum: i64,
        count: u64,
        avg: i64,
    },
    Min {
        value: i64,
        cohort: u64,
    },
    Max {
        value: i64,
        cohort: u64,
    },
    /// Groups at or above the cohort floor, and the codes of those below it.
    Groups {
        groups: Vec<Group>,
        suppressed: Vec<i64>,
    },
}

/// The private input. Only the guest sees it.
#[derive(Serialize, Deserialize, Clone, Debug)]
pub struct Input {
    pub salt: [u8; 32],
    pub schema_digest: [u8; 32],
    pub columns: u32,
    /// Row-major cells, `columns` per row.
    pub cells: Vec<i64>,
    pub plan: Plan,
}

/// The public output: what the receipt proves.
#[derive(Serialize, Deserialize, Clone, Debug, PartialEq, Eq)]
pub struct Journal {
    pub version: u32,
    pub commitment: [u8; 32],
    /// The schema the commitment was made under, so a verifier can check it is
    /// the one the manifest publishes.
    pub schema_digest: [u8; 32],
    pub plan: Plan,
    pub answer: Answer,
}

/// The bytes the commitment hashes: the domain, the salt, the schema digest,
/// the shape, then every cell as a little-endian i64.
pub fn commitment_preimage(input: &Input) -> Vec<u8> {
    let rows = row_count(input);
    let mut out = Vec::with_capacity(COMMITMENT_DOMAIN.len() + 80 + input.cells.len() * 8);
    out.extend_from_slice(COMMITMENT_DOMAIN);
    out.extend_from_slice(&input.salt);
    out.extend_from_slice(&input.schema_digest);
    out.extend_from_slice(&(input.columns as u64).to_le_bytes());
    out.extend_from_slice(&(rows as u64).to_le_bytes());
    for cell in &input.cells {
        out.extend_from_slice(&cell.to_le_bytes());
    }
    out
}

fn row_count(input: &Input) -> usize {
    let cols = input.columns as usize;
    assert!(cols > 0, "a dataset has at least one column");
    assert!(
        input.cells.len().is_multiple_of(cols),
        "the cells do not fill whole rows"
    );
    input.cells.len() / cols
}

fn cell(row: &[i64], column: u32) -> i64 {
    *row.get(column as usize)
        .expect("the plan names a column the dataset does not have")
}

fn holds(pred: &Pred, row: &[i64]) -> bool {
    match pred {
        Pred::Cmp { column, op, value } => {
            let v = cell(row, *column);
            match op {
                Op::Eq => v == *value,
                Op::Ne => v != *value,
                Op::Lt => v < *value,
                Op::Gt => v > *value,
                Op::Le => v <= *value,
                Op::Ge => v >= *value,
            }
        }
        Pred::And(a, b) => holds(a, row) && holds(b, row),
        Pred::Or(a, b) => holds(a, row) || holds(b, row),
        Pred::Not(a) => !holds(a, row),
    }
}

fn total(rows: &[&[i64]], column: u32) -> i64 {
    rows.iter().fold(0i64, |acc, r| {
        acc.checked_add(cell(r, column))
            .expect("the sum does not fit in 64 bits")
    })
}

fn require_cohort(cohort: usize, plan: &Plan) {
    assert!(
        cohort as u64 >= plan.min_cohort,
        "the query describes {cohort} rows, fewer than the minimum cohort of {}",
        plan.min_cohort
    );
}

/// Evaluate the plan over the rows. Panics, so that no proof exists, when the
/// plan is malformed, a sum overflows, or an answer would describe too few rows.
pub fn answer(input: &Input) -> Answer {
    let plan = &input.plan;
    assert!(plan.min_cohort >= 1, "the minimum cohort is at least 1");
    let cols = input.columns as usize;
    row_count(input);
    let selected: Vec<&[i64]> = input
        .cells
        .chunks(cols)
        .filter(|row| plan.filter.as_ref().is_none_or(|p| holds(p, row)))
        .collect();
    let n = selected.len();
    match &plan.aggregate {
        Aggregate::Count => {
            require_cohort(n, plan);
            Answer::Count { count: n as u64 }
        }
        Aggregate::Sum { column } => {
            require_cohort(n, plan);
            Answer::Sum {
                sum: total(&selected, *column),
                cohort: n as u64,
            }
        }
        Aggregate::Avg { column } => {
            require_cohort(n, plan);
            let sum = total(&selected, *column);
            Answer::Avg {
                sum,
                count: n as u64,
                avg: sum.div_euclid(n as i64),
            }
        }
        Aggregate::Min { column } => {
            require_cohort(n, plan);
            let value = selected
                .iter()
                .map(|r| cell(r, *column))
                .min()
                .expect("a cohort is never empty");
            Answer::Min {
                value,
                cohort: n as u64,
            }
        }
        Aggregate::Max { column } => {
            require_cohort(n, plan);
            let value = selected
                .iter()
                .map(|r| cell(r, *column))
                .max()
                .expect("a cohort is never empty");
            Answer::Max {
                value,
                cohort: n as u64,
            }
        }
        Aggregate::GroupSum { column, key, codes } => {
            assert!(!codes.is_empty(), "GROUP BY needs at least one category");
            for (i, c) in codes.iter().enumerate() {
                assert!(!codes[..i].contains(c), "GROUP BY codes are distinct");
            }
            let mut groups = Vec::new();
            let mut suppressed = Vec::new();
            for &code in codes {
                let rows: Vec<&[i64]> = selected
                    .iter()
                    .copied()
                    .filter(|r| cell(r, *key) == code)
                    .collect();
                if (rows.len() as u64) < plan.min_cohort {
                    suppressed.push(code);
                } else {
                    groups.push(Group {
                        code,
                        sum: total(&rows, *column),
                        cohort: rows.len() as u64,
                    });
                }
            }
            Answer::Groups { groups, suppressed }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn input(aggregate: Aggregate, filter: Option<Pred>, min_cohort: u64) -> Input {
        // dept, salary: three in dept 0, two in dept 1, one in dept 2
        let rows = [[0, 100], [0, 200], [0, 300], [1, -50], [1, 70], [2, 9]];
        Input {
            salt: [7; 32],
            schema_digest: [9; 32],
            columns: 2,
            cells: rows.iter().flatten().copied().collect(),
            plan: Plan {
                aggregate,
                filter,
                min_cohort,
            },
        }
    }

    fn eq(column: u32, value: i64) -> Option<Pred> {
        Some(Pred::Cmp {
            column,
            op: Op::Eq,
            value,
        })
    }

    #[test]
    fn count_sum_avg_min_max() {
        assert_eq!(
            answer(&input(Aggregate::Count, None, 1)),
            Answer::Count { count: 6 }
        );
        assert_eq!(
            answer(&input(Aggregate::Sum { column: 1 }, eq(0, 0), 3)),
            Answer::Sum {
                sum: 600,
                cohort: 3
            }
        );
        assert_eq!(
            answer(&input(Aggregate::Avg { column: 1 }, eq(0, 1), 2)),
            Answer::Avg {
                sum: 20,
                count: 2,
                avg: 10
            }
        );
        assert_eq!(
            answer(&input(Aggregate::Min { column: 1 }, None, 1)),
            Answer::Min {
                value: -50,
                cohort: 6
            }
        );
        assert_eq!(
            answer(&input(Aggregate::Max { column: 1 }, None, 1)),
            Answer::Max {
                value: 300,
                cohort: 6
            }
        );
    }

    #[test]
    fn avg_floors_toward_negative_infinity() {
        let mut i = input(Aggregate::Avg { column: 1 }, eq(0, 1), 1);
        i.cells = vec![1, -7, 1, 0];
        assert_eq!(
            answer(&i),
            Answer::Avg {
                sum: -7,
                count: 2,
                avg: -4
            }
        );
    }

    #[test]
    fn operators_and_connectives() {
        let lt = Pred::Cmp {
            column: 1,
            op: Op::Lt,
            value: 100,
        };
        let ge = Pred::Cmp {
            column: 1,
            op: Op::Ge,
            value: 300,
        };
        let either = Some(Pred::Or(Box::new(lt.clone()), Box::new(ge)));
        assert_eq!(
            answer(&input(Aggregate::Count, either, 1)),
            Answer::Count { count: 4 }
        );
        let both = Some(Pred::And(
            Box::new(lt.clone()),
            Box::new(Pred::Not(Box::new(eq(0, 2).unwrap()))),
        ));
        assert_eq!(
            answer(&input(Aggregate::Count, both, 1)),
            Answer::Count { count: 2 }
        );
        for (op, n) in [
            (Op::Eq, 1),
            (Op::Ne, 5),
            (Op::Lt, 4),
            (Op::Gt, 1),
            (Op::Le, 5),
            (Op::Ge, 2),
        ] {
            let p = Some(Pred::Cmp {
                column: 1,
                op,
                value: 200,
            });
            assert_eq!(
                answer(&input(Aggregate::Count, p, 1)),
                Answer::Count { count: n },
                "{op:?}"
            );
        }
    }

    #[test]
    fn group_by_suppresses_small_groups() {
        let agg = Aggregate::GroupSum {
            column: 1,
            key: 0,
            codes: vec![0, 1, 2],
        };
        assert_eq!(
            answer(&input(agg, None, 2)),
            Answer::Groups {
                groups: vec![
                    Group {
                        code: 0,
                        sum: 600,
                        cohort: 3
                    },
                    Group {
                        code: 1,
                        sum: 20,
                        cohort: 2
                    }
                ],
                suppressed: vec![2],
            }
        );
    }

    #[test]
    #[should_panic(expected = "minimum cohort")]
    fn refuses_small_cohort() {
        answer(&input(Aggregate::Sum { column: 1 }, eq(0, 2), 2));
    }

    #[test]
    #[should_panic(expected = "64 bits")]
    fn refuses_overflow() {
        let mut i = input(Aggregate::Sum { column: 1 }, None, 1);
        i.cells = vec![0, i64::MAX, 0, 1];
        answer(&i);
    }

    #[test]
    #[should_panic(expected = "column")]
    fn refuses_unknown_column() {
        answer(&input(Aggregate::Sum { column: 2 }, None, 1));
    }

    #[test]
    #[should_panic(expected = "whole rows")]
    fn refuses_ragged_cells() {
        let mut i = input(Aggregate::Count, None, 1);
        i.cells.pop();
        answer(&i);
    }

    #[test]
    fn preimage_layout() {
        let i = input(Aggregate::Count, None, 1);
        let p = commitment_preimage(&i);
        assert_eq!(&p[..COMMITMENT_DOMAIN.len()], COMMITMENT_DOMAIN);
        assert_eq!(p.len(), COMMITMENT_DOMAIN.len() + 32 + 32 + 8 + 8 + 12 * 8);
        let tail = &p[p.len() - 8..];
        assert_eq!(tail, &9i64.to_le_bytes());
    }
}
