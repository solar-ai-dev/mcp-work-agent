"""Compare one restored user-authority contract in the narrow Review Goal probe."""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
import time
from copy import deepcopy
from pathlib import Path
from typing import Any, cast

from scripts.evaluate_review_decomposition_node import (
    GOAL_SOURCE,
    MODEL_ID,
    PROMPT_ID,
    _bundle,
    _goal_input,
    _runtime,
)

from google_work_agent.adapters.llm.ollama.transport import OllamaHTTPClient
from google_work_agent.application.agents.review.contracts.review_findings import (
    review_inspector_output_schema,
    validate_review_inspector_result,
)
from google_work_agent.application.prompt_runtime.prompt_registry import (
    DEVELOPMENT_SMOKE,
    load_prompt_reference,
)
from google_work_agent.application.use_cases.run.account_provider_dispatch import (
    provider_dispatch_budget_scope,
    provider_dispatch_execution_scope,
)
from google_work_agent.application.use_cases.run.guard_run_budget import build_default_run_budget

AUTHORITY_SOURCE = GOAL_SOURCE + """
# 현재 사용자 권위
검증된 user_action_modifications의 정확한 argument_overrides path/value는
현재 사용자가 Preview에서 직접 수정한 값이다. 그 path의 옛 요청값을
다시 강제하지 않는다. 수정하지 않은 다른 path의 요청 제약은 유지한다.
이미 제공한 값·선택한 대상·현재 기준시각으로 검증된 계산 결과는 다시
묻지 않는다. 제안이 명시된 금지 조건을 위반하면 선택 질문이 아니라
제안 자체의 ISSUE다. CONFIRMATION은 현재 입력으로 실제로 결정되지 않은
사용자 선택에만 사용한다.
"""


def _tasks(source: dict[str, object]) -> list[tuple[str, str, dict[str, object], int]]:
    cases = {item["label"]: item for item in cast(list[dict[str, object]], source["cases"])}
    rows: list[tuple[str, str, dict[str, object], int]] = []
    for label in (
        "CASE-CORE-023",
        "CASE-CORE-028",
        "WRONG_ACTION_DATE",
        "FORBIDDEN_ATTENDEE",
    ):
        item = cases[label]
        started_at_ms = cast(int, item["started_at_ms"])
        rows.append(
            (
                label,
                "D",
                _goal_input(cast(dict[str, object], item["baseline_input"]), started_at_ms),
                started_at_ms,
            )
        )
    edit_item = cases["USER_PREVIEW_EDIT"]
    edited = deepcopy(cast(dict[str, object], edit_item["baseline_input"]))
    title = "Kestrel 공급 지연 점검"
    edited["planning_result"]["actions"][0]["arguments"]["payload"]["title"] = title
    edited["user_action_modifications"][0]["argument_overrides"]["payload.title"] = title
    started_at_ms = cast(int, edit_item["started_at_ms"])
    for arm in ("A", "D"):
        rows.append(
            (
                "USER_PREVIEW_EDIT_CLEAR",
                arm,
                _goal_input(edited, started_at_ms),
                started_at_ms,
            )
        )
    if len(rows) != 6:
        raise ValueError("predeclared call count changed")
    return rows


def evaluate(source_path: Path, output_path: Path) -> dict[str, object]:
    source = json.loads(source_path.read_text(encoding="utf-8"))
    installed = {
        item.model_id: item.digest for item in OllamaHTTPClient().list_installed_models()
    }
    if installed.get(MODEL_ID) != source["binding"]["model_digest"]:
        raise ValueError("installed model digest differs from fixed comparison model")
    root = Path(tempfile.mkdtemp(prefix="gwa-review-goal-authority-"))
    arms: dict[str, tuple[Any, object]] = {}
    for arm, text in (("A", GOAL_SOURCE), ("D", AUTHORITY_SOURCE)):
        manifest = _bundle(root / f"{arm.lower()}-bundle", text)
        runtime = _runtime(root / arm.lower(), manifest)
        reference = load_prompt_reference(
            PROMPT_ID, manifest, execution_scope=DEVELOPMENT_SMOKE
        )
        arms[arm] = (runtime, reference)
    result: dict[str, object] = {
        "binding": {
            "source_sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
            "baseline_sha": "2523f699",
            "model_id": MODEL_ID,
            "model_digest": installed[MODEL_ID],
            "sampling_temperature": 0.0,
            "sampling_seed": 1729,
            "a_prompt_sha256": arms["A"][1].content_hash,
            "d_prompt_sha256": arms["D"][1].content_hash,
            "new_call_limit": 6,
            "provider_read_enabled": False,
            "provider_write_enabled": False,
        },
        "trials": [],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    schema = review_inspector_output_schema(PROMPT_ID)
    for label, arm, prompt_input, started_at_ms in _tasks(source):
        runtime, reference = arms[arm]
        started = time.perf_counter()
        trial: dict[str, object] = {
            "label": label,
            "arm": arm,
            "input_sha256": hashlib.sha256(
                json.dumps(prompt_input, ensure_ascii=False, sort_keys=True).encode("utf-8")
            ).hexdigest(),
            "prompt_input": prompt_input,
        }
        try:
            with (
                provider_dispatch_execution_scope(
                    run_id=f"review-goal-authority-{label}-{arm}",
                    now_ms=lambda started_at_ms=started_at_ms, started=started: (
                        started_at_ms + int((time.perf_counter() - started) * 1_000)
                    ),
                ),
                provider_dispatch_budget_scope(
                    build_default_run_budget(started_at_ms=started_at_ms)
                ),
            ):
                inference = runtime.infer("LOCAL_GPU", reference, prompt_input, schema)
            validated = validate_review_inspector_result(
                inference.structured_output, expected_dimension=PROMPT_ID
            )
            trial.update(
                {
                    "outcome": "COMPLETED",
                    "structured_output": validated,
                    "input_tokens": inference.input_tokens,
                    "output_tokens": inference.output_tokens,
                    "provider_latency_ms": inference.latency_ms,
                }
            )
        except Exception as error:
            code = getattr(error, "code", None)
            trial.update(
                {
                    "outcome": "FAILED",
                    "error_type": type(error).__name__,
                    "error_code": getattr(code, "value", None),
                }
            )
        trial["duration_ms"] = int((time.perf_counter() - started) * 1_000)
        cast(list[dict[str, object]], result["trials"]).append(trial)
        output_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(label, arm, trial["outcome"], trial["duration_ms"], flush=True)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    evaluate(args.input, args.output)


if __name__ == "__main__":
    main()
