"""Synthetic current Source FIRST wire shared by evaluation contract tests."""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

import pytest

from google_work_agent.application.agents.request_understanding.identify_source_dependencies import (  # noqa: E501
    build_source_dependency_candidates,
    build_source_dependency_output_schema,
)
from google_work_agent.application.prompt_runtime.assemble_prompt import assemble_prompt
from google_work_agent.application.prompt_runtime.prompt_registry import EVALUATION, PromptRegistry
from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_development_tool_registry,
)


@pytest.fixture
def product_wire() -> dict[str, Any]:
    request = "작업 목록의 제목과 상태를 알려줘. 새 작업은 만들지 마."
    registry = PromptRegistry()
    ref = registry.lookup_for_evaluation("request_understanding.identify_source_dependencies")
    candidates = list(build_source_dependency_candidates(load_development_tool_registry()))
    projection = {
        "user_request": request,
        "selected_resource_refs": [],
        "run_reference_time": {"now_utc": "2026-09-29T00:00:00Z"},
        "goal_candidate": {"goal": request},
        "source_candidates": candidates,
        "requested_work": {
            "work_units": [
                {
                    "unit_id": "work-1",
                    "request_provenance": [
                        {
                            "source": "USER_REQUEST",
                            "start_offset": 0,
                            "end_offset": len(request),
                            "source_text": request,
                        }
                    ],
                }
            ],
            "work_relations": [],
        },
    }
    schema = build_source_dependency_output_schema(candidates, work_unit_ids=["work-1"])
    return {
        "model": "qwen3.5:9b",
        "system": assemble_prompt(ref, projection, registry=registry, execution_scope=EVALUATION),
        "prompt": json.dumps(
            {
                "prompt_ref": {
                    "prompt_id": ref.prompt_id,
                    "prompt_version": ref.prompt_version,
                    "content_hash": ref.content_hash,
                },
                "input": projection,
                "output_schema": schema.json_schema,
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
        "format": deepcopy(schema.json_schema),
        "stream": False,
        "think": False,
        "options": {"num_ctx": 16_384, "temperature": 0.05, "seed": 20260923},
    }
