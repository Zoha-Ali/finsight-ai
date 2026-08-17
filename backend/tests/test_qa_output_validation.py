from unittest.mock import AsyncMock

import httpx
import pytest

from app.agents import qa_agent


# --- _parse_final_answer: deliberately malformed input, no crash ----------


def test_parse_final_answer_accepts_valid_json():
    answer, table, was_valid = qa_agent._parse_final_answer('{"answer": "hi", "table": null}')
    assert was_valid is True
    assert answer == "hi"
    assert table is None


def test_parse_final_answer_handles_plain_prose_that_is_not_json_at_all():
    answer, table, was_valid = qa_agent._parse_final_answer("Sure! You spent $42 this month.")
    assert was_valid is False
    assert answer == "Sure! You spent $42 this month."  # graceful fallback: whole text as the answer
    assert table is None


def test_parse_final_answer_handles_json_missing_the_answer_key():
    answer, table, was_valid = qa_agent._parse_final_answer('{"foo": "bar"}')
    assert was_valid is False
    assert answer == '{"foo": "bar"}'  # falls back to the raw text, doesn't crash on the missing key


def test_parse_final_answer_handles_a_json_array_instead_of_an_object():
    answer, table, was_valid = qa_agent._parse_final_answer('["not", "an", "object"]')
    assert was_valid is False


def test_parse_final_answer_handles_truncated_json():
    # e.g. a response cut off mid-generation by a token limit
    answer, table, was_valid = qa_agent._parse_final_answer('{"answer": "You spent $42, but')
    assert was_valid is False
    assert "$42" in answer


def test_parse_final_answer_ignores_a_non_list_table_value():
    answer, table, was_valid = qa_agent._parse_final_answer('{"answer": "hi", "table": "not a list"}')
    assert was_valid is True
    assert table is None  # coerced to None rather than passed through malformed


def test_parse_final_answer_handles_prose_plus_a_trailing_json_fence():
    # a real quirk observed from Haiku in practice: prose followed by a
    # fenced JSON blob, instead of ONLY the raw JSON object as instructed
    text = 'Here is what I found:\n\n```json\n{"answer": "You spent $42", "table": null}\n```'
    answer, table, was_valid = qa_agent._parse_final_answer(text)
    assert was_valid is False  # the leading prose means json.loads still fails
    assert answer == text  # falls back to showing the whole thing rather than crashing


# --- _finalize_answer: retry-once-then-fall-back, deliberately malformed --


async def test_finalize_answer_returns_immediately_when_first_attempt_is_valid():
    call_fn = AsyncMock()
    messages: list[dict] = []

    answer, table = await qa_agent._finalize_answer(messages, '{"answer": "42", "table": null}', call_fn)

    assert answer == "42"
    call_fn.assert_not_awaited()  # no retry needed
    assert messages == []  # nothing appended when no retry happens


async def test_finalize_answer_retries_once_and_uses_the_corrected_json():
    call_fn = AsyncMock(return_value='{"answer": "corrected answer", "table": null}')
    messages: list[dict] = [{"role": "user", "content": "q"}, {"role": "assistant", "content": "garbage"}]

    answer, table = await qa_agent._finalize_answer(messages, "not valid json at all", call_fn)

    assert answer == "corrected answer"
    call_fn.assert_awaited_once()
    # the corrective message must be appended as a user turn, not duplicate the assistant's
    assert messages[-1]["role"] == "user"
    assert "not valid JSON" in messages[-1]["content"]


async def test_finalize_answer_falls_back_to_raw_text_when_the_retry_also_fails():
    # deliberately malformed on BOTH the original attempt and the retry -
    # must still return cleanly, not raise.
    call_fn = AsyncMock(return_value="still not json, second time")
    messages: list[dict] = [{"role": "user", "content": "q"}, {"role": "assistant", "content": "garbage"}]

    answer, table = await qa_agent._finalize_answer(messages, "garbage not json", call_fn)

    assert answer == "still not json, second time"
    assert table is None
    call_fn.assert_awaited_once()  # exactly one retry, not an infinite loop


async def test_finalize_answer_does_not_crash_if_call_fn_itself_raises():
    # simulates a network failure during the retry call itself
    call_fn = AsyncMock(side_effect=RuntimeError("connection reset"))
    messages: list[dict] = [{"role": "user", "content": "q"}, {"role": "assistant", "content": "garbage"}]

    with pytest.raises(RuntimeError):
        await qa_agent._finalize_answer(messages, "garbage not json", call_fn)
    # This is intentionally NOT caught inside _finalize_answer - a genuine
    # network failure during the retry should propagate so the caller's
    # own error handling (e.g. the route's try/except) can respond with a
    # real error rather than silently returning a fabricated answer.


# --- Full loop, Anthropic path: deliberately malformed final response -----


def _anthropic_response(text: str, stop_reason: str = "end_turn") -> dict:
    return {"content": [{"type": "text", "text": text}], "stop_reason": stop_reason}


async def test_answer_question_anthropic_retries_on_malformed_final_json(monkeypatch):
    calls: list[dict] = []

    async def fake_call_model(messages, allow_tools, model=qa_agent.MODEL):
        calls.append({"allow_tools": allow_tools})
        if len(calls) == 1:
            return _anthropic_response("Sure, here you go: not valid json")
        return _anthropic_response('{"answer": "You spent $50 this month", "table": null}')

    monkeypatch.setattr(qa_agent, "_call_model", fake_call_model)

    result = await qa_agent.answer_question("How much did I spend?", owner_id=1, model=qa_agent.MODEL)

    assert result["answer"] == "You spent $50 this month"
    assert len(calls) == 2
    assert calls[1]["allow_tools"] is False  # the retry must not re-offer tools


async def test_answer_question_anthropic_degrades_gracefully_when_retry_also_malformed(monkeypatch):
    async def fake_call_model(messages, allow_tools, model=qa_agent.MODEL):
        return _anthropic_response("still not json, even on retry")

    monkeypatch.setattr(qa_agent, "_call_model", fake_call_model)

    # must not raise
    result = await qa_agent.answer_question("How much did I spend?", owner_id=1, model=qa_agent.MODEL)

    assert result["answer"] == "still not json, even on retry"
    assert result["table"] is None


# --- Full loop, Groq path: deliberately malformed final response ----------


def _groq_response(content: str | None = None, tool_calls: list[dict] | None = None) -> dict:
    message: dict = {"role": "assistant"}
    if content is not None:
        message["content"] = content
    if tool_calls is not None:
        message["tool_calls"] = tool_calls
    return {"choices": [{"message": message}]}


async def test_answer_question_groq_retries_on_malformed_final_json(monkeypatch):
    calls: list[dict] = []

    async def fake_call_groq(messages, model=None, tools=None, **kwargs):
        calls.append({"tools": tools})
        if len(calls) == 1:
            return _groq_response(content="Sure, here you go: not valid json")
        return _groq_response(content='{"answer": "You spent $50 this month", "table": null}')

    monkeypatch.setattr(qa_agent, "call_groq", fake_call_groq)

    result = await qa_agent.answer_question(
        "How much did I spend?", owner_id=1, model=qa_agent.GROQ_MODEL
    )

    assert result["answer"] == "You spent $50 this month"
    assert len(calls) == 2
    assert calls[1]["tools"] is None  # the retry must not re-offer tools


async def test_answer_question_groq_degrades_gracefully_when_retry_also_malformed(monkeypatch):
    async def fake_call_groq(messages, model=None, tools=None, **kwargs):
        return _groq_response(content="still not json, even on retry")

    monkeypatch.setattr(qa_agent, "call_groq", fake_call_groq)

    result = await qa_agent.answer_question(
        "How much did I spend?", owner_id=1, model=qa_agent.GROQ_MODEL
    )

    assert result["answer"] == "still not json, even on retry"
    assert result["table"] is None


# --- Full loop, Groq path: the tool-requesting call itself fails ----------
# A real failure mode observed live against Groq: whichever model is
# currently routed there occasionally emits a malformed function-call the
# API rejects outright with 400 "tool_use_failed", before any response
# body exists to parse - a different failure shape than a
# malformed-but-parseable JSON body, so it needs its own deliberate test
# rather than being covered by the JSON fallback tests above. Confirmed
# live against both llama-3.3-70b-versatile (before Groq decommissioned
# it) and its replacement openai/gpt-oss-120b that this happens on
# roughly half of attempts against the same question, with the retry only
# self-healing a minority of the time - so this needs a real Sonnet
# fallback, not just answering with no data (which produces an honest but
# useless "I don't know" - the bug this was rewritten to fix).


def _tool_use_failed_error() -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    response = httpx.Response(
        400,
        json={"error": {"message": "Failed to call a function.", "code": "tool_use_failed"}},
        request=request,
    )
    return httpx.HTTPStatusError("400 Bad Request", request=request, response=response)


async def test_answer_question_groq_retries_once_on_the_same_model_when_the_tool_call_fails(monkeypatch):
    calls: list[dict] = []

    async def fake_call_groq(messages, model=None, tools=None, **kwargs):
        calls.append({"model": model, "tools": tools})
        if len(calls) == 1:
            # first attempt: Groq rejects the malformed tool call outright
            raise _tool_use_failed_error()
        # retry against the SAME model succeeds and actually uses a tool
        if len(calls) == 2:
            return _groq_response(tool_calls=[{"id": "c1", "function": {"name": "get_transactions", "arguments": "{}"}}])
        return _groq_response(content='{"answer": "Your latest transaction was $42.50.", "table": null}')

    monkeypatch.setattr(qa_agent, "call_groq", fake_call_groq)
    monkeypatch.setattr(qa_agent, "_run_tool", AsyncMock(return_value=[{"merchant": "Trader Joe's", "amount": 42.5}]))

    result = await qa_agent.answer_question("what's my latest transaction", owner_id=1, model=qa_agent.GROQ_MODEL)

    assert result["answer"] == "Your latest transaction was $42.50."
    assert result["tools_used"] == ["get_transactions"]  # the retry's tool call was actually used
    assert result["recovery_path"] == "groq_retry"
    assert result["model_used"] == qa_agent.GROQ_MODEL  # stayed on Groq, no fallback needed
    # both the failed attempt and the successful retry offered tools on the same model
    assert calls[0]["model"] == qa_agent.GROQ_MODEL and calls[0]["tools"] is not None
    assert calls[1]["model"] == qa_agent.GROQ_MODEL and calls[1]["tools"] is not None


async def test_answer_question_groq_falls_back_to_sonnet_when_both_groq_attempts_fail(monkeypatch):
    groq_calls: list[dict] = []
    anthropic_calls: list[dict] = []

    async def fake_call_groq(messages, model=None, tools=None, **kwargs):
        groq_calls.append({"model": model, "tools": tools})
        raise _tool_use_failed_error()  # fails every time it's asked to offer tools

    async def fake_call_model(messages, allow_tools, model=qa_agent.MODEL):
        anthropic_calls.append({"model": model, "allow_tools": allow_tools})
        return _anthropic_response('{"answer": "Your latest transaction was $42.50.", "table": null}')

    monkeypatch.setattr(qa_agent, "call_groq", fake_call_groq)
    monkeypatch.setattr(qa_agent, "_call_model", fake_call_model)

    # must not raise, and must not fabricate a no-data answer - both Groq
    # attempts failing should produce a real, data-grounded Sonnet answer
    result = await qa_agent.answer_question("what's my latest transaction", owner_id=1, model=qa_agent.GROQ_MODEL)

    assert result["answer"] == "Your latest transaction was $42.50."
    assert result["recovery_path"] == "sonnet_fallback"
    assert result["model_used"] == qa_agent.SONNET_MODEL  # NOT the originally-requested Groq model
    assert len(groq_calls) == 2  # original attempt + one retry, both on Groq
    assert all(c["tools"] is not None for c in groq_calls)  # both attempts actually tried to offer tools
    assert len(anthropic_calls) == 1
    assert anthropic_calls[0]["model"] == qa_agent.SONNET_MODEL
    assert anthropic_calls[0]["allow_tools"] is True  # the Sonnet fallback must have tools available


async def test_answer_question_groq_propagates_if_the_sonnet_fallback_itself_also_fails(monkeypatch):
    async def fake_call_groq(messages, model=None, tools=None, **kwargs):
        raise _tool_use_failed_error()

    async def failing_call_model(messages, allow_tools, model=qa_agent.MODEL):
        raise httpx.ConnectError("network is down")

    monkeypatch.setattr(qa_agent, "call_groq", fake_call_groq)
    monkeypatch.setattr(qa_agent, "_call_model", failing_call_model)

    # a total outage on both Groq AND the Sonnet fallback is a genuine
    # failure with nothing left to gracefully degrade to - this should
    # propagate, not silently fabricate an answer.
    with pytest.raises(httpx.ConnectError):
        await qa_agent.answer_question("what's my latest transaction", owner_id=1, model=qa_agent.GROQ_MODEL)


async def test_compare_models_labels_a_fallen_back_groq_side_as_sonnet(monkeypatch):
    # If the "groq" side of Compare Models had to fall back to Sonnet, the
    # UI must not keep labeling that card with the Groq model's name - it
    # has to report the model that actually answered.
    async def fake_call_groq(messages, model=None, tools=None, **kwargs):
        raise _tool_use_failed_error()

    async def fake_call_model(messages, allow_tools, model=qa_agent.MODEL):
        return _anthropic_response('{"answer": "real answer", "table": null}')

    monkeypatch.setattr(qa_agent, "call_groq", fake_call_groq)
    monkeypatch.setattr(qa_agent, "_call_model", fake_call_model)

    result = await qa_agent.compare_models("what's my latest transaction", owner_id=1)

    assert result["groq"]["model"] == qa_agent.SONNET_MODEL
    assert result["groq"]["answer"] == "real answer"
