import json
import os

import httpx
from dotenv import load_dotenv

from .categorization_agent import categorize_transaction
from .forecasting_agent import generate_forecast
from .qa_agent import answer_question
from .tracing import save_trace

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
MODEL = "claude-haiku-4-5"

CLASSIFIER_SYSTEM_PROMPT = (
    "You classify a user's request to FinSight AI's personal finance "
    "assistant into exactly one intent, and extract a transaction_id if "
    "one is mentioned.\n\n"
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
    "Respond with ONLY a single raw JSON object - no markdown, no "
    "commentary - matching exactly this schema:\n"
    '{"intent": "categorize" | "forecast" | "qa" | "receipt", '
    '"transaction_id": integer or null}\n\n'
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
    """Classify a request into an intent (+ transaction_id if relevant).

    Falls back to a safe "qa" classification if the model's response isn't
    parseable JSON, rather than failing the whole request over a
    malformed classification.
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
        return {"intent": "qa", "transaction_id": None}

    intent = parsed.get("intent")
    if intent not in ("categorize", "forecast", "qa", "receipt"):
        intent = "qa"

    return {"intent": intent, "transaction_id": parsed.get("transaction_id")}


async def route_request(request: str, owner_id: int) -> dict:
    """Classify a user's request and dispatch it to the right worker agent.

    Builds a trace log of every agent invocation (what it was called with
    and what it returned) alongside the final result, so the full
    supervisor -> worker flow can be inspected after the fact, and
    persists that trace as a Trace row before returning. When agent_used
    is "qa", qa_agent's optional tabular data is lifted to a top-level
    "table" field; it's null for every other intent.
    """
    trace: list[dict] = []

    classification = await _classify(request)
    trace.append(
        {
            "agent": "supervisor_classifier",
            "called_with": {"request": request},
            "returned": classification,
        }
    )

    intent = classification["intent"]

    if intent == "qa":
        agent_used = "qa"
        result = await answer_question(request, owner_id)
        trace.append(
            {
                "agent": "qa_agent",
                "called_with": {"question": request, "owner_id": owner_id},
                "returned": result,
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
                }
            )
        else:
            result = await categorize_transaction(int(transaction_id), owner_id)
            trace.append(
                {
                    "agent": "categorization_agent",
                    "called_with": {"transaction_id": transaction_id, "owner_id": owner_id},
                    "returned": result,
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
        trace.append({"agent": "supervisor", "called_with": {"intent": "receipt"}, "returned": result})

    await save_trace(owner_id, request, agent_used, trace)

    table = result.get("table") if agent_used == "qa" else None

    return {"agent_used": agent_used, "result": result, "trace": trace, "table": table}
