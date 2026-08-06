import json
import os

import httpx
from dotenv import load_dotenv

from ..groq_client import GROQ_MODEL
from .categorization_agent import categorize_transaction
from .forecasting_agent import MODEL as FORECAST_MODEL
from .forecasting_agent import generate_forecast
from .qa_agent import answer_question
from .tracing import save_trace

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
MODEL = "claude-haiku-4-5"

# Multi-model routing: "simple" requests (categorization, straightforward
# single-fact questions) go to Llama-via-Groq for speed/cost; "complex"
# requests (multi-part questions, anything needing nuanced reasoning) go
# to Sonnet for the extra reasoning depth. Forecasting isn't part of this
# routing - it keeps using its own model unchanged (see forecasting_agent).
SIMPLE_MODEL = GROQ_MODEL
COMPLEX_MODEL = "claude-sonnet-5"

CLASSIFIER_SYSTEM_PROMPT = (
    "You classify a user's request to FinSight AI's personal finance "
    "assistant into exactly one intent, extract a transaction_id if one "
    "is mentioned, and rate how complex the request is.\n\n"
    "Intents:\n"
    '- "categorize": the user wants a specific transaction categorized or '
    "re-checked for anomalies.\n"
    '- "forecast": the user wants a projection or forecast of their '
    "spending.\n"
    '- "qa": the user is asking a question about their spending, budget, '
    "transactions, or anomalies.\n"
    '- "receipt": the request is about uploading or processing a receipt '
    "or statement image. Receipt/statement image uploads are handled by a "
    "separate pipeline and never reach you as text, so only use this "
    "intent if the text is unmistakably about that and fits nothing else.\n\n"
    "Complexity (only meaningful when intent is \"qa\" - always use "
    '"simple" for every other intent):\n'
    '- "simple": a single, straightforward factual question answerable by '
    "looking up one piece of data - a total, a single number, a yes/no, a "
    'short list. E.g. "how much did I spend on food this month?", "what '
    'was my last transaction?".\n'
    '- "complex": a multi-part question, or one that requires comparing '
    "or reasoning across several pieces of data rather than a single "
    'lookup. E.g. "compare my spending this month to last month and tell '
    'me what changed", "why am I over budget and what should I cut back '
    'on?".\n\n'
    "Respond with ONLY a single raw JSON object - no markdown, no "
    "commentary - matching exactly this schema:\n"
    '{"intent": "categorize" | "forecast" | "qa" | "receipt", '
    '"transaction_id": integer or null, '
    '"complexity": "simple" | "complex"}\n\n'
    'Only set transaction_id when intent is "categorize" and a specific '
    "numeric transaction ID is mentioned or clearly implied; otherwise use "
    "null."
)


def _strip_code_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        if text.endswith("```"):
            text = text[:-3]
        if text.lower().startswith("json"):
            text = text[4:]
    return text.strip()


async def _classify(request: str) -> dict:
    """Classify a request into an intent, transaction_id, and complexity.

    The complexity rating is produced in this same call rather than a
    separate one - it's the fastest way to get it (no extra round trip)
    and the classifier is already reading the request closely enough to
    judge it. Falls back to safe defaults ("qa" intent, "simple"
    complexity) if the model's response isn't parseable JSON, rather than
    failing the whole request over a malformed classification.
    """
    if not ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY is not set in the environment")

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            ANTHROPIC_API_URL,
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": ANTHROPIC_VERSION,
                "content-type": "application/json",
            },
            json={
                "model": MODEL,
                "max_tokens": 100,
                "system": CLASSIFIER_SYSTEM_PROMPT,
                "messages": [{"role": "user", "content": request}],
            },
        )
        response.raise_for_status()
        data = response.json()

    raw_text = "".join(block["text"] for block in data["content"] if block.get("type") == "text").strip()

    try:
        parsed = json.loads(_strip_code_fence(raw_text))
    except json.JSONDecodeError:
        return {"intent": "qa", "transaction_id": None, "complexity": "simple"}

    intent = parsed.get("intent")
    if intent not in ("categorize", "forecast", "qa", "receipt"):
        intent = "qa"

    complexity = parsed.get("complexity")
    if complexity not in ("simple", "complex"):
        complexity = "simple"

    return {"intent": intent, "transaction_id": parsed.get("transaction_id"), "complexity": complexity}


async def route_request(request: str, owner_id: int) -> dict:
    """Classify a user's request and dispatch it to the right worker agent.

    Builds a trace log of every agent invocation (what it was called with
    and what it returned) alongside the final result, so the full
    supervisor -> worker flow can be inspected after the fact, and
    persists that trace as a Trace row before returning. When agent_used
    is "qa", qa_agent's optional tabular data is lifted to a top-level
    "table" field; it's null for every other intent.

    Multi-model routing: categorize and qa requests are also routed to a
    model based on the classifier's complexity rating - "simple" requests
    (all categorize requests, plus simple qa questions) go to Llama via
    Groq, "complex" qa questions go to Sonnet. Every trace entry records
    which model actually handled that step via "model_used", so the
    routing decision is visible after the fact.
    """
    trace: list[dict] = []

    classification = await _classify(request)
    trace.append(
        {
            "agent": "supervisor_classifier",
            "called_with": {"request": request},
            "returned": classification,
            "model_used": MODEL,
        }
    )

    intent = classification["intent"]
    complexity = classification["complexity"]
    chosen_model = COMPLEX_MODEL if (intent == "qa" and complexity == "complex") else SIMPLE_MODEL

    if intent == "qa":
        agent_used = "qa"
        result = await answer_question(request, owner_id, model=chosen_model)
        trace.append(
            {
                "agent": "qa_agent",
                "called_with": {"question": request, "owner_id": owner_id},
                "returned": result,
                "model_used": chosen_model,
            }
        )

    elif intent == "forecast":
        agent_used = "forecast"
        result = await generate_forecast(owner_id)
        trace.append(
            {
                "agent": "forecasting_agent",
                "called_with": {"owner_id": owner_id},
                "returned": result,
                "model_used": FORECAST_MODEL,
            }
        )

    elif intent == "categorize":
        agent_used = "categorize"
        transaction_id = classification.get("transaction_id")
        if transaction_id is None:
            result = {
                "needs_clarification": True,
                "message": "Which transaction would you like me to categorize? Please include its transaction ID.",
            }
            trace.append(
                {
                    "agent": "supervisor",
                    "called_with": {"intent": "categorize", "transaction_id": None},
                    "returned": result,
                    "model_used": None,
                }
            )
        else:
            result = await categorize_transaction(int(transaction_id), owner_id, model=chosen_model)
            trace.append(
                {
                    "agent": "categorization_agent",
                    "called_with": {"transaction_id": transaction_id, "owner_id": owner_id},
                    "returned": result,
                    "model_used": chosen_model,
                }
            )

    else:
        # intent == "receipt": image uploads never reach this text router
        # in practice, so this is a defensive dead end rather than a real
        # path.
        agent_used = "receipt"
        result = {
            "error": "Receipt and statement uploads are handled directly by receipt_agent.process_receipt, not through text routing.",
        }
        trace.append(
            {"agent": "supervisor", "called_with": {"intent": "receipt"}, "returned": result, "model_used": None}
        )

    await save_trace(owner_id, request, agent_used, trace)

    table = result.get("table") if agent_used == "qa" else None

    return {"agent_used": agent_used, "result": result, "trace": trace, "table": table}
