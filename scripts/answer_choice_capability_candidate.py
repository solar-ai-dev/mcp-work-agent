"""Inactive 087 choice envelope for caller-validated, sealed Planning inputs.

The caller must verify same-Run Evidence/snapshot authority before invoking this
helper. A missing catalog does not distinguish unsupported facts from invalid
snapshots and is not an authorization decision. This bounded experiment accepts
only already validated 065/084/085 observations; it does not recover stale or
missing snapshots, classify requests, or retry a failed model response.
"""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from scripts import evaluate_answer_mode_first as ordered
from scripts import evaluate_answer_rendering_choice as choice
from scripts.answer_fact_selection_candidate import bind_fact_selection_schema


def build_capability_wire(
    original: dict[str, Any],
    projection: dict[str, Any],
    snapshots: dict[str, Any],
) -> dict[str, Any]:
    """Keep Product bytes unless the existing fact renderer has a capability.

    Catalog/validation exceptions propagate. Neither an absent catalog nor the
    returned wire asserts semantic sufficiency, snapshot validity, or success.
    """
    prompt = original.get("prompt")
    if not isinstance(projection, dict) or not isinstance(prompt, str):
        raise ValueError("a Product compose wire and its exact input are required")
    try:
        body = json.loads(prompt)
    except ValueError as error:
        raise ValueError("a Product compose wire and its exact input are required") from error
    if (
        not isinstance(body, dict)
        or not isinstance(body.get("input"), dict)
        or body["input"] != projection
    ):
        raise ValueError("input differs from the Product compose wire")
    if bind_fact_selection_schema(projection, source_snapshots=snapshots) is None:
        return deepcopy(original)
    return ordered.mode_first_wire(choice.choice_wire(original, projection, snapshots))


__all__ = ["build_capability_wire"]
