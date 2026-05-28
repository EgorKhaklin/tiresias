"""Central configuration, read from the environment with sane defaults.

Everything is overridable so the same code runs as a local dev server, a
self-hosted container, or a hosted SaaS.
"""

from __future__ import annotations

import logging
import os

# Where the Glass proving engine lives (read-only).
GLASS_DIR = os.environ.get("GPI_GLASS_DIR", os.path.expanduser("~/Desktop/Glass"))

# Registry server.
REGISTRY_HOST = os.environ.get("GPI_HOST", "127.0.0.1")
REGISTRY_PORT = int(os.environ.get("GPI_PORT", "8765"))
DB_PATH = os.environ.get("GPI_DB", os.path.expanduser("~/.gpi/registry.db"))

# Public Fiat-Shamir point used for commitments. A deployment may rotate this,
# but it must be stable for a given dataset's lifetime.
GAMMA = int(os.environ.get("GPI_GAMMA", "918273645"))

# Admin bearer token for provisioning orgs + keys over the API. Empty by default,
# which DISABLES the admin API (provision via the CLI on the box instead). Set
# GPI_ADMIN_TOKEN to a strong secret to enable programmatic tenant onboarding.
ADMIN_TOKEN = os.environ.get("GPI_ADMIN_TOKEN", "")

# Reject request bodies larger than this (manifests/bundles are small).
MAX_BODY_BYTES = int(os.environ.get("GPI_MAX_BODY_BYTES", str(2 * 1024 * 1024)))

# Per-API-key rate limit (requests/minute). 0 disables limiting.
RATE_PER_MIN = int(os.environ.get("GPI_RATE_PER_MIN", "240"))

# Default / max page size for list endpoints.
PAGE_SIZE = int(os.environ.get("GPI_PAGE_SIZE", "50"))
MAX_PAGE_SIZE = int(os.environ.get("GPI_MAX_PAGE_SIZE", "500"))

# Client defaults.
REGISTRY_URL = os.environ.get("GPI_REGISTRY_URL", f"http://{REGISTRY_HOST}:{REGISTRY_PORT}")
API_KEY = os.environ.get("GPI_API_KEY", "")

_LEVEL = os.environ.get("GPI_LOG_LEVEL", "INFO").upper()


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
