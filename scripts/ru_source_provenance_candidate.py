"""Inactive Source-owned exact request references; no inferred search/identity authority."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any, cast

from evaluation.request_semantic_authority_candidate import _request_tokens
from scripts.ru_observation import object_hash
from scripts.ru_source_focal_candidate import INPUT_FIELDS, PROMPT_ID

from google_work_agent.application.agents.request_understanding.identify_source_dependencies import (  # noqa: E501
    build_source_dependency_candidates,
    build_source_dependency_output_schema,
    validate_source_dependency_candidate,
)
from google_work_agent.application.agents.tool_routing.bind_registry_candidates import (
    coarse_resource_category,
)
from google_work_agent.application.prompt_runtime.assemble_prompt import assemble_prompt
from google_work_agent.application.prompt_runtime.prompt_registry import EVALUATION, PromptRegistry
from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_development_tool_registry,
)
from google_work_agent.ports.llm.output_schema_validation import validate_output_schema

CANDIDATE_ID = "evaluation.source_request_provenance"
DECLARATION = (
    "각 SOURCE_REQUIRED의 source_request_ranges에는 그 Resource의 조회 필요성을 정의하는 "
    "사용자 원문 구간을 request_tokens의 start_token_id/end_token_id로 선택한다. "
    "양 끝 토큰을 포함하며, 조회할 자료와 요청한 새 산출물은 구분한다. "
    "이는 요청의 근거 구간이지 Provider identity나 검색 Query가 아니다."
)


def _schema(projection: dict[str, Any]) -> dict[str, Any]:
    schema = cast(
        dict[str, Any],
        deepcopy(
            build_source_dependency_output_schema(
                projection["source_candidates"],
                work_unit_ids=[u["unit_id"] for u in projection["requested_work"]["work_units"]],
            ).json_schema
        ),
    )
    token_ids = [t["token_id"] for t in _request_tokens(projection["user_request"])]
    if not token_ids:
        raise ValueError("current request tokens required")
    required = schema["properties"]["source_dependencies"]["items"]["oneOf"][1]
    required["required"].insert(2, "source_request_ranges")
    properties = required["properties"]
    required["properties"] = {
        "resource_type": properties.pop("resource_type"),
        "dependency": properties.pop("dependency"),
        "source_request_ranges": {
            "type": "array",
            "minItems": 1,
            "maxItems": len(token_ids),
            "uniqueItems": True,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["start_token_id", "end_token_id"],
                "properties": {
                    name: {"enum": token_ids} for name in ("start_token_id", "end_token_id")
                },
            },
        },
        **properties,
    }
    return schema


def build_payload(original: dict[str, Any]) -> dict[str, Any]:
    """Keep full Product FIRST context/options; extend only Source representation."""
    body = json.loads(original["prompt"])
    if set(body) != {"prompt_ref", "input", "output_schema"}:
        raise ValueError("Product FIRST envelope required")
    projection = body["input"]
    if set(projection) != INPUT_FIELDS:
        raise ValueError("exact Source FIRST fields required")
    registry = PromptRegistry()
    ref = registry.lookup_for_evaluation(PROMPT_ID)
    if body["prompt_ref"] != {
        "prompt_id": ref.prompt_id,
        "prompt_version": ref.prompt_version,
        "content_hash": ref.content_hash,
    }:
        raise ValueError("current Product Source PromptRef required")
    catalog = list(build_source_dependency_candidates(load_development_tool_registry()))
    schema = build_source_dependency_output_schema(
        catalog, work_unit_ids=[u["unit_id"] for u in projection["requested_work"]["work_units"]]
    ).json_schema
    if projection["source_candidates"] != catalog or body["output_schema"] != schema:
        raise ValueError("current Product catalog/schema required")
    instruction = assemble_prompt(ref, projection, registry=registry, execution_scope=EVALUATION)
    if original["system"] != instruction or original.get("format") != schema:
        raise ValueError("current Product assembly/format required")
    role = registry.source_text(PROMPT_ID).rstrip()
    suffix = (
        json.dumps(projection, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"
    )
    if not instruction.startswith(role + "\n\n") or not instruction.endswith(suffix):
        raise ValueError("unsupported Product assembly")
    result, candidate = deepcopy(original), deepcopy(body)
    candidate["input"]["request_tokens"] = [
        {"token_id": t["token_id"], "text": t["text"]}
        for t in _request_tokens(projection["user_request"])
    ]
    candidate_role = role + "\n\n" + DECLARATION
    candidate["prompt_ref"] = {
        "prompt_id": CANDIDATE_ID,
        "prompt_version": "v1",
        "content_hash": hashlib.sha256(candidate_role.encode("utf-8")).hexdigest(),
    }
    candidate["output_schema"] = _schema(projection)
    result["format"] = deepcopy(candidate["output_schema"])
    result["system"] = (
        candidate_role
        + instruction[len(role) : -len(suffix)]
        + json.dumps(candidate["input"], ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    )
    result["prompt"] = json.dumps(candidate, ensure_ascii=False, sort_keys=True)
    return result


def admit_source(content: object, payload: dict[str, Any]) -> dict[str, Any]:
    """Select offsets without semantic correction; retain full owner decisions separately."""
    body = json.loads(payload["prompt"])
    projection = body["input"]
    tokens = _request_tokens(projection["user_request"])
    if (
        set(projection) != INPUT_FIELDS | {"request_tokens"}
        or projection["request_tokens"]
        != [{"token_id": t["token_id"], "text": t["text"]} for t in tokens]
        or body["output_schema"] != _schema(projection)
        or payload.get("format") != body["output_schema"]
    ):
        raise ValueError("frozen Source provenance input/schema drift")
    result: dict[str, Any] = {"validated_source": None, "source_artifacts": None}
    try:
        value = json.loads(content) if isinstance(content, str) else None
    except json.JSONDecodeError as error:
        return {**result, "validation": {"structural_result": "INVALID_JSON", "error": str(error)}}
    errors = list(validate_output_schema(value, body["output_schema"]))
    if errors:
        return {**result, "validation": {"structural_result": "INVALID_SCHEMA", "errors": errors}}
    source = cast(dict[str, Any], deepcopy(value))
    artifacts = []
    by_id = {t["token_id"]: t for t in tokens}
    try:
        for item in source["source_dependencies"]:
            if item["dependency"] != "SOURCE_REQUIRED":
                continue
            provenance = []
            for selected in item.pop("source_request_ranges"):
                start = cast(int, by_id[selected["start_token_id"]]["start_offset"])
                end = cast(int, by_id[selected["end_token_id"]]["end_offset"])
                if end <= start:
                    raise ValueError("reversed Source request range")
                provenance.append(
                    {
                        "source": "USER_REQUEST",
                        "start_offset": start,
                        "end_offset": end,
                        "source_text": projection["user_request"][start:end],
                    }
                )
            artifacts.append({"source_item": deepcopy(item), "request_provenance": provenance})
        validated = validate_source_dependency_candidate(
            source,
            source_candidates=projection["source_candidates"],
            work_unit_ids=[u["unit_id"] for u in projection["requested_work"]["work_units"]],
        )
    except ValueError as error:
        return {
            **result,
            "validation": {"structural_result": "OWNER_REJECTED", "error": str(error)},
        }
    artifact_state = {
        "schema_version": "evaluation-source-request-provenance-v1",
        "user_request_sha256": object_hash(projection["user_request"]),
        "requested_work_sha256": object_hash(projection["requested_work"]),
        "source_input_sha256": object_hash({k: projection[k] for k in INPUT_FIELDS}),
        "items": artifacts,
    }
    return {
        "validation": {"structural_result": "VALIDATED", "validated_output": value},
        "validated_source": validated,
        "source_artifacts": artifact_state,
        "artifact_sha256": object_hash(artifact_state),
        "semantic_verdict": "NOT_REVIEWED",
    }


def project_query_context(
    query_input: dict[str, Any],
    admission: dict[str, Any],
    *,
    requested_work: dict[str, Any],
    input_routes: list[dict[str, Any]],
    source_input: dict[str, Any],
) -> dict[str, Any]:
    """Evaluation-only context sidecar; never edit anchors, routes, or Provider arguments."""
    artifact = admission["source_artifacts"]
    if (
        not artifact
        or admission["validation"]["structural_result"] != "VALIDATED"
        or object_hash(artifact) != admission["artifact_sha256"]
        or object_hash(query_input["user_request"]) != artifact["user_request_sha256"]
        or object_hash(requested_work) != artifact["requested_work_sha256"]
        or query_input["request_intent"]["requested_work"] != requested_work
        or set(source_input) != INPUT_FIELDS
        or object_hash(source_input) != artifact["source_input_sha256"]
    ):
        raise ValueError("Source artifact/current request binding mismatch")
    required = [
        i
        for i in admission["validated_source"]["source_dependencies"]
        if i["dependency"] == "SOURCE_REQUIRED"
    ]
    if [i["source_item"] for i in artifact["items"]] != required:
        raise ValueError("Source artifact differs from admitted owner output")
    expected_sources = {
        object_hash({k: v for k, v in item.items() if k != "dependency"}) for item in required
    }
    current_sources = query_input["request_intent"]["resource_responsibilities"]["source_reads"]
    if (
        len(current_sources) != len(required)
        or {object_hash(item) for item in current_sources} != expected_sources
    ):
        raise ValueError("Source meaning changed between admission and Query input")
    if "source_request_context" in query_input:
        raise ValueError("Query Source provenance already bound")
    context, consumed = [], set()
    routes = input_routes
    by_route = {r["route_id"]: r for r in query_input["input_routes"]}
    if (
        len(by_route) != len(routes)
        or len(query_input["input_routes"]) != len(routes)
        or len({r["route_id"] for r in routes}) != len(routes)
    ):
        raise ValueError("Query route identity changed")
    for route in routes:
        projected = by_route.get(route["route_id"])
        if (
            projected is None
            or projected["resource_type"] != coarse_resource_category(route["resource_type"])
            or projected["work_unit_ids"] != route["work_unit_ids"]
        ):
            raise ValueError("Query route identity/Work projection changed")
    types = {r["resource_type"] for r in routes}
    for route in routes:
        items = []
        for index, item in enumerate(artifact["items"]):
            source = item["source_item"]
            matches = source["resource_type"] == route["resource_type"] or (
                source["resource_type"] == "GMAIL_MESSAGE"
                and route["resource_type"] == "GMAIL_THREAD"
                and "GMAIL_MESSAGE" not in types
            )
            if not matches:
                continue
            if not set(source["work_unit_ids"]).issubset(route["work_unit_ids"]):
                raise ValueError("Source Work binding lost before Query")
            items.append(deepcopy(item))
            consumed.add(index)
        if items:
            context.append({"route_id": route["route_id"], "sources": items})
    if consumed != set(range(len(artifact["items"]))):
        raise ValueError("Source artifact has no compatible Query route")
    return {**deepcopy(query_input), "source_request_context": context}
