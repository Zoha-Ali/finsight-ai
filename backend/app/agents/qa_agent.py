import asyncio
import json
import os
import time
from datetime import date

import httpx
from dotenv import load_dotenv

from ..groq_client import GROQ_MODEL, call_groq, is_groq_model
from ..mcp_server import get_anomalies, get_budget, get_monthly_summary, get_transactions

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
MODEL = "claude-haiku-4-5"
SONNET_MODEL = "claude-sonnet-5"

# Models available for the side-by-side comparison feature - both run the
# identical tool-use loop against the same real data, so any difference in
# the answers reflects the model itself, not the pipeline. Matches the
# actual automatic routing split in supervisor_agent.py (Groq/Llama for
# simple requests, Sonnet for complex ones), rather than an unrelated pair.
COMPARISON_MODELS = {"sonnet": SONNET_MODEL, "groq": GROQ_MODEL}

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

# Groq's chat completions API is OpenAI-compatible, which uses a
# differently-shaped tool schema than Anthropic's Messages API
# ({"type": "function", "function": {...}} vs {"name", "description",
# "input_schema"}) - derived from TOOLS above rather than duplicated, so
# the two tool lists can't drift out of sync.
GROQ_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": tool["name"],
            "description": tool["description"],
            "parameters": tool["input_schema"],
        },
    }
    for tool in TOOLS
]


def _system_prompt() -> str:
    return (
        "You are FinSight AI's Q&A assistant. Answer the user's question "
        "about their personal finances using ONLY the data returned by the "
        "tools available to you. Never invent, estimate, or guess a number "
        "- if the tools don't give you enough to answer precisely, say so "
        "instead of making something up. Call as few tools as necessary to "
        "answer the question.\n\n"
        "get_transactions returns results ordered NEWEST FIRST - the first "
        "item in the list is the most recent transaction, not the oldest. "
        "When asked for the oldest, earliest, or first transaction, never "
        "assume the answer is the first or last item in the list based on "
        "its position - explicitly compare every date in the results and "
        "pick the one with the minimum (earliest) date. The same applies "
        "in reverse for the newest, latest, or most recent transaction - "
        "explicitly find the maximum (latest) date rather than guessing "
        "from position.\n\n"
        "Once you have everything you need and are ready to give your "
        "final answer (i.e. you are not calling another tool), respond "
        "with ONLY a single raw JSON object - no markdown code fences, no "
        "commentary - matching exactly this schema:\n"
        '{"answer": string, "table": array of objects, or null}\n\n'
        'Populate "table" when the data naturally forms a list of similar '
        "rows - multiple transactions, a spending-by-category breakdown, a "
        "list of anomalies, etc. Every object in the array should share "
        "the same keys, named after the actual data (e.g. merchant, "
        'amount, date, category). Leave "table" null for a single-value '
        "answer (a total, a yes/no, a single number) where there's no "
        'natural list of rows. "answer" should always be a clear, concise '
        "natural-language summary regardless of whether table is "
        "populated. All monetary amounts are in Pakistani Rupees - format "
        'them as "Rs. " followed by the number (e.g. "Rs. 1500.00"), never '
        f'"$". Today\'s date is {date.today().isoformat()}.'
    )


def _extract_text(content: list[dict]) -> str:
    return "".join(block["text"] for block in content if block.get("type") == "text").strip()


def _strip_code_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        if text.endswith("```"):
            text = text[:-3]
        if text.lower().startswith("json"):
            text = text[4:]
    return text.strip()


def _parse_final_answer(text: str) -> tuple[str, list[dict] | None, bool]:
    """Parse the model's final response as {"answer": str, "table": ...}.

    Returns (answer, table, was_valid) - was_valid is False whenever the
    text isn't valid JSON matching the schema, in which case the whole
    response is returned verbatim as the answer with table=None, so a
    formatting slip degrades to plain-text prose instead of crashing.
    Callers that want the retry-once-on-malformed-output pattern (see
    _finalize_answer) use was_valid to decide whether to ask the model to
    reformat before falling back to this same graceful degradation.
    """
    try:
        parsed = json.loads(_strip_code_fence(text))
    except json.JSONDecodeError:
        return text, None, False

    if not isinstance(parsed, dict) or "answer" not in parsed:
        return text, None, False

    table = parsed.get("table")
    if not isinstance(table, list):
        table = None

    return str(parsed["answer"]), table, True


async def _finalize_answer(messages: list[dict], raw_text: str, call_fn) -> tuple[str, list[dict] | None]:
    """Parse a model's final answer, retrying once via call_fn if it isn't
    valid JSON matching the expected schema - the same retry-once-then-
    fall-back pattern receipt_agent.py uses for its JSON extraction.

    `messages` must already end with the assistant's original final-answer
    turn (appended by the caller, in whichever shape that provider uses -
    Anthropic's content-blocks list vs Groq's message dict) - this only
    appends the corrective user message before retrying, rather than
    re-appending the assistant's turn a second time (which would produce
    two consecutive assistant turns, invalid for a strict user/assistant
    conversation). `call_fn` takes the messages list and returns the
    retried response's raw text; it's provider-specific but the parsing
    and fallback behavior here is shared.
    """
    answer, table, was_valid = _parse_final_answer(raw_text)
    if was_valid:
        return answer, table

    messages.append(
        {
            "role": "user",
            "content": (
                "That was not valid JSON matching the required schema. Respond again with ONLY "
                'the raw JSON object - no markdown, no commentary: {"answer": string, "table": '
                "array of objects, or null}."
            ),
        }
    )
    retry_text = await call_fn(messages)
    answer, table, _ = _parse_final_answer(retry_text)
    return answer, table


async def _call_model(messages: list[dict], allow_tools: bool, model: str = MODEL) -> dict:
    if not ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY is not set in the environment")

    payload = {
        "model": model,
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


async def answer_question(question: str, owner_id: int, model: str = MODEL) -> dict:
    """Answer a natural-language question about a user's finances.

    Runs a ReAct-style loop: the model picks from the MCP tools
    (get_transactions, get_monthly_summary, get_budget, get_anomalies), the
    real tool functions are executed server-side scoped to owner_id (the
    model never sees or controls owner_id, so it can't be redirected to
    another user's data), and results are fed back to the model until it
    gives a final answer or the tool-call cap is reached. The final answer
    includes an optional "table" - populated with rows when the data is
    naturally tabular (e.g. a transaction list or category breakdown),
    left null for single-value answers. `model` defaults to this module's
    standard Anthropic model but can be overridden (see compare_models and
    supervisor_agent's routing) to run the identical loop against a
    different one - Anthropic models go through _answer_question_anthropic,
    the Groq model through _answer_question_groq, since the two providers'
    tool-calling wire formats aren't compatible.
    """
    if is_groq_model(model):
        result = await _answer_question_groq(question, owner_id, model)
    else:
        result = await _answer_question_anthropic(question, owner_id, model)

    # _answer_question_groq sets this itself when it had to fall back to a
    # different model (see there) - setdefault leaves that in place rather
    # than stomping it back to the originally-requested model.
    result.setdefault("model_used", model)
    return result


async def _answer_question_anthropic(question: str, owner_id: int, model: str) -> dict:
    async def call_fn(msgs: list[dict]) -> str:
        response = await _call_model(msgs, allow_tools=False, model=model)
        return _extract_text(response["content"])

    messages: list[dict] = [{"role": "user", "content": question}]
    tools_used: list[str] = []

    while len(tools_used) < MAX_TOOL_CALLS:
        response = await _call_model(messages, allow_tools=True, model=model)
        content = response["content"]
        messages.append({"role": "assistant", "content": content})

        if response.get("stop_reason") != "tool_use":
            answer, table = await _finalize_answer(messages, _extract_text(content), call_fn)
            return {"answer": answer, "tools_used": tools_used, "table": table}

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
                "table": None,
            }

        messages.append({"role": "user", "content": tool_results})

    # Tool-call cap reached and the model still wanted another tool call;
    # force a final answer from whatever's been gathered so far.
    final_response = await _call_model(messages, allow_tools=False, model=model)
    final_content = final_response["content"]
    messages.append({"role": "assistant", "content": final_content})
    answer, table = await _finalize_answer(messages, _extract_text(final_content), call_fn)
    return {"answer": answer, "tools_used": tools_used, "table": table}


async def _call_groq_with_tools_recovering(messages: list[dict], model: str) -> tuple[dict | None, bool]:
    """Call Groq offering tools, retrying once if Groq's API itself
    rejects the tool-call attempt. Returns (response, retried) - response
    is None only if both attempts failed; retried is True if the first
    attempt failed but the second one succeeded.

    Llama on Groq occasionally emits a malformed function-call (e.g. an
    XML-ish <function=...> tag instead of a proper tool_calls entry),
    which Groq's own API rejects outright with a 400 "tool_use_failed"
    before we ever see a response to parse - this is intermittent (roughly
    half the attempts against the same question in testing), so a second
    attempt against the same prompt often just succeeds. The caller
    decides what to do if both attempts fail (rather than this silently
    forcing a no-data answer, which is what used to happen here).
    """
    for attempt in range(2):
        try:
            return await call_groq(messages, model=model, tools=GROQ_TOOLS), attempt == 1
        except httpx.HTTPStatusError:
            continue
    return None, False


async def _answer_question_groq(question: str, owner_id: int, model: str) -> dict:
    """Same ReAct loop as _answer_question_anthropic, against Groq's
    OpenAI-compatible chat completions API instead - tool calls arrive as
    message.tool_calls (JSON-string arguments) rather than Anthropic's
    typed content blocks, and results are sent back as role="tool"
    messages instead of a tool_result content block, but the underlying
    tools, prompt, and final-answer parsing are identical.

    If Groq's own API rejects the tool-call attempt twice in a row (see
    _call_groq_with_tools_recovering), this falls back to a fresh request
    to Sonnet (with tools) rather than forcing Llama to answer with zero
    data - which technically "degrades gracefully" but produces an
    honest-but-useless "I don't have enough information" answer instead
    of the real, data-grounded one Sonnet can actually get. The result
    carries "model_used" and "recovery_path" so callers (route_request's
    trace, compare_models) can tell what actually happened rather than
    assuming the originally-requested model answered.
    """
    async def call_fn(msgs: list[dict]) -> str:
        response = await call_groq(msgs, model=model)
        return response["choices"][0]["message"].get("content") or ""

    messages: list[dict] = [
        {"role": "system", "content": _system_prompt()},
        {"role": "user", "content": question},
    ]
    tools_used: list[str] = []
    recovery_path: str | None = None

    while len(tools_used) < MAX_TOOL_CALLS:
        response, retried = await _call_groq_with_tools_recovering(messages, model)
        if response is None:
            # Both the original attempt and the retry failed to produce a
            # usable tool call - fall back to Sonnet with tools instead of
            # asking Llama a second time with nothing to go on.
            result = await _answer_question_anthropic(question, owner_id, SONNET_MODEL)
            result["model_used"] = SONNET_MODEL
            result["recovery_path"] = "sonnet_fallback"
            return result
        if retried:
            recovery_path = "groq_retry"

        message = response["choices"][0]["message"]
        messages.append(message)

        tool_calls = message.get("tool_calls")
        if not tool_calls:
            answer, table = await _finalize_answer(messages, message.get("content") or "", call_fn)
            return {"answer": answer, "tools_used": tools_used, "table": table, "recovery_path": recovery_path}

        for call in tool_calls:
            tool_name = call["function"]["name"]
            tools_used.append(tool_name)

            try:
                tool_input = json.loads(call["function"]["arguments"] or "{}")
                result = await _run_tool(tool_name, tool_input, owner_id)
                content = json.dumps(result)
            except Exception as exc:
                content = json.dumps({"error": str(exc)})

            messages.append({"role": "tool", "tool_call_id": call["id"], "content": content})

    # Tool-call cap reached and the model still wanted another tool call;
    # force a final answer from whatever's been gathered so far.
    final_response = await call_groq(messages, model=model)
    final_message = final_response["choices"][0]["message"]
    messages.append(final_message)
    answer, table = await _finalize_answer(messages, final_message.get("content") or "", call_fn)
    return {"answer": answer, "tools_used": tools_used, "table": table, "recovery_path": recovery_path}


async def _timed_answer(question: str, owner_id: int, model: str) -> dict:
    start = time.perf_counter()
    result = await answer_question(question, owner_id, model=model)
    elapsed = time.perf_counter() - start
    # result["model_used"] reflects what actually answered - if the Groq
    # side had to fall back to Sonnet, this must say so rather than
    # mislabeling a Sonnet answer as the originally-requested Groq model.
    return {**result, "model": result.get("model_used", model), "elapsed_seconds": round(elapsed, 2)}


async def compare_models(question: str, owner_id: int) -> dict:
    """Answer the same question with claude-sonnet-5 and Llama-via-Groq.

    Runs the identical tool-use loop from answer_question() against each
    model concurrently, both scoped to the same owner_id and hitting the
    same real data - so any difference between the two answers reflects
    the model itself, not the pipeline or the data available to it. Uses
    the same two models the Supervisor's automatic complexity routing
    chooses between (see supervisor_agent.py), so this mode doubles as a
    manual "what would each path have answered" comparison.
    """
    sonnet_result, groq_result = await asyncio.gather(
        _timed_answer(question, owner_id, COMPARISON_MODELS["sonnet"]),
        _timed_answer(question, owner_id, COMPARISON_MODELS["groq"]),
    )
    return {"sonnet": sonnet_result, "groq": groq_result}
