//! Builds the guest in RISC Zero's pinned Docker image, so its image id is the
//! same on every machine. TIRESIAS_LOCAL_GUEST=1 builds it with the local
//! toolchain instead: faster, but the image id then differs from a release's,
//! and receipts from one do not verify under the other.

use std::collections::HashMap;

use risc0_build::{embed_methods_with_options, DockerOptionsBuilder, GuestOptionsBuilder};

fn main() {
    println!("cargo:rerun-if-env-changed=TIRESIAS_LOCAL_GUEST");
    let mut options = GuestOptionsBuilder::default();
    if std::env::var_os("TIRESIAS_LOCAL_GUEST").is_none() {
        let root = concat!(env!("CARGO_MANIFEST_DIR"), "/..");
        options.use_docker(
            DockerOptionsBuilder::default()
                .root_dir(root)
                .build()
                .unwrap(),
        );
    }
    embed_methods_with_options(HashMap::from([(
        "tiresias-guest",
        options.build().unwrap(),
    )]));
}
