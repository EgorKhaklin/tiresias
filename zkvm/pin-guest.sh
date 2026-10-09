#!/bin/sh
# Rebuild the guest in RISC Zero's pinned Docker image and pin it: the binary the
# prover embeds, and its image id. The build is reproducible, so on any machine
# this leaves pinned/ unchanged unless the guest's source changed; CI runs it and
# fails on any difference. Needs Docker and `rzup install rust 1.97.0`: risc0-build
# reads that toolchain's version to choose the flags it passes into the image.
set -eu
cd "$(dirname "$0")"
cargo build --release -p tiresias-methods
cp target/riscv-guest/tiresias-methods/tiresias-guest/riscv32im-risc0-zkvm-elf/docker/tiresias-guest.bin pinned/
cargo build --release -p tiresias-prover
target/release/tiresias-prover image-id | sed -e 's/.*"image_id":"\([0-9a-f]*\)".*/\1/' > pinned/image-id
echo "pinned guest $(cat pinned/image-id)"
