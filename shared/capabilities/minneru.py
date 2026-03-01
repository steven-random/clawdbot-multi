"""
shared/capabilities/minneru.py
───────────────────────────────
Capability: PDF → Markdown conversion via the minneru RunPod Serverless endpoint.

Required environment variables:
  RUNPOD_API_KEY       - RunPod API key
  MINNERU_ENDPOINT_ID  - RunPod endpoint ID for the deployed minneru service
"""

import asyncio
import base64
import os
import logging

import httpx

from capabilities.base import Capability

log = logging.getLogger(__name__)

_RUNPOD_BASE = "https://api.runpod.ai/v2"
_POLL_INTERVAL = 3    # seconds between status polls
_TIMEOUT = 300        # max seconds to wait for job completion


class MinneruCapability(Capability):
    NAME = "minneru"

    DEFINITION = {
        "name": "pdf_to_markdown",
        "description": (
            "Convert a PDF document to Markdown text using the minneru service. "
            "Provide either a publicly accessible URL to the PDF or the raw base64-encoded content."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "pdf_url": {
                    "type": "string",
                    "description": "Publicly accessible URL of the PDF to convert.",
                },
                "pdf_base64": {
                    "type": "string",
                    "description": "Base64-encoded content of the PDF file.",
                },
            },
            "required": [],
        },
    }

    async def run(self, input_: dict) -> str:
        api_key = os.environ.get("RUNPOD_API_KEY", "")
        endpoint_id = os.environ.get("MINNERU_ENDPOINT_ID", "")

        if not api_key or not endpoint_id:
            return "Error: RUNPOD_API_KEY or MINNERU_ENDPOINT_ID not configured."

        pdf_base64 = input_.get("pdf_base64")
        pdf_url = input_.get("pdf_url")

        if not pdf_base64 and not pdf_url:
            return "Error: provide either pdf_url or pdf_base64."

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=30) as client:
            # Download PDF from URL if needed
            if not pdf_base64:
                log.info(f"Downloading PDF from {pdf_url}")
                try:
                    resp = await client.get(pdf_url)
                    resp.raise_for_status()
                    pdf_base64 = base64.b64encode(resp.content).decode()
                except Exception as e:
                    return f"Error downloading PDF: {e}"

            # Submit job
            log.info("Submitting job to minneru endpoint")
            try:
                resp = await client.post(
                    f"{_RUNPOD_BASE}/{endpoint_id}/run",
                    headers=headers,
                    json={"input": {"pdf_base64": pdf_base64}},
                )
                resp.raise_for_status()
                job_id = resp.json()["id"]
                log.info(f"Job submitted: {job_id}")
            except Exception as e:
                return f"Error submitting job to minneru: {e}"

        # Poll for completion (use a fresh client for polling)
        elapsed = 0
        async with httpx.AsyncClient(timeout=15) as client:
            while elapsed < _TIMEOUT:
                await asyncio.sleep(_POLL_INTERVAL)
                elapsed += _POLL_INTERVAL
                try:
                    resp = await client.get(
                        f"{_RUNPOD_BASE}/{endpoint_id}/status/{job_id}",
                        headers=headers,
                    )
                    data = resp.json()
                    status = data.get("status")
                    log.info(f"Job {job_id} status: {status} ({elapsed}s)")

                    if status == "COMPLETED":
                        output = data.get("output", {})
                        if "error" in output:
                            return f"minneru error: {output['error']}"
                        return output.get("markdown", "(no markdown returned)")

                    if status in ("FAILED", "CANCELLED"):
                        return f"Job {status}: {data.get('error', 'unknown error')}"

                except Exception as e:
                    log.warning(f"Poll error: {e}")

        return f"Timed out waiting for minneru job {job_id} after {_TIMEOUT}s."
