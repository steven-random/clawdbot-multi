"""
shared/capabilities/database.py
────────────────────────────────
Capability: Read-only SQL query against a remote database.

This is a skeleton / example. Fill in the connection logic for your database.

Required environment variables:
  DATABASE_URL  - SQLAlchemy-style connection string, e.g.
                  postgresql+asyncpg://user:pass@host/dbname
"""

import os
import logging

from capabilities.base import Capability

log = logging.getLogger(__name__)


class DatabaseCapability(Capability):
    NAME = "database"

    DEFINITION = {
        "name": "query_database",
        "description": (
            "Run a read-only SQL query against the remote database and return the results. "
            "Only SELECT statements are allowed."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sql": {
                    "type": "string",
                    "description": "A read-only SQL SELECT statement to execute.",
                },
            },
            "required": ["sql"],
        },
    }

    def __init__(self):
        self._conn = None

    async def setup(self) -> None:
        """Open the database connection at agent startup."""
        url = os.environ.get("DATABASE_URL", "")
        if not url:
            log.warning("DATABASE_URL not set — database capability will return errors")
            return
        # TODO: replace with your preferred async DB driver
        # Example with asyncpg:
        #   import asyncpg
        #   self._conn = await asyncpg.connect(url)
        log.info("Database capability ready (stub — wire up your driver in setup())")

    async def teardown(self) -> None:
        """Close the database connection on agent shutdown."""
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    async def run(self, input_: dict) -> str:
        sql = input_.get("sql", "").strip()

        if not sql.lower().startswith("select"):
            return "Error: only SELECT statements are permitted."

        if self._conn is None:
            return "Error: database not connected. Check DATABASE_URL."

        # TODO: execute query and format results
        # Example with asyncpg:
        #   rows = await self._conn.fetch(sql)
        #   if not rows:
        #       return "No results."
        #   headers = list(rows[0].keys())
        #   lines = [" | ".join(headers)]
        #   lines += [" | ".join(str(v) for v in row.values()) for row in rows]
        #   return "\n".join(lines)

        return "Database capability not fully configured (see database.py TODO comments)."
