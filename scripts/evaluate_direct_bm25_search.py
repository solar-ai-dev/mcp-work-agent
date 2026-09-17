"""Search one common fixture corpus with LangChain BM25 and bounded query hypotheses."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from collections import Counter
from importlib.metadata import version
from pathlib import Path
from typing import Any, cast
from urllib.request import Request, urlopen

from evaluation.dataset_v8 import DEFAULT_PROVIDER_FIXTURE_PATH, load_cases
from scripts.serve_canonical_v8_product import _normalize_provider_resources

from google_work_agent.application.agents.retrieval.normalize_segments import (
    ContextBudget,
    SourceSegment,
    normalize_segments,
)
from google_work_agent.application.agents.retrieval.rag_retrieve_rerank import _clean_terms

DEFAULT_MANIFEST = Path("evaluation/derived_queries/source-query-diversity-v1.json")
MODEL_ID = "qwen3.5:9b"
RRF_CONSTANT = 60
TOP_K_VALUES = (4, 12)
REWRITE_SYSTEM = """You create search hypotheses, not answers or user requirements.
Given only the current user request, produce one concise retrieval query and at most
one materially different alternative. Preserve explicitly named targets, exact titles,
dates, source restrictions, negation, and multiword names. Do not invent aliases or
claim that related documents are the same event. A shorter discovery query is only
a hypothesis; source content must later confirm the target and requested fact.
Return only the supplied JSON object. Use null when no useful alternate exists."""
REWRITE_SCHEMA: dict[str, object] = {
    "type": "object",
    "required": ["rewritten_query", "alternative_query"],
    "properties": {
        "rewritten_query": {"type": "string", "minLength": 1},
        "alternative_query": {"type": ["string", "null"]},
    },
    "additionalProperties": False,
}


def _sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _common_corpus() -> tuple[list[SourceSegment], dict[str, object]]:
    snapshot = json.loads(DEFAULT_PROVIDER_FIXTURE_PATH.read_text(encoding="utf-8"))
    packs = snapshot["resource_packs"]
    raw_resources = [
        resource for pack in packs.values() for resource in pack["resources"]
    ] + snapshot["common_distractors"]["resources"]
    originals: dict[tuple[str, str, str], dict[str, Any]] = {}
    for resource in raw_resources:
        key = (
            str(resource["resource_type"]),
            str(resource["resource_id"]),
            str(resource.get("version") or resource.get("etag") or "1"),
        )
        previous = originals.get(key)
        if previous is not None and previous != resource:
            raise ValueError(f"conflicting snapshot resource version: {key}")
        originals[key] = resource
    resources = _normalize_provider_resources(list(originals.values()))
    summaries = []
    for source, resource_types in (
        ("GMAIL", {"gmail_thread", "gmail_message", "gmail_draft"}),
        ("TASKS", {"task", "task_list"}),
        ("CALENDAR", {"calendar", "calendar_event", "calendar_freebusy"}),
    ):
        current = [
            {
                **resource,
                "resource_handle": f"{resource['resource_type']}:{resource['resource_id']}",
                "connector_id": "google_workspace",
            }
            for resource in resources
            if resource["resource_type"] in resource_types
        ]
        summaries.append({"source": source, "resources": current})
    segments = normalize_segments(
        cast(Any, {"source_summaries": summaries}),
        context_budget=ContextBudget(max_segments=4096),
    )
    if len(segments) != len({segment.segment_id for segment in segments}):
        raise ValueError("common corpus has duplicate segment identities")
    if len(segments) >= 4096:
        raise ValueError("common corpus reached pre-search segment bound")
    summary: dict[str, object] = {
        "provider_snapshot_sha256": hashlib.sha256(
            DEFAULT_PROVIDER_FIXTURE_PATH.read_bytes()
        ).hexdigest(),
        "resource_pack_count": len(packs),
        "raw_resource_count": len(raw_resources),
        "unique_resource_version_count": len(originals),
        "normalized_resource_count": len(resources),
        "segment_count": len(segments),
        "resource_type_counts": dict(Counter(item["resource_type"] for item in resources)),
        "segment_type_counts": dict(Counter(item.resource_type for item in segments)),
        "corpus_fingerprint": _sha256(
            [
                (
                    item.segment_id,
                    item.resource_type,
                    item.resource_id,
                    item.version,
                    _sha256(item.text),
                )
                for item in segments
            ]
        ),
    }
    return segments, summary


def _rewrite(request_text: str) -> dict[str, object]:
    payload = {
        "model": MODEL_ID,
        "stream": False,
        "think": False,
        "format": REWRITE_SCHEMA,
        "options": {"temperature": 0, "seed": 1729},
        "messages": [
            {"role": "system", "content": REWRITE_SYSTEM},
            {"role": "user", "content": request_text},
        ],
    }
    request = Request(
        "http://127.0.0.1:11434/api/chat",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    started = time.perf_counter()
    with urlopen(request, timeout=180) as response:
        result = json.loads(response.read().decode("utf-8"))
    output = json.loads(result["message"]["content"])
    if (
        not isinstance(output, dict)
        or set(output) != {"rewritten_query", "alternative_query"}
        or not isinstance(output["rewritten_query"], str)
        or not output["rewritten_query"].strip()
        or output["alternative_query"] is not None
        and not isinstance(output["alternative_query"], str)
    ):
        raise ValueError("rewrite output schema mismatch")
    return {
        "output": output,
        "input_tokens": result.get("prompt_eval_count"),
        "output_tokens": result.get("eval_count"),
        "provider_latency_ms": round(result.get("total_duration", 0) / 1_000_000, 3),
        "wall_ms": round((time.perf_counter() - started) * 1_000, 3),
    }


def _ranked_items(
    documents: list[Any], scores_by_segment: dict[str, float]
) -> list[dict[str, object]]:
    return [
        {
            "segment_id": document.metadata["segment_id"],
            "resource_type": document.metadata["resource_type"],
            "resource_id": document.metadata["resource_id"],
            "version": document.metadata["version"],
            "bm25_score": scores_by_segment[document.metadata["segment_id"]],
        }
        for document in documents
    ]


def _rrf(rankings: list[list[dict[str, object]]]) -> list[dict[str, object]]:
    scores: dict[str, float] = {}
    items: dict[str, dict[str, object]] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            if cast(float, item["bm25_score"]) <= 0:
                continue
            identity = cast(str, item["segment_id"])
            items[identity] = item
            scores[identity] = scores.get(identity, 0.0) + 1 / (RRF_CONSTANT + rank)
    return [items[identity] for identity in sorted(scores, key=lambda key: (-scores[key], key))]


def _positions(
    ranking: list[dict[str, object]], targets: list[str], k: int
) -> dict[str, int | None]:
    return {
        target: next(
            (
                index
                for index, item in enumerate(ranking[:k], 1)
                if item["resource_id"] == target and cast(float, item["bm25_score"]) > 0
            ),
            None,
        )
        for target in targets
    }


def evaluate(
    manifest_path: Path,
    result_path: Path,
    *,
    preflight_only: bool,
    baseline_only: bool = False,
) -> dict[str, object]:
    if preflight_only and baseline_only:
        raise ValueError("preflight-only and baseline-only are mutually exclusive")
    from langchain_community.retrievers.bm25 import BM25Retriever
    from langchain_core.documents import Document

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    variants = manifest["cases"]
    cases = load_cases()
    if len(variants) != 24 or Counter(item["variant"] for item in variants) != {
        "A": 6,
        "B": 6,
        "C": 6,
        "D": 6,
    }:
        raise ValueError("expected six complete A/B/C/D request families")
    for item in variants:
        if (
            item["variant"] == "A"
            and item["request"] != cases[item["origin_case_id"]].raw["canonical_user_prompt"]
        ):
            raise ValueError("derived A differs from original request")
    segments, corpus = _common_corpus()
    available = {segment.resource_id for segment in segments}
    for item in variants:
        if not set(item.get("rank_target_resource_ids", [])) <= available:
            raise ValueError("target resource absent from common corpus")
    documents = [
        Document(
            page_content=segment.text,
            metadata={
                "segment_id": segment.segment_id,
                "resource_type": segment.resource_type,
                "resource_id": segment.resource_id,
                "version": segment.version,
                "source": segment.source,
            },
        )
        for segment in segments
    ]
    retriever = BM25Retriever.from_documents(
        documents,
        preprocess_func=_clean_terms,
        bm25_params={"k1": 1.2, "b": 0.75, "epsilon": 0.25},
        k=max(TOP_K_VALUES),
    )
    # Call the same public API before any LLM dispatch or scored trial.
    if len(retriever.invoke("fixture preflight")) != min(len(documents), max(TOP_K_VALUES)):
        raise ValueError("BM25Retriever.invoke preflight returned an unexpected count")
    result: dict[str, object] = {
        "binding": {
            "baseline_sha": "f40cc1ff54a392314c2a5e0a15224a484eff4435",
            "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
            "corpus": corpus,
            "execution_scope": "COMMON_FIXTURE_CORPUS_IN_MEMORY_NOT_PROVIDER_READ",
            "langchain_community_version": version("langchain-community"),
            "langchain_core_version": version("langchain-core"),
            "rank_bm25_version": version("rank-bm25"),
            "numpy_version": version("numpy"),
            "preprocessing": "rag_retrieve_rerank._clean_terms",
            "bm25_params": {"k1": 1.2, "b": 0.75, "epsilon": 0.25},
            "top_k_values": TOP_K_VALUES,
            "fusion": {"kind": "RRF", "constant": RRF_CONSTANT},
            "rewrite_model": MODEL_ID,
            "rewrite_prompt_sha256": hashlib.sha256(REWRITE_SYSTEM.encode()).hexdigest(),
            "sampling_temperature": 0,
            "sampling_seed": 1729,
            "provider_read_count": 0,
            "provider_write_count": 0,
        },
        "cases": [
            {
                "origin_case_id": item["origin_case_id"],
                "variant": item["variant"],
                "difficulty": item["difficulty"],
                "request_sha256": hashlib.sha256(item["request"].encode()).hexdigest(),
                "targets": item.get("rank_target_resource_ids", []),
                "verification_rule": item.get("verification_rule"),
                "status": "PENDING",
            }
            for item in variants
        ],
    }
    _write(result_path, result)
    if preflight_only:
        return result

    cached_queries: dict[str, list[dict[str, object]]] = {}

    def query(text: str) -> tuple[list[dict[str, object]], bool, float]:
        normalized = text.strip()
        if normalized in cached_queries:
            return cached_queries[normalized], True, 0.0
        started = time.perf_counter()
        retrieved = retriever.invoke(normalized)
        scores = retriever.vectorizer.get_scores(_clean_terms(normalized))
        scores_by_segment = {
            document.metadata["segment_id"]: float(score)
            for document, score in zip(retriever.docs, scores, strict=True)
        }
        ranked = _ranked_items(retrieved, scores_by_segment)
        elapsed = round((time.perf_counter() - started) * 1_000, 3)
        cached_queries[normalized] = ranked
        return ranked, False, elapsed

    for record, item in zip(cast(list[dict[str, object]], result["cases"]), variants, strict=True):
        rewrite_started: float | None = None
        try:
            original, reused, elapsed = query(item["request"])
            record["A"] = {
                "query": item["request"],
                "ranked": original,
                "cache_reused": reused,
                "search_ms": elapsed,
            }
            targets = cast(list[str], record["targets"])
            record["target_positions"] = {
                "A": {str(k): _positions(original, targets, k) for k in TOP_K_VALUES}
            }
            record["status"] = "A_COMPLETE"
            _write(result_path, result)
            if baseline_only:
                print(
                    json.dumps(
                        {
                            "case": item["origin_case_id"],
                            "variant": item["variant"],
                            "status": record["status"],
                        }
                    ),
                    flush=True,
                )
                continue
            rewrite_started = time.perf_counter()
            record["rewrite_dispatch_count"] = 1
            rewrite = _rewrite(item["request"])
            record["rewrite_attempt_wall_ms"] = round(
                (time.perf_counter() - rewrite_started) * 1_000, 3
            )
            record["rewrite"] = rewrite
            proposed = cast(dict[str, object], rewrite["output"])
            rewritten = cast(str, proposed["rewritten_query"]).strip()
            alternative = proposed["alternative_query"]
            alternative = alternative.strip() if isinstance(alternative, str) else None
            b_rank, reused, elapsed = query(rewritten)
            record["B"] = {
                "query": rewritten,
                "ranked": b_rank,
                "cache_reused": reused,
                "search_ms": elapsed,
            }
            hypotheses = list(dict.fromkeys([item["request"].strip(), rewritten, alternative]))
            hypotheses = [value for value in hypotheses if isinstance(value, str) and value]
            rankings = [query(value)[0] for value in hypotheses]
            merged = _rrf(rankings)
            record["C"] = {"queries": hypotheses, "ranked": merged[: max(TOP_K_VALUES)]}
            record["status"] = "COMPLETE"
            record["target_positions"] = {
                arm: {
                    str(k): _positions(
                        cast(
                            list[dict[str, object]], cast(dict[str, object], record[arm])["ranked"]
                        ),
                        targets,
                        k,
                    )
                    for k in TOP_K_VALUES
                }
                for arm in ("A", "B", "C")
            }
        except Exception as error:
            record["status"] = "FAILED"
            record["error_type"] = type(error).__name__
            if rewrite_started is not None:
                record["rewrite_attempt_wall_ms"] = round(
                    (time.perf_counter() - rewrite_started) * 1_000, 3
                )
                record["rewrite_token_usage"] = "unavailable_on_failed_call"
        _write(result_path, result)
        print(
            json.dumps(
                {
                    "case": item["origin_case_id"],
                    "variant": item["variant"],
                    "status": record["status"],
                }
            ),
            flush=True,
        )
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--baseline-only", action="store_true")
    args = parser.parse_args()
    output = evaluate(
        args.manifest,
        args.result,
        preflight_only=args.preflight_only,
        baseline_only=args.baseline_only,
    )
    print(
        json.dumps(
            {
                "case_count": len(output["cases"]),
                "preflight": args.preflight_only,
                "baseline_only": args.baseline_only,
            }
        )
    )
