"""Evaluation-only exposure of existing typed Source-scope constraint fields."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from copy import deepcopy
from typing import Any, cast
from unittest.mock import patch

from google_work_agent.application.agents.request_understanding.contracts import (
    request_goal_candidate_schema as goal_schema,
)

SOURCE_SCOPE_FIELDS = ("required_sources", "forbidden_sources")
SOURCE_CATEGORIES = ("EMAIL", "TASK", "CALENDAR", "ISSUE")


@contextmanager
def source_scope_candidate() -> Iterator[None]:
    """Use existing Constraint kind/fields without inferring a Source from request text.

    The shared schema object is patched in place so imported builders, the default
    validator schema, and Goal/Output v4 all see the same bounded experiment.
    Normalization keeps its existing owner and item-local WorkUnit bindings.
    """
    additional_schema = goal_schema._ADDITIONAL_CONSTRAINT_LIST_SCHEMA
    item = cast(dict[str, Any], additional_schema["items"])
    candidate = deepcopy(item)
    field_schema = candidate["properties"]["field"]
    field_schema["enum"] = sorted(set(field_schema["enum"]) | set(SOURCE_SCOPE_FIELDS))
    field_schema["description"] = (
        "제품이 지원하는 명시적 업무값 또는 Source 제한 필드 하나를 선택한다."
    )
    candidate["allOf"] = [
        *candidate.get("allOf", []),
        {
            "if": {
                "properties": {"field": {"enum": list(SOURCE_SCOPE_FIELDS)}},
                "required": ["field"],
            },
            "then": {
                "properties": {
                    "value": {
                        "oneOf": [
                            {"enum": list(SOURCE_CATEGORIES)},
                            {
                                "type": "array",
                                "minItems": 1,
                                "items": {"enum": list(SOURCE_CATEGORIES)},
                            },
                        ]
                    }
                }
            },
        },
    ]
    with (
        patch.dict(item, candidate, clear=True),
        patch.dict(
            goal_schema._ADDITIONAL_CONSTRAINT_FIELD_KINDS,
            {field: "SCOPE" for field in SOURCE_SCOPE_FIELDS},
        ),
    ):
        yield
