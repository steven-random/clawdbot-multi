"""
shared/capabilities/registry.py
────────────────────────────────
Central registry of all available capabilities.

To add a new capability:
  1. Create shared/capabilities/yourname.py (inherit from Capability)
  2. Add one line to REGISTRY below (module path + class name as a string)
  3. Set AGENT_CAPABILITIES=yourname in docker-compose.yml for the agents that should use it

Imports are lazy: a capability module is only imported when an agent actually
requests it via AGENT_CAPABILITIES. This means agents won't crash if a
capability's dependencies aren't installed in their image.
"""

import importlib
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from capabilities.base import Capability

log = logging.getLogger(__name__)

# ── Add new capabilities here ──────────────────────────────────────────────
# Format: "capability_name": "module_path.ClassName"
REGISTRY: dict[str, str] = {
    "email":    "capabilities.email.EmailCapability",
    "minneru":  "capabilities.minneru.MinneruCapability",
    "database": "capabilities.database.DatabaseCapability",
}
# ──────────────────────────────────────────────────────────────────────────


def load(names: list[str]) -> list["Capability"]:
    """
    Instantiate capabilities by name (lazy import).

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
        module_path, class_name = REGISTRY[name].rsplit(".", 1)
        try:
            module = importlib.import_module(module_path)
            cls = getattr(module, class_name)
        except (ImportError, AttributeError) as e:
            log.error(f"Failed to load capability '{name}': {e}")
            continue
        capabilities.append(cls())
        log.info(f"Loaded capability: {name}")
    return capabilities
