"""Local-only transport observations, including failed/repair model attempts."""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Collection, Iterator
from contextlib import contextmanager
from copy import deepcopy
from typing import Any
from unittest.mock import patch

from google_work_agent.adapters.llm.ollama import transport as ollama_transport
from google_work_agent.adapters.llm.ollama.transport import OllamaHTTPClient


def object_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()


@contextmanager
def observe_local_calls(records: list[dict[str, Any]]) -> Iterator[None]:
    original = OllamaHTTPClient.invoke_structured

    def invoke(client: Any, **kwargs: Any) -> Any:
        event = {
            "prompt_id": kwargs["prompt_ref"].prompt_id,
            "input": deepcopy(kwargs["prompt_input"]),
            "input_sha256": object_hash(kwargs["prompt_input"]),
            "schema_sha256": object_hash(kwargs["output_schema"].json_schema),
            "instruction_sha256": hashlib.sha256(kwargs["instruction_text"].encode()).hexdigest(),
            "temperature": kwargs.get("sampling_temperature"),
            "seed": kwargs.get("sampling_seed"),
            "model": kwargs["model_id"],
            "timeout_seconds": kwargs["timeout_seconds"],
        }
        records.append(event)
        started = time.perf_counter()
        try:
            result = original(client, **kwargs)
            event.update(
                content=result.content,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                latency_ms=result.latency_ms,
            )
            return result
        except Exception as error:
            event.update(error_type=type(error).__name__, error=str(error)[:500])
            raise
        finally:
            event["wall_latency_ms"] = int((time.perf_counter() - started) * 1000)

    with patch.object(OllamaHTTPClient, "invoke_structured", invoke):
        yield


def metrics(calls: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "calls": len(calls),
        "input_tokens": sum(call.get("input_tokens") or 0 for call in calls),
        "output_tokens": sum(call.get("output_tokens") or 0 for call in calls),
        "reported_latency_ms": sum(call.get("latency_ms") or 0 for call in calls),
        "missing_usage_calls": sum(
            call.get("input_tokens") is None or call.get("output_tokens") is None
            for call in calls
        ),
    }


@contextmanager
def source_format_only_envelope(records: list[dict[str, Any]]) -> Iterator[None]:
    """Keep constrained decoding, remove the duplicated schema from Source prompt text only."""
    original = ollama_transport._post_json

    def dispatch(**kwargs: Any) -> Any:
        payload = kwargs["payload"]
        if kwargs["path"] == "/api/generate":
            prompt = json.loads(payload["prompt"])
            if (
                prompt["prompt_ref"]["prompt_id"]
                == "request_understanding.identify_source_dependencies"
            ):
                prompt.pop("output_schema")
                payload = {
                    **payload,
                    "prompt": json.dumps(prompt, sort_keys=True, ensure_ascii=False),
                }
                kwargs["payload"] = payload
                if records:
                    records[-1]["wire_prompt_sha256"] = object_hash(prompt)
                    records[-1]["envelope"] = "SOURCE_SCHEMA_IN_FORMAT_ONLY"
        return original(**kwargs)

    with patch.object(ollama_transport, "_post_json", dispatch):
        yield


@contextmanager
def source_input_once_envelope(records: list[dict[str, Any]]) -> Iterator[None]:
    """V22 removes one exact FIRST input copy, not v10's duplicated schema.

    The Product system instruction remains byte-identical. Repairs retain their
    existing envelope because their assembled failure projection is not an exact
    copy of the complete repair input. Usage remains the transport observer's
    actual provider usage, never a token estimate for the removed text.
    """
    original = ollama_transport._post_json
    source_prompt_id = "request_understanding.identify_source_dependencies"
    marker = "Allowed current-Run input projection (JSON):\n"

    def dispatch(**kwargs: Any) -> Any:
        payload = kwargs["payload"]
        if kwargs["path"] != "/api/generate" or not isinstance(payload.get("prompt"), str):
            return original(**kwargs)
        prompt_text = payload["prompt"]
        try:
            prompt = json.loads(prompt_text)
        except json.JSONDecodeError:
            return original(**kwargs)
        prompt_ref = prompt.get("prompt_ref") if isinstance(prompt, dict) else None
        if not isinstance(prompt_ref, dict) or prompt_ref.get("prompt_id") != source_prompt_id:
            return original(**kwargs)
        event = (
            records[-1]
            if records and records[-1].get("prompt_id") == source_prompt_id
            else None
        )
        projection = prompt.get("input")
        system = payload.get("system")
        if not isinstance(projection, dict) or not isinstance(system, str):
            raise ValueError("Source input-once requires a structured input and system instruction")
        before_hash = hashlib.sha256(prompt_text.encode()).hexdigest()
        action = "REPAIR_UNCHANGED"
        if "base_projection" not in projection:
            projection_text = json.dumps(
                projection, ensure_ascii=False, separators=(",", ":"), sort_keys=True
            )
            if marker + projection_text not in system:
                raise ValueError("Source FIRST input has no identical assembled system copy")
            prompt = {key: value for key, value in prompt.items() if key != "input"}
            prompt_text = json.dumps(prompt, sort_keys=True, ensure_ascii=False)
            kwargs["payload"] = {**payload, "prompt": prompt_text}
            action = "FIRST_REMOVED"
        if event is not None:
            event.update(
                envelope="SOURCE_INPUT_ONCE",
                input_copy_action=action,
                wire_prompt_before_sha256=before_hash,
                wire_prompt_after_sha256=hashlib.sha256(prompt_text.encode()).hexdigest(),
                unchanged_system_sha256=hashlib.sha256(system.encode()).hexdigest(),
                unchanged_format_sha256=object_hash(payload.get("format")),
                unchanged_options_sha256=object_hash(payload.get("options")),
                retained_input_sha256=object_hash(projection),
            )
        return original(**kwargs)

    with patch.object(ollama_transport, "_post_json", dispatch):
        yield


@contextmanager
def thinking_envelope(records: list[dict[str, Any]], prompt_ids: Collection[str]) -> Iterator[None]:
    """Enable provider thinking only for selected evaluation structured calls.

    Thinking text stays in the transport response and is never added to records.
    The normal observer retains final output and provider usage/latency counters.
    """
    selected_ids = frozenset(prompt_ids)
    original = ollama_transport._post_json

    def dispatch(**kwargs: Any) -> Any:
        payload = kwargs["payload"]
        if kwargs["path"] != "/api/generate":
            return original(**kwargs)
        prompt_text = payload.get("prompt")
        if not isinstance(prompt_text, str):
            return original(**kwargs)
        try:
            prompt = json.loads(prompt_text)
        except json.JSONDecodeError:
            return original(**kwargs)
        prompt_ref = prompt.get("prompt_ref") if isinstance(prompt, dict) else None
        prompt_id = prompt_ref.get("prompt_id") if isinstance(prompt_ref, dict) else None
        if not isinstance(prompt_id, str) or prompt_id not in selected_ids:
            return original(**kwargs)
        event = records[-1] if records and records[-1].get("prompt_id") == prompt_id else None
        kwargs["payload"] = {**payload, "think": True}
        if event is not None:
            event["think_requested"] = True
        response = original(**kwargs)
        thinking = response.get("thinking")
        if event is not None:
            event["thinking_present"] = isinstance(thinking, str) and bool(thinking)
            event["thinking_char_count"] = len(thinking) if isinstance(thinking, str) else 0
        return response

    with patch.object(ollama_transport, "_post_json", dispatch):
        yield


@contextmanager
def source_chat_envelope(records: list[dict[str, Any]], thinking: bool) -> Iterator[None]:
    """Probe Source structured-output compatibility using the chat transport only."""
    original = ollama_transport._post_json
    source_prompt_id = "request_understanding.identify_source_dependencies"

    def dispatch(**kwargs: Any) -> Any:
        payload = kwargs["payload"]
        if kwargs["path"] != "/api/generate":
            return original(**kwargs)
        prompt_text = payload.get("prompt")
        if not isinstance(prompt_text, str):
            return original(**kwargs)
        try:
            prompt = json.loads(prompt_text)
        except json.JSONDecodeError:
            return original(**kwargs)
        prompt_ref = prompt.get("prompt_ref") if isinstance(prompt, dict) else None
        if not isinstance(prompt_ref, dict) or prompt_ref.get("prompt_id") != source_prompt_id:
            return original(**kwargs)
        event = (
            records[-1] if records and records[-1].get("prompt_id") == source_prompt_id else None
        )
        kwargs["path"] = "/api/chat"
        kwargs["payload"] = {
            **{key: value for key, value in payload.items() if key not in {"system", "prompt"}},
            "messages": [
                {"role": "system", "content": payload["system"]},
                {"role": "user", "content": prompt_text},
            ],
            "think": thinking,
        }
        if event is not None:
            event.update(envelope="SOURCE_CHAT", think_requested=thinking)
        response = original(**kwargs)
        message = response.get("message")
        if not isinstance(message, dict):
            raise ValueError("Source chat response requires message object")
        content = message.get("content")
        if not isinstance(content, str):
            raise ValueError("Source chat response requires string content")
        reasoning = message.get("thinking")
        if event is not None:
            event["thinking_present"] = isinstance(reasoning, str) and bool(reasoning)
            event["thinking_char_count"] = len(reasoning) if isinstance(reasoning, str) else 0
        return {
            **{key: value for key, value in response.items() if key not in {"message", "thinking"}},
            "response": content,
        }

    with patch.object(ollama_transport, "_post_json", dispatch):
        yield
