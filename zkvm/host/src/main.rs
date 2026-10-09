//! tiresias-prover: proves Tiresias queries in the RISC Zero zkVM and verifies
//! the receipts. It speaks JSON on stdin and stdout.
//!
//!   tiresias-prover image-id   the guest's image id, the one id it trusts
//!   tiresias-prover prove      {salt, schema_digest, columns, cells, plan} -> {journal, receipt, ...}
//!   tiresias-prover verify     {receipt} -> {journal, image_id}
//!
//! Proving runs on this machine only, in RISC Zero's r0vm (RISC0_SERVER_PATH, or
//! r0vm on PATH): there is no remote prover, and fake (development mode)
//! receipts are neither produced nor accepted.
//!
//! Exit status: 0 done, 1 the receipt does not verify, 2 malformed input,
//! 3 no proof exists (the guest refused: too few rows, an overflow, ...).

use std::io::{Read, Write};
use std::process::ExitCode;
use std::sync::OnceLock;

use anyhow::{anyhow, bail, Context, Result};
use base64::{engine::general_purpose::STANDARD as B64, Engine};
use bincode::Options;
use risc0_zkvm::{
    compute_image_id, sha::Digest, ExecutorEnv, ExternalProver, Prover, ProverOpts, Receipt,
};
use serde::{Deserialize, Serialize};
use tiresias_core::{Answer, Input, Journal, Plan, JOURNAL_VERSION};

/// The guest, built reproducibly in RISC Zero's Docker image and pinned in the
/// repository (pin-guest.sh). Its image id is the only one this binary trusts.
const GUEST: &[u8] = include_bytes!("../../pinned/tiresias-guest.bin");

/// A succinct receipt is about 250 KB; nothing honest comes near this.
const RECEIPT_LIMIT: u64 = 8 << 20;

#[derive(Deserialize)]
struct ProveRequest {
    salt: String,
    schema_digest: String,
    columns: u32,
    cells: Vec<i64>,
    plan: Plan,
}

#[derive(Deserialize)]
struct VerifyRequest {
    receipt: String,
}

#[derive(Serialize)]
struct JournalOut {
    version: u32,
    commitment: String,
    schema_digest: String,
    plan: Plan,
    answer: Answer,
}

impl From<Journal> for JournalOut {
    fn from(j: Journal) -> Self {
        JournalOut {
            version: j.version,
            commitment: hex::encode(j.commitment),
            schema_digest: hex::encode(j.schema_digest),
            plan: j.plan,
            answer: j.answer,
        }
    }
}

enum Failure {
    Rejected(anyhow::Error),
    Malformed(anyhow::Error),
    Refused(anyhow::Error),
}

fn guest_id() -> Digest {
    static ID: OnceLock<Digest> = OnceLock::new();
    *ID.get_or_init(|| compute_image_id(GUEST).expect("the pinned guest is a RISC Zero program"))
}

fn image_id() -> String {
    guest_id().to_string()
}

/// RISC Zero's prover: RISC0_SERVER_PATH, else the first r0vm on PATH.
fn r0vm() -> Result<std::path::PathBuf> {
    if let Some(path) = std::env::var_os("RISC0_SERVER_PATH") {
        return Ok(path.into());
    }
    std::env::var_os("PATH")
        .iter()
        .flat_map(std::env::split_paths)
        .map(|dir| dir.join("r0vm"))
        .find(|p| p.is_file())
        .ok_or_else(|| anyhow!("r0vm is not installed; run `rzup install r0vm 3.0.6`"))
}

fn codec() -> impl Options {
    bincode::DefaultOptions::new()
        .with_fixint_encoding()
        .with_limit(RECEIPT_LIMIT)
}

fn bytes32(field: &str, s: &str) -> Result<[u8; 32]> {
    let v = hex::decode(s).with_context(|| format!("{field} is not hex"))?;
    v.try_into().map_err(|_| anyhow!("{field} is not 32 bytes"))
}

fn read_stdin<T: for<'de> Deserialize<'de>>() -> Result<T> {
    let mut buf = String::new();
    std::io::stdin()
        .read_to_string(&mut buf)
        .context("reading stdin")?;
    serde_json::from_str(&buf).context("the request is not the expected JSON")
}

fn prove() -> Result<serde_json::Value, Failure> {
    let req: ProveRequest = read_stdin().map_err(Failure::Malformed)?;
    let input = Input {
        salt: bytes32("salt", &req.salt).map_err(Failure::Malformed)?,
        schema_digest: bytes32("schema_digest", &req.schema_digest).map_err(Failure::Malformed)?,
        columns: req.columns,
        cells: req.cells,
        plan: req.plan,
    };
    let env = ExecutorEnv::builder()
        .write(&input)
        .and_then(|b| b.build())
        .map_err(Failure::Malformed)?;
    let r0vm = r0vm().map_err(Failure::Malformed)?;
    let info = ExternalProver::new("tiresias", r0vm)
        .prove_with_opts(env, GUEST, &ProverOpts::succinct())
        .map_err(Failure::Refused)?;
    let receipt = info.receipt;
    let journal: Journal = receipt
        .journal
        .decode()
        .map_err(|e| Failure::Malformed(e.into()))?;
    let bytes = codec()
        .serialize(&receipt)
        .map_err(|e| Failure::Malformed(e.into()))?;
    Ok(serde_json::json!({
        "journal": JournalOut::from(journal),
        "receipt": B64.encode(bytes),
        "image_id": image_id(),
        "cycles": info.stats.total_cycles,
        "segments": info.stats.segments,
    }))
}

fn check(receipt: &Receipt) -> Result<Journal> {
    receipt
        .inner
        .succinct()
        .map_err(|_| anyhow!("the receipt is not succinct"))?;
    receipt.verify(guest_id()).map_err(|e| {
        anyhow!(
            "the receipt does not verify against the Tiresias guest {}: {e}",
            image_id()
        )
    })?;
    let journal: Journal = receipt
        .journal
        .decode()
        .context("the journal does not decode")?;
    if journal.version != JOURNAL_VERSION {
        bail!(
            "journal version {} is not {}",
            journal.version,
            JOURNAL_VERSION
        );
    }
    Ok(journal)
}

fn verify() -> Result<serde_json::Value, Failure> {
    let req: VerifyRequest = read_stdin().map_err(Failure::Malformed)?;
    let bytes = B64
        .decode(req.receipt.trim())
        .map_err(|e| Failure::Malformed(anyhow!("the receipt is not base64: {e}")))?;
    let receipt: Receipt = codec()
        .deserialize(&bytes)
        .map_err(|e| Failure::Rejected(anyhow!("the receipt does not decode: {e}")))?;
    let journal = check(&receipt).map_err(Failure::Rejected)?;
    Ok(serde_json::json!({ "journal": JournalOut::from(journal), "image_id": image_id() }))
}

fn main() -> ExitCode {
    let cmd = std::env::args().nth(1).unwrap_or_default();
    let out = match cmd.as_str() {
        "image-id" => Ok(serde_json::json!({ "image_id": image_id() })),
        "prove" => prove(),
        "verify" => verify(),
        _ => Err(Failure::Malformed(anyhow!(
            "usage: tiresias-prover image-id | prove | verify"
        ))),
    };
    match out {
        Ok(v) => {
            let mut stdout = std::io::stdout().lock();
            let _ = writeln!(stdout, "{v}");
            ExitCode::SUCCESS
        }
        Err(f) => {
            let (code, e) = match f {
                Failure::Rejected(e) => (1, e),
                Failure::Malformed(e) => (2, e),
                Failure::Refused(e) => (3, e),
            };
            eprintln!("{e:#}");
            ExitCode::from(code)
        }
    }
}
