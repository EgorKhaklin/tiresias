"""Configuration: every TIRESIAS_* setting, declared once.

Each setting is read from the environment and parsed against its declaration.
A malformed value never breaks an import: the default is kept and the problem is
recorded. `tiresias serve` calls `problems()` and refuses to start while any
stands, naming each one. `tiresias config` prints the effective values, and
docs/configuration.md is generated from the same table.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

PREFIX = "TIRESIAS_"

# The commitment field, 2^31 - 1 (tiresias/engine/schema.py FIELD_PRIME; a test
# keeps the two equal without importing the engine here).
_FIELD_PRIME = 2147483647

_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
ADMIN_TOKEN_MIN = 32


@dataclass(frozen=True)
class Setting:
    name: str            # the variable without the TIRESIAS_ prefix
    default: str
    kind: str            # "str", "path", "int", "secret" or "level"
    doc: str
    scope: str           # "registry", "client" or "prover": who reads it
    lo: int | None = None
    hi: int | None = None

    @property
    def env(self) -> str:
        return PREFIX + self.name


SETTINGS: tuple[Setting, ...] = (
    Setting("HOST", "127.0.0.1", "str", "Address the registry binds to.", "registry"),
    Setting("PORT", "8765", "int", "Port the registry listens on.", "registry", 1, 65535),
    Setting("DB", "~/.tiresias/registry.db", "path", "The registry's SQLite database.", "registry"),
    Setting("ADMIN_TOKEN", "", "secret",
            f"Bearer token for the admin API. Empty disables the admin API; when set, at least {ADMIN_TOKEN_MIN} characters.",
            "registry"),
    Setting("MAX_BODY_BYTES", str(2 * 1024 * 1024), "int", "Largest request body the registry accepts.", "registry",
            1024, 64 * 1024 * 1024),
    Setting("RATE_PER_MIN", "240", "int", "Requests per minute per API key; 0 disables limiting.", "registry", 0, 100000),
    Setting("PAGE_SIZE", "50", "int", "Default page size for list endpoints.", "registry", 1, 10000),
    Setting("MAX_PAGE_SIZE", "500", "int", "Largest page size a client may ask for; at least PAGE_SIZE.", "registry",
            1, 10000),
    Setting("LOG_LEVEL", "INFO", "level", "One of DEBUG, INFO, WARNING, ERROR, CRITICAL.", "registry"),
    Setting("GLASS_DIR", "~/Desktop/Glass", "path", "Where the Glass engine lives. Only the local prover reads it.",
            "prover"),
    Setting("GAMMA", "918273645", "int",
            "Public Fiat-Shamir point for dataset commitments. Keep it fixed for a dataset's lifetime.", "prover",
            2, _FIELD_PRIME - 1),
    Setting("REGISTRY_URL", "", "str", "Registry the client talks to. Empty means http://HOST:PORT.", "client"),
    Setting("API_KEY", "", "secret", "The client's API key.", "client"),
)

_BY_NAME = {s.name: s for s in SETTINGS}


def _parse(setting: Setting, raw: str):
    """Parse one raw value. Returns (value, problem or None)."""
    if setting.kind == "int":
        try:
            value = int(raw)
        except ValueError:
            return None, f"{setting.env}: expected an integer, got {raw!r}"
        if (setting.lo is not None and value < setting.lo) or (setting.hi is not None and value > setting.hi):
            return None, f"{setting.env}: {value} is outside {setting.lo} to {setting.hi}"
        return value, None
    if setting.kind == "level":
        value = raw.upper()
        if value not in _LEVELS:
            return None, f"{setting.env}: expected one of {', '.join(_LEVELS)}, got {raw!r}"
        return value, None
    if setting.kind == "path":
        return os.path.expanduser(raw), None
    if setting.kind == "secret" and setting.name == "ADMIN_TOKEN" and raw and len(raw) < ADMIN_TOKEN_MIN:
        return raw, f"{setting.env}: set but only {len(raw)} characters; use at least {ADMIN_TOKEN_MIN} or leave it empty"
    return raw, None


def load(environ=None) -> tuple[dict, list[str]]:
    """Read every setting from `environ` (default os.environ). Returns the values
    by name and the list of problems; a value with a problem falls back to its default."""
    environ = os.environ if environ is None else environ
    values: dict = {}
    found: list[str] = []
    for s in SETTINGS:
        value, problem = _parse(s, environ.get(s.env, s.default))
        if problem is not None:
            found.append(problem)
            if value is None:
                value, _ = _parse(s, s.default)
        values[s.name] = value
    if values["MAX_PAGE_SIZE"] < values["PAGE_SIZE"]:
        found.append(f"{PREFIX}MAX_PAGE_SIZE ({values['MAX_PAGE_SIZE']}) is below {PREFIX}PAGE_SIZE ({values['PAGE_SIZE']})")
    for key in sorted(environ):
        if key.startswith(PREFIX) and key[len(PREFIX):] not in _BY_NAME:
            found.append(f"{key}: not a Tiresias setting (a typo?)")
    if not values["REGISTRY_URL"]:
        values["REGISTRY_URL"] = f"http://{values['HOST']}:{values['PORT']}"
    return values, found


def problems(environ=None, scope: str = "registry") -> list[str]:
    """The problems that matter to one reader: the registry refuses to start on these."""
    _, found = load(environ)
    keep = []
    for p in found:
        name = p.split(":", 1)[0].split(" ", 1)[0]
        setting = _BY_NAME.get(name[len(PREFIX):]) if name.startswith(PREFIX) else None
        if setting is None or setting.scope == scope:
            keep.append(p)
    return keep


def render_markdown() -> str:
    """docs/configuration.md, generated from SETTINGS."""
    lines = [
        "# Configuration",
        "",
        "Every setting is an environment variable. This page is generated from `tiresias/config.py`;",
        "a test fails if the two disagree. `tiresias config` prints the effective values.",
        "`tiresias serve` refuses to start while any registry setting is malformed, out of range,",
        "or unknown, and names each problem.",
        "",
        "| Variable | Read by | Default | Meaning |",
        "|---|---|---|---|",
    ]
    for s in SETTINGS:
        default = f"`{s.default}`" if s.default else "(empty)"
        bounds = f" Range {s.lo} to {s.hi}." if s.kind == "int" and s.lo is not None else ""
        lines.append(f"| `{s.env}` | {s.scope} | {default} | {s.doc}{bounds} |")
    return "\n".join(lines) + "\n"


_VALUES, _ = load()

GLASS_DIR = _VALUES["GLASS_DIR"]
REGISTRY_HOST = _VALUES["HOST"]
REGISTRY_PORT = _VALUES["PORT"]
DB_PATH = _VALUES["DB"]
GAMMA = _VALUES["GAMMA"]
ADMIN_TOKEN = _VALUES["ADMIN_TOKEN"]
MAX_BODY_BYTES = _VALUES["MAX_BODY_BYTES"]
RATE_PER_MIN = _VALUES["RATE_PER_MIN"]
PAGE_SIZE = _VALUES["PAGE_SIZE"]
MAX_PAGE_SIZE = _VALUES["MAX_PAGE_SIZE"]
REGISTRY_URL = _VALUES["REGISTRY_URL"]
API_KEY = _VALUES["API_KEY"]
_LEVEL = _VALUES["LOG_LEVEL"]


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
        logger.addHandler(handler)
        logger.setLevel(getattr(logging, _LEVEL, logging.INFO))
        logger.propagate = False
    return logger
