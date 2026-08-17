import os

import httpx
from dotenv import load_dotenv

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

# The model used for every request routed to Groq - see
# supervisor_agent.py's simple/complex classification, which sends
# "simple" requests here instead of to Anthropic. Was llama-3.3-70b-
# versatile until Groq decommissioned it on 2026-08-16; switched to
# openai/gpt-oss-120b, Groq's recommended replacement (also cheaper:
# $0.15/$0.60 per million tokens vs Llama 3.3 70B's $0.59/$0.79).
# Verified against Groq's live /v1/models endpoint before switching.
GROQ_MODEL = "openai/gpt-oss-120b"


def is_groq_model(model: str) -> bool:
    return model == GROQ_MODEL


async def call_groq(
    messages: list[dict],
    *,
    model: str = GROQ_MODEL,
    tools: list[dict] | None = None,
    max_tokens: int = 1024,
) -> dict:
    """POST to Groq's OpenAI-compatible chat completions endpoint.

    Bypasses any SDK on purpose, mirroring the direct-httpx pattern used
    for Anthropic calls elsewhere in this codebase - one fewer dependency
    to worry about breaking on this project's dev machines.
    """
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY is not set in the environment")

    payload: dict = {"model": model, "messages": messages, "max_tokens": max_tokens}
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            GROQ_API_URL,
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "content-type": "application/json"},
            json=payload,
        )
        response.raise_for_status()
        return response.json()
