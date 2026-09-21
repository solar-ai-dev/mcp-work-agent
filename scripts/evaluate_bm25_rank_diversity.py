"""Compare lexical rankers on frozen fixture-derived pools without LLM or READ."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any, cast

from evaluation.bm25_rank_candidate import (
    DEFAULT_BM25_CANDIDATE_CONFIG,
    bm25_rag_retrieve_rerank,
)
from evaluation.dataset_v8 import DEFAULT_PROVIDER_FIXTURE_PATH, load_cases
from scripts.serve_canonical_v8_product import _case_resources, _normalize_provider_resources

from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestIntentV3,
)
from google_work_agent.application.agents.retrieval.normalize_segments import (
    ContextBudget,
    SourceSegment,
    normalize_segments,
)
from google_work_agent.application.agents.retrieval.rag_retrieve_rerank import (
    DEFAULT_RAG_SCORING_CONFIG,
    RagCandidateV1,
    rag_retrieve_rerank,
)

DEFAULT_MANIFEST = Path("evaluation/derived_queries/source-query-diversity-v1.json")
DEFAULT_TOP_K = 4


def _fingerprint(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    ).hexdigest()


def _resource_handle(resource: dict[str, Any]) -> str:
    return f"{resource['resource_type']}:{resource['resource_id']}"


def _pool_for_case(case: Any, common_resources: list[dict[str, Any]]) -> list[SourceSegment]:
    resources = [*_case_resources(case.raw), *common_resources]
    summaries = []
    for source, resource_types in (
        ("GMAIL", {"gmail_thread", "gmail_message", "gmail_draft"}),
        ("TASKS", {"task", "task_list"}),
        ("CALENDAR", {"calendar", "calendar_event", "calendar_freebusy"}),
    ):
        current = [
            {
                **resource,
                "resource_handle": _resource_handle(resource),
                "connector_id": "google_workspace",
            }
            for resource in resources
            if resource["resource_type"] in resource_types
        ]
        summaries.append({"source": source, "resources": current})
    return normalize_segments(
        cast(Any, {"source_summaries": summaries}),
        context_budget=ContextBudget(max_segments=24),
    )


def _rank(
    request: str,
    segments: list[SourceSegment],
    *,
    target_ids: list[str],
    top_k: int,
    use_bm25: bool,
) -> dict[str, object]:
    intent = cast(RequestIntentV3, {"goal": request, "constraints": []})
    started = time.perf_counter()
    ranker = bm25_rag_retrieve_rerank if use_bm25 else rag_retrieve_rerank
    ranked = ranker(
        segments,
        request_intent=intent,
        source_plans=[],
        top_k=top_k,
    )
    by_id = {segment.segment_id: segment for segment in segments}
    target_positions = {
        resource_id: next(
            (
                index + 1
                for index, candidate in enumerate(ranked)
                if by_id[candidate["segment_id"]].resource_id == resource_id
            ),
            None,
        )
        for resource_id in target_ids
    }
    return {
        "elapsed_ms": round((time.perf_counter() - started) * 1_000, 3),
        "ranked": [_ranked_summary(candidate, by_id) for candidate in ranked],
        "target_positions": target_positions,
        "target_count_in_top_k": sum(
            position is not None for position in target_positions.values()
        ),
    }


def _ranked_summary(
    candidate: RagCandidateV1,
    segments_by_id: dict[str, SourceSegment],
) -> dict[str, object]:
    segment = segments_by_id[candidate["segment_id"]]
    return {
        "segment_id": segment.segment_id,
        "resource_type": segment.resource_type,
        "resource_id": segment.resource_id,
        "score": round(candidate["retrieval_score"], 5),
        "reason_codes": candidate["reason_codes"],
    }


def _write_result(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def evaluate(
    manifest_path: Path,
    result_path: Path,
    *,
    preflight_only: bool = False,
    top_k: int = DEFAULT_TOP_K,
) -> dict[str, object]:
    if top_k < 1:
        raise ValueError("top_k must be positive")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    cases = load_cases()
    snapshot = json.loads(DEFAULT_PROVIDER_FIXTURE_PATH.read_text(encoding="utf-8"))
    common_resources = _normalize_provider_resources(snapshot["common_distractors"]["resources"])
    variants = manifest["cases"]
    if len(variants) != 24 or Counter(item["variant"] for item in variants) != {
        "A": 6,
        "B": 6,
        "C": 6,
        "D": 6,
    }:
        raise ValueError("derived corpus must have six complete A/B/C/D families")
    pools = {
        case_id: _pool_for_case(cases[case_id], common_resources)
        for case_id in {item["origin_case_id"] for item in variants}
    }
    result: dict[str, object] = {
        "binding": {
            "manifest_hash": _fingerprint(manifest),
            "provider_snapshot_hash": hashlib.sha256(
                DEFAULT_PROVIDER_FIXTURE_PATH.read_bytes()
            ).hexdigest(),
            "pool_kind": "FIXTURE_PACK_PLUS_COMMON_DISTRACTORS_NOT_ACTUAL_READ",
            "query_input_kind": "RAW_TEXT_SURROGATE_NOT_RU_STATE",
            "top_k": top_k,
            "preprocessing": "shared_whitespace_punctuation_clean_terms",
            "baseline_config": asdict(DEFAULT_RAG_SCORING_CONFIG),
            "candidate_config": {
                **asdict(DEFAULT_RAG_SCORING_CONFIG),
                "lexical_ranker": "BM25",
                **asdict(DEFAULT_BM25_CANDIDATE_CONFIG),
            },
            "llm_dispatch_count": 0,
            "provider_read_count": 0,
            "provider_write_count": 0,
        },
        "cases": [],
    }
    for variant in variants:
        origin = variant["origin_case_id"]
        if (
            variant["variant"] == "A"
            and variant["request"] != cases[origin].raw["canonical_user_prompt"]
        ):
            raise ValueError(f"{origin}: base request differs from unchanged dataset")
        segments = pools[origin]
        target_ids = variant.get("rank_target_resource_ids", [])
        available_ids = {segment.resource_id for segment in segments}
        if not set(target_ids) <= available_ids:
            raise ValueError(f"{origin}: target is absent from fixed pool")
        cast(list[dict[str, object]], result["cases"]).append(
            {
                "origin_case_id": origin,
                "family": variant["family"],
                "variant": variant["variant"],
                "difficulty": variant["difficulty"],
                "request_fingerprint": _fingerprint(variant["request"]),
                "pool_fingerprint": _fingerprint(
                    [(item.segment_id, item.resource_id, item.version) for item in segments]
                ),
                "pool_size": len(segments),
                "pool_resource_type_counts": dict(Counter(item.resource_type for item in segments)),
                "target_ids": target_ids,
                "verification_rule": variant.get("verification_rule"),
                "baseline": None,
                "bm25": None,
            }
        )
    _write_result(result_path, result)
    if preflight_only:
        return result
    for record, variant in zip(
        cast(list[dict[str, object]], result["cases"]), variants, strict=True
    ):
        try:
            segments = pools[variant["origin_case_id"]]
            record["baseline"] = _rank(
                variant["request"],
                segments,
                target_ids=record["target_ids"],
                top_k=top_k,
                use_bm25=False,
            )
            _write_result(result_path, result)
            record["bm25"] = _rank(
                variant["request"],
                segments,
                target_ids=record["target_ids"],
                top_k=top_k,
                use_bm25=True,
            )
        except Exception as error:
            record["error_type"] = type(error).__name__
            record["error"] = str(error)[:300]
        _write_result(result_path, result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--top-k", type=int, default=DEFAULT_TOP_K)
    arguments = parser.parse_args()
    output = evaluate(
        arguments.manifest,
        arguments.result,
        preflight_only=arguments.preflight_only,
        top_k=arguments.top_k,
    )
    print(json.dumps({"case_count": len(output["cases"]), "preflight": arguments.preflight_only}))
