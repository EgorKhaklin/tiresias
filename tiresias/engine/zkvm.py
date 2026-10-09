"""The proving system: the RISC Zero zkVM, through the tiresias-prover binary.

The guest program (zkvm/methods/guest) reads the private rows, recomputes the
dataset's commitment, answers the query and commits only the commitment, the
query plan and the answer. A receipt for it proves that answer is the true one
over the committed rows. The binary proves on this machine only, and it neither
makes nor accepts development-mode (fake) receipts.

Build it once with `cargo build --release` in zkvm/, or point TIRESIAS_PROVER at
a built binary.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess

from tiresias import config

HERE = os.path.dirname(__file__)
BUILT = os.path.normpath(os.path.join(HERE, "..", "..", "zkvm", "target", "release", "tiresias-prover"))
RISC0_VERSION = "3.0.6"


class ProverUnavailable(RuntimeError):
    """The tiresias-prover binary is not built or not found."""


class Rejected(ValueError):
    """A receipt that does not verify."""


class Refused(ValueError):
    """The guest refused to answer, so no proof exists (too few rows, an overflow)."""


def binary() -> str:
    """The tiresias-prover to run: TIRESIAS_PROVER, else this checkout's build, else PATH."""
    for candidate in (config.PROVER, BUILT, shutil.which("tiresias-prover") or ""):
        if candidate and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    raise ProverUnavailable(
        "tiresias-prover is not built. Install the RISC Zero toolchain (rzup), run "
        "`cargo build --release` in zkvm/, or set TIRESIAS_PROVER to the binary."
    )


def available() -> bool:
    try:
        binary()
        return True
    except ProverUnavailable:
        return False


def _run(cmd: str, request: dict | None) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("RISC0_DEV_MODE", "BONSAI_"))}
    proc = subprocess.run(
        [binary(), cmd],
        input=json.dumps(request or {}),
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    message = proc.stderr.strip().splitlines()[-1] if proc.stderr.strip() else f"exit {proc.returncode}"
    if proc.returncode == 1 or (proc.returncode == 2 and cmd == "verify"):
        raise Rejected(message)
    if proc.returncode == 3:
        raise Refused(_guest_reason(proc.stderr) or message)
    if proc.returncode != 0:
        raise RuntimeError(f"tiresias-prover {cmd} failed: {message}")
    return json.loads(proc.stdout)


def _guest_reason(stderr: str) -> str:
    """The guest's own panic message, when there is one."""
    for line in reversed(stderr.splitlines()):
        if "panicked" in line or "Guest panicked" in line:
            return line.split(":", 1)[-1].strip() if "Guest panicked" in line else line.strip()
    return ""


def image_id() -> str:
    """The image id of the guest this binary proves with and trusts."""
    return _run("image-id", None)["image_id"]


def prove(salt: bytes, schema_digest: bytes, columns: int, cells: list[int], plan: dict) -> dict:
    """Prove a plan over the rows. Returns {journal, receipt, image_id, cycles, segments}."""
    return _run("prove", {
        "salt": salt.hex(),
        "schema_digest": schema_digest.hex(),
        "columns": columns,
        "cells": cells,
        "plan": plan,
    })


def verify(receipt: str) -> dict:
    """Verify a receipt against the Tiresias guest. Returns {journal, image_id};
    raises Rejected if it does not verify."""
    return _run("verify", {"receipt": receipt})
