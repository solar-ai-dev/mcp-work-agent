"""088 runner guard/observation tests; no hardware probe or model/Provider I/O."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
from types import SimpleNamespace
from typing import Any

import pytest
from scripts import evaluate_registered_answer_choice as runner
from scripts import task_field_scope_diagnostic as fixture

from google_work_agent.ports.llm.structured_inference_contracts import RuntimePolicy


def test_validate_plan__stored_http_property_order_changes__rejects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload: dict[str, Any] = {"format": {"properties": {"mode": {}, "answer": {}}}}
    original: dict[str, Any] = {
        "model": {},
        "cases": [
            {
                "expected_first": {
                    "payload": payload,
                    "transport_sha256": runner.transport_hash(payload),
                }
            }
        ],
    }
    monkeypatch.setattr(runner, "make_plan", lambda _model: deepcopy(original))
    changed = deepcopy(original)
    changed["cases"][0]["expected_first"]["payload"]["format"]["properties"] = {
        "answer": {},
        "mode": {},
    }
    assert changed == original  # Python mapping equality cannot protect wire ordering.
    with pytest.raises(ValueError, match="byte/order"):
        runner.validate_plan(changed)


def test_boundary_observations__failed_read_and_denied_write__preserves_attempts() -> None:
    boundary = SimpleNamespace(
        events=[
            {"boundary": "local_hardware_probe"},
            {"boundary": "snapshot_read"},
            {"boundary": "provider_write_dispatch", "decision": "DENY"},
        ],
        read_results=[{"tool_id": "tasks_get_task", "error_type": "TimeoutError"}],
    )
    result = runner._boundary_observations(boundary)
    assert result["counts"] == {
        "snapshot_read_attempts": 1,
        "snapshot_read_returned": 0,
        "provider_write_attempts_denied": 1,
        "all_boundary_denials": 1,
    }
    boundary.events.clear()
    assert len(result["events"]) == 3
    assert result["read_results"][0]["error_type"] == "TimeoutError"


def test_boundary_observations__runtime_never_exposed_boundary__does_not_claim_zero() -> None:
    result = runner._boundary_observations(None)
    assert result["observed"] is False
    assert result["counts"] is None


def test_observation_guard__four_attempts_recorded__rejects_fifth_before_leaf() -> None:
    owner = runner._Observation({}, started=runner.time.monotonic(), save=lambda: None, fake=True)
    owner.calls = [{} for _ in range(4)]
    with pytest.raises(RuntimeError, match="DISPATCH_CAP"):
        owner._guard()


def test_wire_observer__transport_raises__preserves_started_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {"model": runner.MODEL_ID, "prompt": "unused fake diagnostic payload"}
    case = {"expected_first": {"transport_sha256": runner.transport_hash(payload)}}
    writes: list[dict[str, Any] | None] = []
    owner: runner._Observation = runner._Observation(
        case,
        started=runner.time.monotonic(),
        save=lambda: writes.append(deepcopy(owner.active)),
        fake=False,
    )
    event: dict[str, Any] = {"phase": "FIRST", "wire_request_count": 0}
    owner.active = event

    def fail(**_kwargs: Any) -> Any:
        raise TimeoutError("synthetic transport failure")

    monkeypatch.setattr(runner.transport, "_post_json", fail)
    with owner.wire(), pytest.raises(TimeoutError, match="synthetic"):
        runner.transport._post_json(
            endpoint="http://127.0.0.1:11434",
            path="/api/generate",
            payload=payload,
            timeout_seconds=180,
        )
    assert len(writes) == 1
    assert event["wire_request_count"] == 1
    assert event["payload"] == payload
    assert "provider_response_metadata" not in event


def test_fake_wire__prose_shape__keeps_version_and_reports_no_usage() -> None:
    payload = {"model": runner.MODEL_ID, "prompt": "unused fake diagnostic payload"}
    owner = runner._Observation(
        {
            "expected_first": {"transport_sha256": runner.transport_hash(payload)},
            "prompt_input": {"answer_outline": {"evidence_refs": ["evidence-1"]}},
        },
        started=runner.time.monotonic(),
        save=lambda: None,
        fake=True,
    )
    owner.active = {
        "phase": "FIRST",
        "wire_request_count": 0,
        "prompt_ref": {"prompt_id": runner.EVALUATION_SLOT},
    }
    with owner.wire():
        response = runner.transport._post_json(
            endpoint="http://127.0.0.1:11434",
            path="/api/generate",
            payload=payload,
            timeout_seconds=180,
        )
    assert runner.json.loads(str(response["response"])) == {
        "mode": "PROSE",
        "schema_version": 2,
        "answer": "모델 없는 연결 검증용 응답입니다.",
        "evidence_refs": ["evidence-1"],
    }
    assert "prompt_eval_count" not in response
    assert owner.active["provider_response_metadata"]["done_reason"] == "stop"


@pytest.fixture
def product_case() -> dict[str, Any]:
    return fixture.build_cases()[0]


def test_expected_first__product_mode__preserves_native_wire_without_candidate(
    monkeypatch: pytest.MonkeyPatch,
    product_case: dict[str, Any],
) -> None:
    from scripts import answer_fact_selection_candidate

    def forbidden(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("094 must not inspect or activate the fact-choice candidate")

    monkeypatch.setattr(answer_fact_selection_candidate, "bind_fact_selection_schema", forbidden)
    monkeypatch.setattr(runner, "_EvaluationRegistry", forbidden)
    before = deepcopy(product_case)
    expected = runner.expected_first(
        product_case["prompt_input"],
        product_case["snapshots"],
        planning_mode=runner.PRODUCT_TASK_FIELD_SCOPE,
    )
    native = runner.handoff._wire_projection(product_case["prompt_input"])
    assert expected["payload"] == native["wire_payload"]
    assert expected["transport_sha256"] == runner.transport_hash(native["wire_payload"])
    assert expected["prompt_ref"] == native["prompt_ref"]
    assert expected["prompt_ref"]["prompt_id"] == "planning.compose_answer"
    assert expected["has_fact_catalog"] is None
    assert expected["payload"]["options"] == {"num_ctx": 16384, "seed": 20260923}
    assert product_case == before


def test_make_plan__product_mode__seals_two_fixed_firsts_without_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runner.handoff, "_bound_files", lambda: {})
    monkeypatch.setattr(runner, "file_hash", lambda _path: "sealed-file")
    monkeypatch.setattr(runner, "head", lambda: "sealed-head")
    model = {"model_id": runner.MODEL_ID, "model_digest": "fixed-digest"}
    plan = runner.make_plan(model, planning_mode=runner.PRODUCT_TASK_FIELD_SCOPE)
    assert plan["kind"] == "094_PRODUCT_COMPILED_PLANNING"
    assert [(c["case_id"], c["trial"]) for c in plan["cases"]] == [
        (f"{group}-T1", 1) for group in runner.TASK_FIELD_GROUPS
    ]
    assert plan["policy"]["total_actual_dispatch_cap"] == 2
    assert plan["policy"]["per_trial_actual_dispatch_cap"] == 1
    assert plan["policy"]["answer_choice_overlay"] is False
    assert plan["history_hashes"] == {}
    assert "scripts/task_field_scope_diagnostic.py" in plan["source_hashes"]
    assert "scripts/serve_canonical_v8_product.py" in plan["source_hashes"]
    assert "evaluation/datasets/e2e/canonical_cases_v8.jsonl" in plan["source_hashes"]
    assert "evaluation/datasets/e2e/dataset-manifest-v8.json" in plan["source_hashes"]
    assert (
        "evaluation/datasets/e2e/fixtures/google_workspace/provider-snapshot-v8.json"
        in plan["source_hashes"]
    )
    assert runner.TASK_FIELD_CRITERIA in plan["source_hashes"]
    runner.validate_plan(plan)
    changed = deepcopy(plan)
    changed["cases"].reverse()
    with pytest.raises(ValueError, match="changed"):
        runner.validate_plan(changed)
    changed = deepcopy(plan)
    changed["policy"]["per_trial_actual_dispatch_cap"] = 2
    with pytest.raises(ValueError, match="changed"):
        runner.validate_plan(changed)


@pytest.mark.parametrize("mutation", ["extra_case", "repeated_trial", "binding"])
def test_make_plan__changed_fixed_fixture__rejects(
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    cases = fixture.build_cases()
    if mutation == "extra_case":
        cases.append(deepcopy(cases[0]))
    elif mutation == "repeated_trial":
        cases[0]["trial"] = 2
    else:
        cases[0]["input_binding_sha256"] = "changed"
    monkeypatch.setattr(fixture, "build_cases", lambda: cases)
    with pytest.raises(ValueError, match="094"):
        runner.make_plan(
            {"model_id": runner.MODEL_ID, "model_digest": "fixed-digest"},
            planning_mode=runner.PRODUCT_TASK_FIELD_SCOPE,
        )


@pytest.mark.parametrize("planning_mode", runner.PLANNING_MODES)
def test_planning_subgraph__closed_mode__uses_exact_registered_owner(
    monkeypatch: pytest.MonkeyPatch,
    planning_mode: str,
) -> None:
    if planning_mode == runner.PRODUCT_TASK_FIELD_SCOPE:

        def forbidden(**_kwargs: Any) -> Any:
            raise AssertionError("Product path may not construct the inactive subclass")

        monkeypatch.setattr(runner, "AnswerChoicePlanningSubgraph", forbidden)
    graph = runner._planning_subgraph(
        planning_mode=planning_mode,
        runtime=SimpleNamespace(prompt_manifest_path=None),
        store=runner._ObservedStore(),
        graph_profile=runner.GraphProfile.SIX_ROLE_BASELINE,
        merge=None,
        observations=[],
    )
    expected_type = (
        runner.PlanningSubgraph
        if planning_mode == runner.PRODUCT_TASK_FIELD_SCOPE
        else runner.AnswerChoicePlanningSubgraph
    )
    assert type(graph) is expected_type
    assert graph._prompt_refs["planning.compose_answer"].prompt_id == "planning.compose_answer"


def test_product_observer__second_inference_attempt__blocks_before_raw_leaf(
    monkeypatch: pytest.MonkeyPatch,
    product_case: dict[str, Any],
) -> None:
    def forbidden(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("Product observer cannot decorate with answer-choice")

    monkeypatch.setattr(runner, "decorate_answer_choice_provider", forbidden)
    arguments = runner.handoff._call_arguments(product_case["prompt_input"])
    product_case["expected_first"] = {"prompt_ref": asdict(arguments["prompt_ref"])}
    received: list[dict[str, Any]] = []

    def invoke(**kwargs: Any) -> Any:
        received.append(kwargs)
        return SimpleNamespace(
            content="{}",
            input_tokens=2,
            output_tokens=1,
            latency_ms=1,
            model=runner.MODEL_ID,
        )

    leaf = SimpleNamespace(
        provider_name="ollama",
        runtime="LOCAL_GPU",
        model_id=runner.MODEL_ID,
        invoke_structured=invoke,
    )
    owner = runner._Observation(
        product_case,
        started=runner.time.monotonic(),
        save=lambda: None,
        fake=False,
        planning_mode=runner.PRODUCT_TASK_FIELD_SCOPE,
    )
    observed = owner.decorate(leaf)
    kwargs = {**arguments, "runtime_policy": RuntimePolicy(sampling_seed=runner.SEED)}
    observed.invoke_structured(**kwargs)
    with pytest.raises(RuntimeError, match="DISPATCH_CAP"):
        observed.invoke_structured(**kwargs)
    assert len(received) == len(owner.calls) == 1
    assert received[0]["runtime_policy"].structured_output_repair_budget == 1
    assert owner.blocked_dispatches == ["EXPERIMENT_TRIAL_DISPATCH_CAP"]
    assert owner.calls[0]["content"] == "{}"


def test_product_observer__first_projection_drift__rejects_before_leaf(
    product_case: dict[str, Any],
) -> None:
    arguments = runner.handoff._call_arguments(product_case["prompt_input"])
    product_case["expected_first"] = {"prompt_ref": asdict(arguments["prompt_ref"])}
    owner = runner._Observation(
        product_case,
        started=runner.time.monotonic(),
        save=lambda: None,
        fake=False,
        planning_mode=runner.PRODUCT_TASK_FIELD_SCOPE,
    )

    def forbidden(**_kwargs: Any) -> Any:
        raise AssertionError("drift must not reach the leaf")

    leaf = SimpleNamespace(
        provider_name="ollama",
        runtime="LOCAL_GPU",
        model_id=runner.MODEL_ID,
        invoke_structured=forbidden,
    )
    with pytest.raises(ValueError, match="FIRST differs"):
        owner.decorate(leaf).invoke_structured(
            **{**arguments, "prompt_input": {}},
            runtime_policy=RuntimePolicy(sampling_seed=runner.SEED),
        )
    assert owner.calls == []


@pytest.mark.parametrize("failure", ["timeout", "wrong_model", "incomplete"])
def test_product_wire__unsafe_transport_result__records_break_without_hidden_text(
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    payload = {"model": runner.MODEL_ID, "prompt": "synthetic wire"}
    owner = runner._Observation(
        {"expected_first": {"transport_sha256": runner.transport_hash(payload)}},
        started=runner.time.monotonic(),
        save=lambda: None,
        fake=False,
        planning_mode=runner.PRODUCT_TASK_FIELD_SCOPE,
    )
    owner.active = {"phase": "FIRST", "wire_request_count": 0}

    def post(**_kwargs: Any) -> dict[str, Any]:
        if failure == "timeout":
            raise TimeoutError("synthetic timeout")
        return {
            "model": "wrong" if failure == "wrong_model" else runner.MODEL_ID,
            "done": failure != "incomplete",
            "response": "visible incomplete response",
            "thinking": "HIDDEN_MUST_NOT_BE_RECORDED",
        }

    monkeypatch.setattr(runner.transport, "_post_json", post)
    with owner.wire(), pytest.raises((TimeoutError, ValueError)):
        runner.transport._post_json(
            endpoint="http://127.0.0.1:11434",
            path="/api/generate",
            payload=payload,
            timeout_seconds=180,
        )
    assert owner.transport_interrupted is True
    assert owner.active["wire_request_count"] == 1
    assert "HIDDEN_MUST_NOT_BE_RECORDED" not in runner.json.dumps(owner.active)
    if failure != "timeout":
        assert owner.active["rejected_response_content"] == "visible incomplete response"


def test_product_fake_wire__native_slot__returns_native_draft_without_choice_mode() -> None:
    payload = {"model": runner.MODEL_ID, "prompt": "synthetic wire"}
    owner = runner._Observation(
        {
            "expected_first": {"transport_sha256": runner.transport_hash(payload)},
            "prompt_input": {"answer_outline": {"evidence_refs": ["evidence-1"]}},
        },
        started=runner.time.monotonic(),
        save=lambda: None,
        fake=True,
        planning_mode=runner.PRODUCT_TASK_FIELD_SCOPE,
    )
    owner.active = {
        "phase": "FIRST",
        "wire_request_count": 0,
        "prompt_ref": {"prompt_id": "planning.compose_answer"},
    }
    with owner.wire():
        response = runner.transport._post_json(
            endpoint="http://127.0.0.1:11434",
            path="/api/generate",
            payload=payload,
            timeout_seconds=180,
        )
    value = runner.json.loads(str(response["response"]))
    assert set(value) == {"schema_version", "answer", "evidence_refs"}
    assert value["evidence_refs"] == ["evidence-1"]


def test_product_wire__malformed_json__preserves_visible_first_without_thinking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {"model": runner.MODEL_ID, "prompt": "synthetic wire"}
    owner = runner._Observation(
        {"expected_first": {"transport_sha256": runner.transport_hash(payload)}},
        started=runner.time.monotonic(),
        save=lambda: None,
        fake=False,
        planning_mode=runner.PRODUCT_TASK_FIELD_SCOPE,
    )
    owner.active = {"phase": "FIRST", "wire_request_count": 0}
    monkeypatch.setattr(
        runner.transport,
        "_post_json",
        lambda **_kwargs: {
            "model": runner.MODEL_ID,
            "done": True,
            "response": '{"answer":',
            "thinking": "HIDDEN_MUST_NOT_BE_RECORDED",
            "eval_count": 3,
        },
    )
    with owner.wire():
        response = runner.transport._post_json(
            endpoint="http://127.0.0.1:11434",
            path="/api/generate",
            payload=payload,
            timeout_seconds=180,
        )
    with pytest.raises(runner.json.JSONDecodeError):
        runner.json.loads(str(response["response"]))
    assert owner.active["provider_visible_output"] == '{"answer":'
    assert owner.active["provider_response_metadata"]["eval_count"] == 3
    assert "HIDDEN_MUST_NOT_BE_RECORDED" not in runner.json.dumps(owner.active)


def test_main__execute_mode_override__rejects_before_loading_or_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sys.argv",
        [
            "runner",
            "--execute-plan",
            "unused.json",
            "--output",
            "unused",
            "--planning-mode",
            runner.PRODUCT_TASK_FIELD_SCOPE,
        ],
    )
    with pytest.raises(SystemExit, match="2"):
        runner.main()


def test_make_plan__unknown_mode__rejects_before_fixture_or_model_access() -> None:
    with pytest.raises(ValueError, match="unknown"):
        runner.make_plan({}, planning_mode="UNREGISTERED_MODE")
