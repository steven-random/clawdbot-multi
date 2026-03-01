"""
shared/capabilities/base.py
───────────────────────────
Base class for all ClawdBot capabilities (tools, databases, APIs, etc.).

Each capability file must:
  1. Define a class that inherits from Capability
  2. Set the NAME and DEFINITION class attributes
  3. Implement the run() method
  4. Optionally override setup() / teardown() for resource lifecycle

See minneru.py and database.py for examples.
"""

from abc import ABC, abstractmethod


class Capability(ABC):
    # Unique identifier used in AGENT_CAPABILITIES env var (e.g. "minneru")
    NAME: str

    # Anthropic-format tool definition returned to Claude
    DEFINITION: dict

    async def setup(self) -> None:
        """Called once at agent startup. Override to open connections, load models, etc."""

    async def teardown(self) -> None:
        """Called on agent shutdown. Override to close connections, release resources."""

    @abstractmethod
    async def run(self, input_: dict) -> str:
        """Execute the capability and return a string result for Claude."""
