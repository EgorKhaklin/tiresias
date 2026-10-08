"""The Glass release Tiresias proves with, pinned by tag and by content.

Tiresias reads two files from Glass: the reference interpreter (`glass.py`), which it
imports, and the query prover (`examples/prove/prove_pane.glass`), whose machinery it
runs. Both are pinned by SHA-256, so a proof is only ever produced by the Glass code
this release was tested against.

Where Glass comes from:

    TIRESIAS_GLASS_DIR set     -> that checkout, verified against the pins
    TIRESIAS_GLASS_DIR empty   -> ~/.tiresias/glass/<tag>, cloned on first use, verified

A checkout whose files differ from the pins is refused, naming each file, unless
TIRESIAS_GLASS_UNPINNED=1 (for developing Tiresias and Glass together).
"""

from __future__ import annotations

import hashlib
import importlib.util
import os
import shutil
import subprocess
import sys
from types import ModuleType

GLASS_REPOSITORY = "https://github.com/EgorKhaklin/Glass.git"
GLASS_TAG = "v1.0.0"

# The files Tiresias reads from Glass, and their SHA-256 at GLASS_TAG.
PINNED_FILES = {
    "glass.py": "90409180570fb86bf6a7bd4ab7b4cad714a00cbe0fd68d2999f0bf79b42208cc",
    "examples/prove/prove_pane.glass": "54e066510b3d98d7ab7685863a769fe7b086b7b18688d740d0cae8174cda8094",
}


class GlassPinError(RuntimeError):
    """The Glass checkout is missing, unreachable, or not the pinned release."""


def cache_dir(tag: str = GLASS_TAG) -> str:
    return os.path.join(os.path.expanduser("~/.tiresias"), "glass", tag)


def _explicit_dir() -> str:
    return os.path.expanduser(os.environ.get("TIRESIAS_GLASS_DIR", ""))


def _unpinned() -> bool:
    return os.environ.get("TIRESIAS_GLASS_UNPINNED", "0") == "1"


def resolve(fetch: bool = True) -> str | None:
    """The Glass checkout to use, fetching the pinned tag if allowed and needed.

    Returns None when no checkout exists and `fetch` is False.
    """
    explicit = _explicit_dir()
    if explicit:
        return explicit if os.path.exists(os.path.join(explicit, "glass.py")) else None
    target = cache_dir()
    if os.path.exists(os.path.join(target, "glass.py")):
        return target
    if not fetch:
        return None
    fetch_release(target)
    return target


def fetch_release(target: str, repository: str = GLASS_REPOSITORY, tag: str = GLASS_TAG) -> None:
    """Clone `tag` of Glass into `target` (a shallow, single-tag clone)."""
    os.makedirs(os.path.dirname(target), exist_ok=True)
    partial = target + ".partial"
    shutil.rmtree(partial, ignore_errors=True)
    result = subprocess.run(
        ["git", "clone", "--quiet", "--depth", "1", "--branch", tag, repository, partial],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise GlassPinError(
            f"could not fetch Glass {tag} from {repository}: {result.stderr.strip() or 'git failed'}"
        )
    os.replace(partial, target)


def mismatches(root: str) -> list[str]:
    """The pinned files under `root` that are missing or differ, as readable lines."""
    found = []
    for rel, want in PINNED_FILES.items():
        path = os.path.join(root, rel)
        try:
            with open(path, "rb") as f:
                got = hashlib.sha256(f.read()).hexdigest()
        except OSError:
            found.append(f"{rel}: missing")
            continue
        if got != want:
            found.append(f"{rel}: sha256 {got[:16]}..., pinned {want[:16]}...")
    return found


_verified_root: str | None = None


def glass_root() -> str:
    """The verified Glass checkout. Raises GlassPinError if it cannot be trusted."""
    global _verified_root
    if _verified_root is not None:
        return _verified_root
    root = resolve(fetch=True)
    if root is None:
        raise GlassPinError(
            f"TIRESIAS_GLASS_DIR={_explicit_dir()} has no glass.py; "
            f"unset it to use the pinned Glass {GLASS_TAG}"
        )
    bad = mismatches(root)
    if bad and not _unpinned():
        raise GlassPinError(
            f"the Glass checkout at {root} is not Glass {GLASS_TAG}:\n  "
            + "\n  ".join(bad)
            + "\nUse the pinned release (unset TIRESIAS_GLASS_DIR), or set "
            "TIRESIAS_GLASS_UNPINNED=1 to prove with it anyway."
        )
    _verified_root = root
    return root


_glass_module: ModuleType | None = None


def load_glass() -> ModuleType:
    """Import the verified checkout's glass.py by path, never a `glass` found elsewhere."""
    global _glass_module
    if _glass_module is None:
        path = os.path.join(glass_root(), "glass.py")
        spec = importlib.util.spec_from_file_location("glass", path)
        if spec is None or spec.loader is None:
            raise GlassPinError(f"cannot load {path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules["glass"] = module
        spec.loader.exec_module(module)
        _glass_module = module
    return _glass_module


def describe() -> list[str]:
    """Lines for `tiresias glass`: the pin, the checkout, and whether it matches."""
    lines = [f"pinned:   Glass {GLASS_TAG} ({GLASS_REPOSITORY})"]
    root = resolve(fetch=False)
    if root is None:
        where = _explicit_dir() or cache_dir()
        lines.append(f"checkout: none at {where} (run `tiresias glass --fetch`)")
        return lines
    lines.append(f"checkout: {root}")
    bad = mismatches(root)
    if not bad:
        lines.append("verified: every pinned file matches")
    else:
        lines.append("verified: NO" + (" (TIRESIAS_GLASS_UNPINNED=1 allows it)" if _unpinned() else ""))
        lines.extend(f"  {line}" for line in bad)
    return lines
