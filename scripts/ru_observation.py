"""Local-only transport observations, including failed/repair model attempts."""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Iterator
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
        "missing_usage_calls": sum("input_tokens" not in call for call in calls),
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
