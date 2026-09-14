"""Apply Canonical faults at evaluator-owned call boundaries.

The adapters are deliberately duck typed.  Evaluation code stays outside the
Product import graph, while a Product composition or a direct boundary test can
pass the real Connector/MCP/LLM objects and exact Product error/result factories.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, is_dataclass, replace
from typing import Any, Literal, cast

from .fault_profiles import FaultDirective, FaultHarness, FaultObservation

EvaluationMode = Literal[
    "LIVE_PROVIDER",
    "LIVE_WITH_FAULT_INJECTION",
    "SIMULATED_PROVIDER",
    "COMPONENT_ONLY",
]


@dataclass(frozen=True, slots=True)
class InjectedCallResult:
    safe_code: str | None
    delivery_certainty: str | None
    outcome_kind: str


class InjectedFaultError(RuntimeError):
    def __init__(self, directive: FaultDirective) -> None:
        safe_code = directive.outcome.safe_code or directive.outcome.kind
        super().__init__(safe_code)
        self.safe_code = safe_code
        self.delivery_certainty = directive.outcome.delivery_certainty
        self.directive = directive


@dataclass(frozen=True, slots=True)
class FaultApplicationRecord:
    case_id: str
    profile_name: str
    evaluation_mode: EvaluationMode
    rule_id: str
    boundary: str
    connector: str | None
    operation: str
    outcome_kind: str
    safe_code: str | None
    injection_number: int
    delegate_called: bool
    effect_applied: bool
    product_success_payload_visible: bool


class FaultApplyingAdapter:
    """Stateful executor for one Case's resolved fault directives."""

    def __init__(
        self,
        harness: FaultHarness,
        *,
        process_terminator: Callable[[], None] | None = None,
        cancel_command: Callable[[], None] | None = None,
        fixture_provider: Callable[[FaultDirective], Any] | None = None,
    ) -> None:
        self.harness = harness
        self._process_terminator = process_terminator
        self._cancel_command = cancel_command
        self._fixture_provider = fixture_provider
        self._records: list[FaultApplicationRecord] = []

    @property
    def records(self) -> tuple[FaultApplicationRecord, ...]:
        return tuple(self._records)

    def invoke(
        self,
        *,
        boundary: str,
        connector: str | None,
        operation: str,
        delegate: Callable[[], Any],
        checkpoints: frozenset[str] = frozenset(),
        required_fields: tuple[str, ...] = (),
    ) -> Any:
        observation = FaultObservation(
            case_id=self.harness.case_id,
            boundary=boundary,
            connector=connector,
            operation=operation,
            checkpoints=checkpoints,
        )
        directive = self.harness.observe(observation)
        if directive is None:
            return delegate()

        outcome = directive.outcome
        delegated_value: Any = None
        delegate_called = False
        if outcome.apply_effect_before_outcome:
            delegated_value = delegate()
            delegate_called = True

        try:
            if outcome.kind == "RETURN_ERROR":
                raise InjectedFaultError(directive)
            if outcome.kind == "TERMINATE_TEST_PROCESS":
                if self._process_terminator is None:
                    raise RuntimeError("process_terminator is required for this fault")
                self._process_terminator()
                raise InjectedFaultError(directive)
            if outcome.kind in {"LOSE_RESPONSE", "RETURN_UNKNOWN"}:
                return InjectedCallResult(
                    safe_code=outcome.safe_code,
                    delivery_certainty=outcome.delivery_certainty,
                    outcome_kind=outcome.kind,
                )
            if outcome.kind == "USER_CANCEL":
                if self._cancel_command is None:
                    raise RuntimeError("cancel_command is required for this fault")
                self._cancel_command()
                return InjectedCallResult(
                    safe_code=outcome.safe_code,
                    delivery_certainty=outcome.delivery_certainty,
                    outcome_kind=outcome.kind,
                )
            if outcome.kind in {"MUTATE_OUTPUT", "MUTATE_VERIFICATION_RESULT"}:
                if not delegate_called:
                    delegated_value = delegate()
                    delegate_called = True
                return _mutate_result(
                    delegated_value,
                    mutation=str(outcome.payload.get("mutation", "")),
                    required_fields=required_fields,
                )
            if outcome.kind == "USE_BOUND_FIXTURE":
                if self._fixture_provider is None:
                    raise RuntimeError("fixture_provider is required for this fault")
                return self._fixture_provider(directive)
            if outcome.kind == "USE_BOUND_CANDIDATE_ORDER":
                if not delegate_called:
                    delegated_value = delegate()
                    delegate_called = True
                return _bind_candidate_order(delegated_value, directive)
            if outcome.kind == "SET_BUDGET_EXHAUSTED":
                return {
                    "schema_version": 1,
                    "status": "BUDGET_STOPPED",
                    "reason_code": outcome.safe_code,
                    "required_fact_observed": bool(
                        outcome.payload.get("required_fact_observed", False)
                    ),
                }
            raise ValueError(f"unsupported fault outcome: {outcome.kind}")
        finally:
            self._records.append(
                FaultApplicationRecord(
                    case_id=self.harness.case_id,
                    profile_name=directive.profile_name,
                    evaluation_mode=directive.evaluation_mode,
                    rule_id=directive.rule_id,
                    boundary=boundary,
                    connector=connector,
                    operation=operation,
                    outcome_kind=outcome.kind,
                    safe_code=outcome.safe_code,
                    injection_number=directive.injection_number,
                    delegate_called=delegate_called,
                    effect_applied=outcome.apply_effect_before_outcome,
                    product_success_payload_visible=False,
                )
            )


class FaultInjectingConnectorAdapter:
    """Duck-typed ConnectorReadPort/ConnectorWritePort evaluation wrapper."""

    def __init__(
        self,
        *,
        fault_adapter: FaultApplyingAdapter,
        read_delegate: Any | None = None,
        write_delegate: Any | None = None,
        read_boundary: str = "CONNECTOR_READ_RESULT",
        checkpoints: Callable[[], frozenset[str]] = frozenset,
        read_error_factory: Callable[[InjectedFaultError], BaseException] | None = None,
        write_result_factory: Callable[[InjectedCallResult], Any] | None = None,
    ) -> None:
        self._fault_adapter = fault_adapter
        self._read_delegate = read_delegate
        self._write_delegate = write_delegate
        self._read_boundary = read_boundary
        self._checkpoints = checkpoints
        self._read_error_factory = read_error_factory
        self._write_result_factory = write_result_factory

    def execute_read(self, binding: Any, tool_arguments: dict[str, Any]) -> Any:
        if self._read_delegate is None:
            raise RuntimeError("read_delegate is required")
        read_delegate = self._read_delegate
        operation = _tool_id(binding)
        connector = _connector_for_call(operation, tool_arguments)
        try:
            return self._fault_adapter.invoke(
                boundary=self._read_boundary,
                connector=connector,
                operation=operation,
                checkpoints=self._checkpoints(),
                delegate=lambda: read_delegate.execute_read(binding, tool_arguments),
            )
        except InjectedFaultError as error:
            if self._read_error_factory is None:
                raise
            raise self._read_error_factory(error) from error

    def execute_write(
        self,
        binding: Any,
        tool_arguments: dict[str, Any],
        claim_token: dict[str, Any],
    ) -> Any:
        if self._write_delegate is None:
            raise RuntimeError("write_delegate is required")
        write_delegate = self._write_delegate
        operation = _tool_id(binding)
        connector = _connector_for_tool(operation)
        boundary = _write_boundary(
            self._fault_adapter.harness,
            connector=connector,
            operation=operation,
        )
        try:
            result = self._fault_adapter.invoke(
                boundary=boundary,
                connector=connector,
                operation=operation,
                checkpoints=self._checkpoints(),
                delegate=lambda: write_delegate.execute_write(
                    binding, tool_arguments, claim_token
                ),
            )
        except InjectedFaultError as error:
            injected = InjectedCallResult(
                safe_code=error.safe_code,
                delivery_certainty=error.delivery_certainty,
                outcome_kind=error.directive.outcome.kind,
            )
            return self._write_result(injected)
        if isinstance(result, InjectedCallResult):
            return self._write_result(result)
        return result

    def _write_result(self, result: InjectedCallResult) -> Any:
        return result if self._write_result_factory is None else self._write_result_factory(result)


class FaultInjectingMCPClientAdapter:
    """MCPClientPort wrapper that contains process loss to one Case runtime."""

    def __init__(
        self,
        *,
        fault_adapter: FaultApplyingAdapter,
        delegate: Any,
        error_factory: Callable[[InjectedFaultError], BaseException] | None = None,
    ) -> None:
        self._fault_adapter = fault_adapter
        self._delegate = delegate
        self._error_factory = error_factory

    def process_instance_id(self, connector_id: str) -> str | None:
        value = self._delegate.process_instance_id(connector_id)
        return None if value is None else str(value)

    def sign_claim_context(self, connector_id: str, payload: dict[str, object]) -> str:
        return str(self._delegate.sign_claim_context(connector_id, payload))

    def list_tools(self, connector_id: str) -> Any:
        return self._delegate.list_tools(connector_id)

    def call_tool(
        self, connector_id: str, tool_id: str, arguments: Any, timeout_ms: int
    ) -> Any:
        try:
            return self._fault_adapter.invoke(
                boundary="MCP_TRANSPORT",
                connector="mcp",
                operation="read_call",
                delegate=lambda: self._delegate.call_tool(
                    connector_id, tool_id, arguments, timeout_ms
                ),
            )
        except InjectedFaultError as error:
            if self._error_factory is None:
                raise
            raise self._error_factory(error) from error

    def restart_once(self, connector_id: str) -> Any:
        return self._delegate.restart_once(connector_id)


class FaultInjectingLLMProviderAdapter:
    """StructuredLLMProvider wrapper that faults before Product validation."""

    def __init__(
        self,
        *,
        fault_adapter: FaultApplyingAdapter,
        delegate: Any,
        error_factory: Callable[[InjectedFaultError], BaseException] | None = None,
        required_fields: tuple[str, ...] = (),
    ) -> None:
        self._fault_adapter = fault_adapter
        self._delegate = delegate
        self._error_factory = error_factory
        self._required_fields = required_fields
        self._structured_calls = 0

    @property
    def provider_name(self) -> str:
        return str(self._delegate.provider_name)

    @property
    def runtime(self) -> Any:
        return self._delegate.runtime

    def invoke_structured(self, **kwargs: Any) -> Any:
        self._structured_calls += 1
        try:
            value = self._fault_adapter.invoke(
                boundary="LLM_INVOCATION",
                connector="local_inference",
                operation="structured_inference",
                delegate=lambda: self._delegate.invoke_structured(**kwargs),
            )
            operation = (
                "validate_initial_output"
                if self._structured_calls == 1
                else "validate_repair_output"
            )
            return self._fault_adapter.invoke(
                boundary="STRUCTURED_OUTPUT",
                connector="llm",
                operation=operation,
                delegate=lambda: value,
                required_fields=self._required_fields,
            )
        except InjectedFaultError as error:
            if self._error_factory is None:
                raise
            raise self._error_factory(error) from error

    def invoke_tool_call(self, **kwargs: Any) -> Any:
        try:
            return self._fault_adapter.invoke(
                boundary="LLM_INVOCATION",
                connector="local_inference",
                operation="text_inference",
                delegate=lambda: self._delegate.invoke_tool_call(**kwargs),
            )
        except InjectedFaultError as error:
            if self._error_factory is None:
                raise
            raise self._error_factory(error) from error


def _tool_id(binding: Any) -> str:
    value = getattr(binding, "tool_id", None)
    if not isinstance(value, str) or not value:
        raise ValueError("connector binding must expose tool_id")
    return value


def _connector_for_tool(tool_id: str) -> str:
    prefix = tool_id.split("_", 1)[0]
    return "calendar" if prefix == "calendar" else "tasks" if prefix == "tasks" else "gmail"


def _connector_for_call(tool_id: str, arguments: Mapping[str, Any]) -> str:
    if tool_id != "search_by_recovery_fingerprint":
        return _connector_for_tool(tool_id)
    resource_type = arguments.get("resource_type")
    if resource_type == "task":
        return "tasks"
    if resource_type in {"calendar", "calendar_event"}:
        return "calendar"
    return "gmail"


def _write_boundary(
    harness: FaultHarness, *, connector: str, operation: str
) -> str:
    for rule in harness.profile.rules:
        if rule.connector == connector and operation in rule.operations:
            return rule.boundary
    return "CONNECTOR_PRE_DISPATCH"


def _mutate_result(
    value: Any, *, mutation: str, required_fields: tuple[str, ...]
) -> Any:
    if mutation == "REMOVE_ONE_SCHEMA_REQUIRED_FIELD":
        return _replace_content(value, _remove_required_field(_content(value), required_fields))
    if mutation == "DIFFER_FROM_APPROVED_VALUE":
        return _replace_connector_output(value, _mismatched_output(_connector_output(value)))
    raise ValueError(f"unsupported result mutation: {mutation}")


def _content(value: Any) -> Mapping[str, Any]:
    content = getattr(value, "content", value)
    if not isinstance(content, Mapping):
        raise ValueError("structured output mutation requires an object")
    return content


def _replace_content(value: Any, content: dict[str, Any]) -> Any:
    if isinstance(value, Mapping):
        return content
    if is_dataclass(value) and hasattr(value, "content"):
        return replace(cast(Any, value), content=content)
    raise ValueError("structured output carrier is unsupported")


def _remove_required_field(
    content: Mapping[str, Any], required_fields: tuple[str, ...]
) -> dict[str, Any]:
    candidates = required_fields or tuple(content)
    field = next((item for item in candidates if item in content), None)
    if field is None:
        raise ValueError("no schema-required field is available to remove")
    return {key: value for key, value in content.items() if key != field}


def _connector_output(value: Any) -> Mapping[str, Any]:
    output = getattr(value, "output", None)
    if output is None and isinstance(value, Mapping):
        nested = value.get("output")
        output = nested if isinstance(nested, Mapping) else value
    if not isinstance(output, Mapping):
        raise ValueError("verification mutation requires Connector READ output")
    return output


def _replace_connector_output(value: Any, output: dict[str, Any]) -> Any:
    if isinstance(value, Mapping):
        return {**value, "output": output} if "output" in value else output
    if is_dataclass(value) and hasattr(value, "output"):
        return replace(cast(Any, value), output=output)
    raise ValueError("Connector READ result carrier is unsupported")


def _mismatched_output(output: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(output)
    raw_item = result.get("item")
    if not isinstance(raw_item, Mapping):
        raise ValueError("verification result requires one item")
    item = dict(raw_item)
    payload_value = item.get("payload")
    payload = dict(payload_value) if isinstance(payload_value, Mapping) else item
    field = next((name for name in ("notes", "title", "status", "due") if name in payload), None)
    if field is None:
        raise ValueError("verification result has no comparable field")
    payload[field] = f"{payload[field]} [EVALUATION_MISMATCH]"
    if isinstance(payload_value, Mapping):
        item["payload"] = payload
    else:
        item = payload
    result["item"] = item
    return result


def _bind_candidate_order(value: Any, directive: FaultDirective) -> Any:
    if not isinstance(value, list) or not all(isinstance(item, Mapping) for item in value):
        raise ValueError("candidate ranking fault requires a list of objects")
    required = directive.outcome.payload.get("required_projects")
    if not isinstance(required, list) or not all(isinstance(item, str) for item in required):
        raise ValueError("candidate ranking fault requires project names")
    positions = {name: index for index, name in enumerate(required)}

    def project(item: Mapping[str, Any]) -> str:
        payload = item.get("payload")
        if isinstance(payload, Mapping) and isinstance(payload.get("project"), str):
            return str(payload["project"])
        return str(item.get("project", ""))

    projects = {project(item) for item in value}
    if not set(required) <= projects:
        raise ValueError("bound candidates do not contain every required project")
    return sorted(value, key=lambda item: (positions.get(project(item), len(positions)),))


__all__ = [
    "EvaluationMode",
    "FaultApplicationRecord",
    "FaultApplyingAdapter",
    "FaultInjectingConnectorAdapter",
    "FaultInjectingLLMProviderAdapter",
    "FaultInjectingMCPClientAdapter",
    "InjectedCallResult",
    "InjectedFaultError",
]
