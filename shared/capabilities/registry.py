"""
shared/capabilities/registry.py
────────────────────────────────
Central registry of all available capabilities.

To add a new capability:
  1. Create shared/capabilities/yourname.py (inherit from Capability)
  2. Import it here and add one line to REGISTRY
  3. Set AGENT_CAPABILITIES=yourname in docker-compose.yml for the agents that should use it
"""

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from capabilities.base import Capability

from capabilities.database import DatabaseCapability
from capabilities.minneru import MinneruCapability

log = logging.getLogger(__name__)

# ── Add new capabilities here ──────────────────────────────────────────────
REGISTRY: dict[str, type["Capability"]] = {
    MinneruCapability.NAME:  MinneruCapability,
    DatabaseCapability.NAME: DatabaseCapability,
}
# ──────────────────────────────────────────────────────────────────────────


def load(names: list[str]) -> list["Capability"]:
    """
    Instantiate capabilities by name.

    Args:
        names: list of capability names (from AGENT_CAPABILITIES env var split by comma)

    Returns:
        list of instantiated Capability objects, skipping unknown names with a warning
    """
    capabilities = []
    for name in names:
        name = name.strip()
        if not name:
            continue
        if name not in REGISTRY:
            log.warning(f"Unknown capability '{name}' — skipping (check AGENT_CAPABILITIES and registry.py)")
            continue
        capabilities.append(REGISTRY[name]())
        log.info(f"Loaded capability: {name}")
    return capabilities
