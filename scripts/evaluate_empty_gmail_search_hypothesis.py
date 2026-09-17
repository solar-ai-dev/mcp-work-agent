"""Diagnose one bounded discovery hypothesis after an observed empty Gmail search."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path
from urllib.request import Request, urlopen

from evaluation.dataset_v8 import DEFAULT_PROVIDER_FIXTURE_PATH
from evaluation.harness.gmail_query import compile_gmail_query
from scripts.evaluate_direct_bm25_search import DEFAULT_MANIFEST, MODEL_ID, _write

CASES = (
    ("CASE-CORE-007", "B", "retrieval-B007.json", "ACTUAL_EMPTY"),
    ("CASE-CORE-008", "A", "retrieval-A008.json", "ACTUAL_EMPTY"),
    ("CASE-CORE-007", "D", None, "SYNTHETIC_OVER_NARROW"),
    ("CASE-CORE-006", "D", None, "SYNTHETIC_OVER_NARROW"),
)
SYSTEM = """You propose at most one search hypothesis after a Gmail search returned zero.
The previous search string was too narrow OR the requested material may not exist.
Return a conservative replacement discovery literal, not an answer or confirmed fact.
Keep exact user-named entities including multiword names and any explicit year/date.
Drop only descriptive words that need not occur verbatim in a source document.
Do not invent aliases, change the requested entity, or assert that a result is relevant.
If safe broadening cannot be determined from the request, return null.
Return only the required JSON."""
SCHEMA: dict[str, object] = {
    "type": "object",
    "required": ["replacement_keyword"],
    "properties": {"replacement_keyword": {"type": ["string", "null"]}},
    "additionalProperties": False,
}


def _resources() -> tuple[list[dict[str, object]], str]:
    raw = DEFAULT_PROVIDER_FIXTURE_PATH.read_bytes()
    snapshot = json.loads(raw)
    originals: dict[tuple[str, str, str], dict[str, object]] = {}
    all_resources = [
        resource for pack in snapshot["resource_packs"].values() for resource in pack["resources"]
    ] + snapshot["common_distractors"]["resources"]
    for resource in all_resources:
        key = (
            str(resource["resource_type"]),
            str(resource["resource_id"]),
            str(resource.get("version") or resource.get("etag") or "1"),
        )
        if key in originals and originals[key] != resource:
            raise ValueError(f"conflicting resource version: {key}")
        originals[key] = resource
    return (
        [r for r in originals.values() if r["resource_type"] == "gmail_thread"],
        hashlib.sha256(raw).hexdigest(),
    )


def _model(request_text: str, failed_query: str) -> dict[str, object]:
    payload = {
        "model": MODEL_ID,
        "stream": False,
        "think": False,
        "format": SCHEMA,
        "options": {"temperature": 0, "seed": 1729},
        "messages": [
            {"role": "system", "content": SYSTEM},
            {
                "role": "user",
                "content": json.dumps(
                    {"current_request": request_text, "empty_query": failed_query},
                    ensure_ascii=False,
                ),
            },
        ],
    }
    request = Request(
        "http://127.0.0.1:11434/api/chat",
        data=json.dumps(payload, ensure_ascii=False).encode(),
        method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    started = time.perf_counter()
    with urlopen(request, timeout=180) as response:
        result = json.loads(response.read().decode())
    output = json.loads(result["message"]["content"])
    if not isinstance(output, dict) or set(output) != {"replacement_keyword"}:
        raise ValueError("replacement output schema mismatch")
    value = output["replacement_keyword"]
    if value is not None and (not isinstance(value, str) or not value.strip()):
        raise ValueError("replacement keyword must be nonempty or null")
    return {
        "replacement_keyword": value.strip() if isinstance(value, str) else None,
        "input_tokens": result.get("prompt_eval_count"),
        "output_tokens": result.get("eval_count"),
        "provider_latency_ms": round(result.get("total_duration", 0) / 1_000_000, 3),
        "wall_ms": round((time.perf_counter() - started) * 1_000, 3),
    }


def _quoted_query(keyword: str) -> str:
    literal = keyword.strip()
    if literal.startswith('"') and literal.endswith('"'):
        literal = literal[1:-1].strip()
    if not literal or len(literal) > 200 or any(char in literal for char in '\r\n"\\'):
        raise ValueError("unsafe Gmail keyword literal")
    return '"' + literal + '"'


def evaluate(
    result_path: Path,
    saved_root: Path,
    *,
    preflight_only: bool = False,
    proposals_from: Path | None = None,
) -> dict[str, object]:
    manifest = json.loads(DEFAULT_MANIFEST.read_text(encoding="utf-8"))
    items = {(item["origin_case_id"], item["variant"]): item for item in manifest["cases"]}
    threads, snapshot_hash = _resources()
    output: dict[str, object] = {
        "binding": {
            "baseline_sha": "f40cc1ff54a392314c2a5e0a15224a484eff4435",
            "snapshot_sha256": snapshot_hash,
            "manifest_sha256": hashlib.sha256(DEFAULT_MANIFEST.read_bytes()).hexdigest(),
            "model": MODEL_ID,
            "prompt_sha256": hashlib.sha256(SYSTEM.encode()).hexdigest(),
            "temperature": 0,
            "seed": 1729,
            "gmail_thread_count": len(threads),
            "scope": "COMMON_SYNTHETIC_GMAIL_CORPUS_NOT_PROVIDER_READ",
        },
        "cases": [],
    }
    prior_records = None
    if proposals_from is not None:
        prior = json.loads(proposals_from.read_text(encoding="utf-8"))
        if prior["binding"]["snapshot_sha256"] != snapshot_hash:
            raise ValueError("proposal replay corpus fingerprint changed")
        if prior["binding"]["manifest_sha256"] != output["binding"]["manifest_sha256"]:
            raise ValueError("proposal replay request manifest changed")
        prior_records = {
            (record["case_id"], record["variant"]): record for record in prior["cases"]
        }
        output["binding"]["proposal_replay_sha256"] = hashlib.sha256(
            proposals_from.read_bytes()
        ).hexdigest()
    _write(result_path, output)
    for case_id, variant, saved_name, provenance in CASES:
        item = items[(case_id, variant)]
        if saved_name is None:
            failed_query = '"' + item["request"] + '"'
        else:
            saved = json.loads((saved_root / saved_name).read_text(encoding="utf-8"))
            attempts = saved["cases"][0]["query_attempts"]
            if len(attempts) != 1 or attempts[0]["candidate_count"] != 0:
                raise ValueError("saved input is not a single observed empty search")
            failed_query = attempts[0]["query_spec"]["canonical_arguments"]["query"]
        initial_hits = [
            str(r["resource_id"]) for r in threads if compile_gmail_query(failed_query)(r)
        ]
        if initial_hits:
            raise ValueError("prior query is not empty in the common corpus")
        record: dict[str, object] = {
            "case_id": case_id,
            "variant": variant,
            "provenance": provenance,
            "request_sha256": hashlib.sha256(item["request"].encode()).hexdigest(),
            "failed_query": failed_query,
            "initial_hit_ids": initial_hits,
            "target_ids": item.get("rank_target_resource_ids", []),
            "model_dispatch_count": 0,
        }
        output["cases"].append(record)
        _write(result_path, output)
    if preflight_only:
        return output
    for record in output["cases"]:
        item = items[(record["case_id"], record["variant"])]
        started = time.perf_counter()
        try:
            if prior_records is None:
                record["model_dispatch_count"] = 1
                proposal = _model(item["request"], record["failed_query"])
            else:
                source = prior_records[(record["case_id"], record["variant"])]
                if source["request_sha256"] != record["request_sha256"]:
                    raise ValueError("proposal replay request changed")
                proposal = source["proposal"]
            record["proposal"] = proposal
            keyword = proposal["replacement_keyword"]
            if keyword is not None:
                replacement_query = _quoted_query(keyword)
                record["replacement_query"] = replacement_query
                record["replacement_hit_ids"] = [
                    str(r["resource_id"])
                    for r in threads
                    if compile_gmail_query(replacement_query)(r)
                ]
            record["status"] = "COMPLETE"
        except Exception as error:
            record["status"] = "FAILED"
            record["error_type"] = type(error).__name__
            record["token_usage"] = "unavailable_on_failed_call"
        record["attempt_wall_ms"] = round((time.perf_counter() - started) * 1_000, 3)
        _write(result_path, output)
        print(
            json.dumps(
                {
                    "case": record["case_id"],
                    "variant": record["variant"],
                    "status": record["status"],
                }
            )
        )
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument(
        "--saved-root",
        type=Path,
        default=Path("evaluation/results/ru-search-term-role-20260917"),
    )
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--proposals-from", type=Path)
    args = parser.parse_args()
    evaluate(
        args.result,
        args.saved_root,
        preflight_only=args.preflight_only,
        proposals_from=args.proposals_from,
    )
