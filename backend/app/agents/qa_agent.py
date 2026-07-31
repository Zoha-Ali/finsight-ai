import json
import os
from datetime import date

import httpx
from dotenv import load_dotenv

from ..mcp_server import get_anomalies, get_budget, get_monthly_summary, get_transactions

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
MODEL = "claude-haiku-4-5"

MAX_TOOL_CALLS = 4

TOOLS = [
    {
        "name": "get_transactions",
        "description": (
            "Return the user's most recent transactions, newest first. Use "
            "this to see what the user has spent money on recently or to "
            "pull raw transaction data."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Max number of transactions to return.",
                    "default": 50,
                },
            },
        },
    },
    {
        "name": "get_monthly_summary",
        "description": (
            "Return the user's total spending grouped by category for a "
            "given month and year. Use this to answer questions about how "
            "much was spent overall or per category in a specific month."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "month": {"type": "integer", "description": "Month number, 1-12."},
                "year": {"type": "integer", "description": "Four-digit year."},
            },
            "required": ["month", "year"],
        },
    },
    {
        "name": "get_budget",
        "description": (
            "Return the user's monthly budget limit for a specific category, "
            "given its numeric category_id (e.g. from a transaction's "
            "category_id). Returns null if no budget is set for that "
            "category."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "category_id": {"type": "integer", "description": "Numeric ID of the category."},
            },
            "required": ["category_id"],
        },
    },
    {
        "name": "get_anomalies",
        "description": (
            "Return the user's most recently flagged anomalous transactions, "
            "each with the reason it was flagged. Use this to answer "
            "questions about unusual or suspicious spending."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Max number of anomalies to return.",
                    "default": 20,
                },
            },
        },
    },
]

TOOL_FUNCTIONS = {
    "get_transactions": get_transactions,
    "get_monthly_summary": get_monthly_summary,
    "get_budget": get_budget,
    "get_anomalies": get_anomalies,
}


def _system_prompt() -> str:
    return (
        "You are FinSight AI's Q&A assistant. Answer the user's question "
        "about their personal finances using ONLY the data returned by the "
        "tools available to you. Never invent, estimate, or guess a number "
        "- if the tools don't give you enough to answer precisely, say so "
        "instead of making something up. Call as few tools as necessary to "
        "answer the question, then give a clear, concise natural-language "
        f"answer. Today's date is {date.today().isoformat()}."
    )


def _extract_text(content: list[dict]) -> str:
    return "".join(block["text"] for block in content if block.get("type") == "text").strip()


async def _call_model(messages: list[dict], allow_tools: bool) -> dict:
    if not ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY is not set in the environment")

    payload = {
        "model": MODEL,
        "max_tokens": 1024,
        "system": _system_prompt(),
        "messages": messages,
    }
    if allow_tools:
        payload["tools"] = TOOLS

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            ANTHROPIC_API_URL,
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": ANTHROPIC_VERSION,
                "content-type": "application/json",
            },
            json=payload,
        )
        response.raise_for_status()
        return response.json()


async def _run_tool(name: str, tool_input: dict, owner_id: int) -> dict:
    tool_fn = TOOL_FUNCTIONS.get(name)
    if tool_fn is None:
        raise ValueError(f"Unknown tool: {name}")
    return await tool_fn(owner_id=owner_id, **tool_input)


async def answer_question(question: str, owner_id: int) -> dict:
    """Answer a natural-language question about a user's finances.

    Runs a ReAct-style loop: the model picks from the MCP tools
    (get_transactions, get_monthly_summary, get_budget, get_anomalies), the
    real tool functions are executed server-side scoped to owner_id (the
    model never sees or controls owner_id, so it can't be redirected to
    another user's data), and results are fed back to the model until it
    gives a final answer or the tool-call cap is reached.
    """
    messages: list[dict] = [{"role": "user", "content": question}]
    tools_used: list[str] = []

    while len(tools_used) < MAX_TOOL_CALLS:
        response = await _call_model(messages, allow_tools=True)
        content = response["content"]
        messages.append({"role": "assistant", "content": content})

        if response.get("stop_reason") != "tool_use":
            return {"answer": _extract_text(content), "tools_used": tools_used}

        tool_results = []
        for block in content:
            if block.get("type") != "tool_use":
                continue

            tool_name = block["name"]
            tools_used.append(tool_name)

            try:
                result = await _run_tool(tool_name, block.get("input", {}), owner_id)
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block["id"],
                        "content": json.dumps(result),
                    }
                )
            except Exception as exc:
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block["id"],
                        "content": str(exc),
                        "is_error": True,
                    }
                )

        if not tool_results:
            return {
                "answer": _extract_text(content) or "I wasn't able to determine an answer.",
                "tools_used": tools_used,
            }

        messages.append({"role": "user", "content": tool_results})

    # Tool-call cap reached and the model still wanted another tool call;
    # force a final text-only answer from whatever's been gathered so far.
    final_response = await _call_model(messages, allow_tools=False)
    return {"answer": _extract_text(final_response["content"]), "tools_used": tools_used}
