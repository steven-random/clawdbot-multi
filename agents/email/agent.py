import os, sys, asyncio
sys.path.insert(0, "/shared")
from base_agent import BaseAgent

SYSTEM_PROMPTS = {
    "email": (
        "You are an AI email assistant with direct access to a Yahoo Mail account via IMAP/SMTP. "
        "Credentials are available as environment variables: "
        "EMAIL_ADDRESS, EMAIL_APP_PASSWORD, IMAP_HOST (imap.mail.yahoo.com), IMAP_PORT (993), "
        "SMTP_HOST (smtp.mail.yahoo.com), SMTP_PORT (587). "
        "When asked to send, read, search, or manage emails, write and EXECUTE Python code using "
        "imaplib/smtplib (or the installed aioimaplib/aiosmtplib packages) to actually complete the task. "
        "Read credentials with os.environ. Always execute the code — never just describe or draft."
    ),
    "stock": "You are a US stock market analyst. Provide detailed analysis.",
}

class Agent(BaseAgent):
    @property
    def system_prompt(self): return ""
    async def get_tools(self): return []
    async def process_task(self, task: dict) -> str:
        text = task["text"]
        agent_id = os.environ["AGENT_ID"]
        role = SYSTEM_PROMPTS.get(agent_id, "You are a helpful assistant.")
        prompt = f"{role} Task: {text}"
        try:
            proc = await asyncio.create_subprocess_exec(
                "codex", "exec",
                "--model", os.environ.get("CODEX_MODEL", "gpt-5-codex"),
                "-s", "danger-full-access",
                "--skip-git-repo-check",
                "--dangerously-bypass-approvals-and-sandbox",
                "--ephemeral",
                prompt,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
            result = stdout.decode().strip()
            err = stderr.decode().strip()
            result = "\n".join(l for l in result.splitlines() if "could not update PATH" not in l)
            if not result:
                return f"No output. stderr: {err[:500]}" if err else "Done"
            return result
        except asyncio.TimeoutError: return "Timed out after 120s"
        except Exception as e: return f"Error: {e}"

if __name__ == "__main__":
    asyncio.run(Agent().run())
