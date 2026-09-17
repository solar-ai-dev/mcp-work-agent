"""Probe a Query-owner typed lexical role output without product activation."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path
from urllib.request import Request, urlopen

from scripts.evaluate_direct_bm25_search import DEFAULT_MANIFEST, MODEL_ID, _write

INPUTS = (
    ("CASE-CORE-007", "A"),
    ("CASE-CORE-007", "B"),
    ("CASE-CORE-008", "A"),
    ("CASE-CORE-010", "A"),
    ("CASE-CORE-010", "B"),
    ("CASE-CORE-023", "A"),
    ("CASE-CORE-007", "D"),
    ("CASE-CORE-006", "D"),
)
SYSTEM = """You are identifying lexical roles for one provider search plan, not answering.
Use only the current user request. Return exact_terms: exact named targets or
explicit titles the user requires to distinguish, preserving complete multiword
names. Return exploratory_terms: descriptions of the material or business topic
that may be rephrased during discovery. A term may be omitted when uncertain.
Do not treat a whole request clause as an exact name. Do not invent aliases,
resources, facts, dates, or user corrections. Do not discard an explicit year
from the request's meaning; this output only classifies lexical terms and is not
the sole representation of time. Every returned term must appear in the request.
Return only the required JSON."""
SCHEMA: dict[str, object] = {
    "type": "object",
    "required": ["exact_terms", "exploratory_terms"],
    "properties": {
        "exact_terms": {"type": "array", "items": {"type": "string"}},
        "exploratory_terms": {"type": "array", "items": {"type": "string"}},
    },
    "additionalProperties": False,
}


def _validation_errors(output: object, request_text: str) -> list[str]:
    if not isinstance(output, dict) or set(output) != {"exact_terms", "exploratory_terms"}:
        return ["lexical role schema mismatch"]
    errors: list[str] = []
    for role, values in output.items():
        if not isinstance(values, list):
            errors.append(f"{role} is not a list")
            continue
        for value in values:
            if not isinstance(value, str) or not value.strip() or value not in request_text:
                errors.append(f"{role} contains a non-current-request span")
    return errors


def _infer(request_text: str) -> dict[str, object]:
    payload = {
        "model": MODEL_ID,
        "stream": False,
        "think": False,
        "format": SCHEMA,
        "options": {"temperature": 0, "seed": 1729},
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": request_text},
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
    raw_output = result["message"]["content"]
    try:
        output = json.loads(raw_output)
    except json.JSONDecodeError:
        output = raw_output
    return {
        "output": output,
        "validation_errors": _validation_errors(output, request_text),
        "input_tokens": result.get("prompt_eval_count"),
        "output_tokens": result.get("eval_count"),
        "provider_latency_ms": round(result.get("total_duration", 0) / 1_000_000, 3),
        "wall_ms": round((time.perf_counter() - started) * 1_000, 3),
    }


def evaluate(result_path: Path) -> dict[str, object]:
    manifest = json.loads(DEFAULT_MANIFEST.read_text(encoding="utf-8"))
    items = {(item["origin_case_id"], item["variant"]): item for item in manifest["cases"]}
    if any(key not in items for key in INPUTS):
        raise ValueError("lexical role input missing from fixed manifest")
    result: dict[str, object] = {
        "binding": {
            "baseline_sha": "925f5b19b1253df87aad2688c8c7d1190ad41c85",
            "manifest_sha256": hashlib.sha256(DEFAULT_MANIFEST.read_bytes()).hexdigest(),
            "model": MODEL_ID,
            "prompt_sha256": hashlib.sha256(SYSTEM.encode()).hexdigest(),
            "temperature": 0,
            "seed": 1729,
            "scope": "EVALUATION_ONLY_EXTRA_CALL_NOT_PRODUCT",
        },
        "cases": [],
    }
    _write(result_path, result)
    for case_id, variant in INPUTS:
        item = items[(case_id, variant)]
        record: dict[str, object] = {
            "case_id": case_id,
            "variant": variant,
            "request_sha256": hashlib.sha256(item["request"].encode()).hexdigest(),
            "model_dispatch_count": 1,
        }
        result["cases"].append(record)
        _write(result_path, result)
        started = time.perf_counter()
        try:
            record["inference"] = _infer(item["request"])
            record["status"] = (
                "COMPLETE" if not record["inference"]["validation_errors"] else "INVALID"
            )
        except Exception as error:
            record["status"] = "FAILED"
            record["error_type"] = type(error).__name__
            record["token_usage"] = "unavailable_on_failed_call"
        record["attempt_wall_ms"] = round((time.perf_counter() - started) * 1_000, 3)
        _write(result_path, result)
        print(json.dumps({"case": case_id, "variant": variant, "status": record["status"]}))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--result", type=Path, required=True)
    args = parser.parse_args()
    evaluate(args.result)
