"""Queued Ollama HTTP responses shared by wire-level tests without model calls."""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

import pytest

from google_work_agent.adapters.llm.ollama import transport


def fake_ollama_transport(
    monkeypatch: pytest.MonkeyPatch, outputs: list[Any], *, model_id: str
) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    def post(**kwargs: Any) -> dict[str, Any]:
        calls.append(deepcopy(kwargs))
        return {
            "response": json.dumps(outputs.pop(0), ensure_ascii=False),
            "model": model_id,
            "prompt_eval_count": 30,
            "eval_count": 20,
            "total_duration": 1000000,
        }

    monkeypatch.setattr(transport, "_post_json", post)
    return calls
