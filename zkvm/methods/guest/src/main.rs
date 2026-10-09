//! The Tiresias guest. It reads the private rows and the query plan, recomputes
//! the dataset's commitment, answers the query, and commits only the commitment,
//! the schema digest, the plan and the answer. A receipt for this program is a
//! proof that the answer is the true answer over the rows that commitment binds.

use risc0_zkvm::guest::env;
use risc0_zkvm::sha::{Impl, Sha256};
use tiresias_core::{answer, commitment_preimage, Input, Journal, JOURNAL_VERSION};

fn main() {
    let input: Input = env::read();
    let digest = Impl::hash_bytes(&commitment_preimage(&input));
    let mut commitment = [0u8; 32];
    commitment.copy_from_slice(digest.as_bytes());
    let answer = answer(&input);
    env::commit(&Journal {
        version: JOURNAL_VERSION,
        commitment,
        schema_digest: input.schema_digest,
        plan: input.plan,
        answer,
    });
}
