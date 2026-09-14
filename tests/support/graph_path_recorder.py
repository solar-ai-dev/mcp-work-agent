"""Production LangGraph callback evidence shared by closure measurements."""

from dataclasses import asdict, is_dataclass
from typing import Any
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler


class GraphPathRecorder(BaseCallbackHandler):
    """Observe existing LangGraph callbacks without replacing Nodes or Routers."""

    def __init__(self) -> None:
        self.path: list[dict[str, object]] = []
        self.active: dict[UUID, dict[str, object]] = {}
        self.completed_count = 0

    def on_chain_start(
        self,
        serialized: dict[str, Any] | None,
        inputs: Any,
        *,
        run_id: UUID,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        node = (metadata or {}).get("langgraph_node")
        if node and kwargs.get("name") == node:
            event = {"node": node, "step": (metadata or {}).get("langgraph_step")}
            self.path.append(event)
            self.active[run_id] = event

    def on_chain_end(self, outputs: Any, *, run_id: UUID, **kwargs: Any) -> None:
        event = self.active.pop(run_id, None)
        if event is not None and isinstance(outputs, dict):
            self.completed_count += 1
            event["completed_sequence"] = self.completed_count
            for key in ("__target__", "workflow_phase", "disposition"):
                if key in outputs:
                    event[key] = outputs[key]
            typed_results: dict[str, object] = {}
            event["typed_results"] = typed_results
            for key in (
                "request_intent",
                "tool_route_plan",
                "retrieval_result",
                "work_analysis",
                "planning_result",
                "execution_result",
                "verification_result",
                "final_result",
                "query_plan",
                "query_attempts",
                "__context_query_attempts__",
                "sufficiency",
                "evidence_selection",
                "evidence_drafts",
                "person_candidates",
                "selected_person_identities",
                "retry_budget",
            ):
                value = outputs.get(key)
                if value is not None:
                    typed_results[key] = {
                        "type": type(value).__name__,
                        "value": asdict(value)
                        if is_dataclass(value) and not isinstance(value, type)
                        else value,
                    }
            event["updated_keys"] = sorted(outputs)

    def on_chain_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        event = self.active.pop(run_id, None)
        if event is not None:
            self.completed_count += 1
            event["completed_sequence"] = self.completed_count
            event["error_type"] = type(error).__name__
            event["error_code"] = getattr(error, "code", getattr(error, "reason_code", None))
