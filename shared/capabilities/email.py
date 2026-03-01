"""
shared/capabilities/email.py
─────────────────────────────
Capability: Yahoo Mail (IMAP/SMTP) — read, search, send, and manage emails.

Required environment variables:
  EMAIL_ADDRESS      - Yahoo email address (e.g. yourname@yahoo.com)
  EMAIL_APP_PASSWORD - Yahoo App Password (not your login password)
  IMAP_HOST          - IMAP server (default: imap.mail.yahoo.com)
  IMAP_PORT          - IMAP port   (default: 993)
  SMTP_HOST          - SMTP server (default: smtp.mail.yahoo.com)
  SMTP_PORT          - SMTP port   (default: 587)

How to generate a Yahoo App Password:
  Yahoo Account → Security → Generate app password → Select "Other app"
"""

import asyncio
import email as email_lib
import email.policy
import logging
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import aioimaplib
import aiosmtplib

from capabilities.base import Capability

log = logging.getLogger(__name__)

_DEFAULT_IMAP_HOST = "imap.mail.yahoo.com"
_DEFAULT_IMAP_PORT = 993
_DEFAULT_SMTP_HOST = "smtp.mail.yahoo.com"
_DEFAULT_SMTP_PORT = 587


class EmailCapability(Capability):
    NAME = "email"

    # This capability exposes multiple tools (DEFINITIONS instead of DEFINITION)
    DEFINITIONS = [
        {
            "name": "email_list",
            "description": "List recent emails from a mailbox folder.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "folder": {
                        "type": "string",
                        "description": "Folder to list (e.g. 'INBOX', 'Sent'). Default: INBOX",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of emails to return. Default: 10",
                    },
                },
                "required": [],
            },
        },
        {
            "name": "email_search",
            "description": (
                "Search emails by keyword, sender, or subject. "
                "Query supports IMAP-style syntax: 'from:sender@example.com', "
                "'subject:invoice', or a plain keyword to search the full text."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query, e.g. 'from:boss@company.com', 'subject:meeting', or 'invoice'",
                    },
                    "folder": {
                        "type": "string",
                        "description": "Folder to search in. Default: INBOX",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum results. Default: 10",
                    },
                },
                "required": ["query"],
            },
        },
        {
            "name": "email_send",
            "description": "Send a new email or reply to an existing one.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "to": {
                        "type": "string",
                        "description": "Recipient email address",
                    },
                    "subject": {
                        "type": "string",
                        "description": "Email subject line",
                    },
                    "body": {
                        "type": "string",
                        "description": "Email body (plain text)",
                    },
                    "reply_to_uid": {
                        "type": "string",
                        "description": "UID of the email to reply to (optional). Fetches original for In-Reply-To header.",
                    },
                },
                "required": ["to", "subject", "body"],
            },
        },
        {
            "name": "email_manage",
            "description": "Manage an email: mark as read/unread, move to a folder, or delete.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "uid": {
                        "type": "string",
                        "description": "Email UID (from email_list or email_search results)",
                    },
                    "action": {
                        "type": "string",
                        "enum": ["mark_read", "mark_unread", "move", "delete"],
                        "description": "Action to perform on the email",
                    },
                    "folder": {
                        "type": "string",
                        "description": "Target folder name (required for 'move' action)",
                    },
                },
                "required": ["uid", "action"],
            },
        },
    ]

    def __init__(self):
        self._imap: aioimaplib.IMAP4_SSL | None = None
        self._address = os.environ.get("EMAIL_ADDRESS", "")
        self._password = os.environ.get("EMAIL_APP_PASSWORD", "")
        self._imap_host = os.environ.get("IMAP_HOST", _DEFAULT_IMAP_HOST)
        self._imap_port = int(os.environ.get("IMAP_PORT", _DEFAULT_IMAP_PORT))
        self._smtp_host = os.environ.get("SMTP_HOST", _DEFAULT_SMTP_HOST)
        self._smtp_port = int(os.environ.get("SMTP_PORT", _DEFAULT_SMTP_PORT))

    async def setup(self) -> None:
        if not self._address or not self._password:
            log.warning("EMAIL_ADDRESS or EMAIL_APP_PASSWORD not set — email capability disabled")
            return
        try:
            self._imap = aioimaplib.IMAP4_SSL(host=self._imap_host, port=self._imap_port)
            await self._imap.wait_hello_from_server()
            await self._imap.login(self._address, self._password)
            log.info(f"Email capability connected as {self._address}")
        except Exception as e:
            log.error(f"Failed to connect to IMAP: {e}")
            self._imap = None

    async def teardown(self) -> None:
        if self._imap:
            try:
                await self._imap.logout()
            except Exception:
                pass
            self._imap = None

    async def run(self, input_: dict) -> str:
        tool = input_.get("_tool", "")
        if not self._imap:
            return "Error: email not connected. Check EMAIL_ADDRESS and EMAIL_APP_PASSWORD."

        if tool == "email_list":
            return await self._list(
                folder=input_.get("folder", "INBOX"),
                limit=int(input_.get("limit", 10)),
            )
        if tool == "email_search":
            return await self._search(
                query=input_["query"],
                folder=input_.get("folder", "INBOX"),
                limit=int(input_.get("limit", 10)),
            )
        if tool == "email_send":
            return await self._send(
                to=input_["to"],
                subject=input_["subject"],
                body=input_["body"],
                reply_to_uid=input_.get("reply_to_uid"),
            )
        if tool == "email_manage":
            return await self._manage(
                uid=input_["uid"],
                action=input_["action"],
                folder=input_.get("folder"),
            )
        return f"Unknown email tool: {tool}"

    # ── IMAP helpers ─────────────────────────────────────────

    async def _select(self, folder: str) -> bool:
        """SELECT a folder; returns True on success."""
        resp = await self._imap.select(folder)
        return resp.result == "OK"

    async def _fetch_summaries(self, uids: list[str], limit: int) -> str:
        """Fetch From/Subject/Date for a list of UIDs and format as text."""
        uids = uids[-limit:]  # most recent
        if not uids:
            return "No emails found."

        lines = []
        for uid in reversed(uids):
            try:
                resp = await self._imap.uid("fetch", uid, "(BODY[HEADER.FIELDS (FROM SUBJECT DATE)])")
                if resp.result != "OK":
                    continue
                raw = b"\r\n".join(
                    line for line in resp.lines if isinstance(line, bytes) and not line.startswith(b"*")
                )
                msg = email_lib.message_from_bytes(raw, policy=email_lib.policy.default)
                lines.append(
                    f"UID {uid} | {msg.get('Date', '?')}\n"
                    f"  From: {msg.get('From', '?')}\n"
                    f"  Subject: {msg.get('Subject', '(no subject)')}"
                )
            except Exception as e:
                lines.append(f"UID {uid} | (error fetching: {e})")
        return "\n\n".join(lines) if lines else "No emails."

    async def _list(self, folder: str, limit: int) -> str:
        if not await self._select(folder):
            return f"Cannot open folder '{folder}'."
        resp = await self._imap.uid("search", None, "ALL")
        if resp.result != "OK":
            return "Search failed."
        uids = [u.decode() for u in resp.lines[0].split() if u]
        return await self._fetch_summaries(uids, limit)

    async def _search(self, query: str, folder: str, limit: int) -> str:
        if not await self._select(folder):
            return f"Cannot open folder '{folder}'."

        # Build IMAP search criteria from query string
        q = query.strip()
        if q.lower().startswith("from:"):
            criteria = f'FROM "{q[5:].strip()}"'
        elif q.lower().startswith("subject:"):
            criteria = f'SUBJECT "{q[8:].strip()}"'
        else:
            criteria = f'TEXT "{q}"'

        resp = await self._imap.uid("search", None, criteria)
        if resp.result != "OK":
            return "Search failed."
        uids = [u.decode() for u in resp.lines[0].split() if u]
        return await self._fetch_summaries(uids, limit)

    async def _send(self, to: str, subject: str, body: str, reply_to_uid: str | None) -> str:
        msg = MIMEMultipart()
        msg["From"] = self._address
        msg["To"] = to
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain", "utf-8"))

        # Add In-Reply-To / References if replying
        if reply_to_uid:
            try:
                if not await self._select("INBOX"):
                    return "Cannot open INBOX to fetch reply headers."
                resp = await self._imap.uid("fetch", reply_to_uid, "(BODY[HEADER.FIELDS (MESSAGE-ID SUBJECT)])")
                if resp.result == "OK":
                    raw = b"\r\n".join(
                        line for line in resp.lines if isinstance(line, bytes) and not line.startswith(b"*")
                    )
                    orig = email_lib.message_from_bytes(raw, policy=email_lib.policy.default)
                    if mid := orig.get("Message-ID"):
                        msg["In-Reply-To"] = mid
                        msg["References"] = mid
                    if not subject.lower().startswith("re:"):
                        msg.replace_header("Subject", "Re: " + orig.get("Subject", subject))
            except Exception as e:
                log.warning(f"Could not fetch reply headers: {e}")

        try:
            await aiosmtplib.send(
                msg,
                hostname=self._smtp_host,
                port=self._smtp_port,
                username=self._address,
                password=self._password,
                start_tls=True,
            )
            return f"Email sent to {to}."
        except Exception as e:
            return f"Failed to send email: {e}"

    async def _manage(self, uid: str, action: str, folder: str | None) -> str:
        if not await self._select("INBOX"):
            return "Cannot open INBOX."

        if action == "mark_read":
            resp = await self._imap.uid("store", uid, "+FLAGS", r"(\Seen)")
            return "Marked as read." if resp.result == "OK" else f"Failed: {resp.lines}"

        if action == "mark_unread":
            resp = await self._imap.uid("store", uid, "-FLAGS", r"(\Seen)")
            return "Marked as unread." if resp.result == "OK" else f"Failed: {resp.lines}"

        if action == "delete":
            resp = await self._imap.uid("store", uid, "+FLAGS", r"(\Deleted)")
            if resp.result == "OK":
                await self._imap.expunge()
                return "Email deleted."
            return f"Failed: {resp.lines}"

        if action == "move":
            if not folder:
                return "Error: 'folder' is required for the move action."
            resp = await self._imap.uid("move", uid, folder)
            if resp.result == "OK":
                return f"Moved to '{folder}'."
            # Fallback: COPY + DELETE if MOVE not supported
            resp = await self._imap.uid("copy", uid, folder)
            if resp.result != "OK":
                return f"Failed to copy: {resp.lines}"
            await self._imap.uid("store", uid, "+FLAGS", r"(\Deleted)")
            await self._imap.expunge()
            return f"Moved to '{folder}'."

        return f"Unknown action: {action}"
