"""Charge a bounded Retrieval dispatch against the existing RunBudget authority."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import cast

from google_work_agent.application.use_cases.run.guard_run_budget import (
    GuardRunBudgetHandler,
    GuardRunBudgetQueryV1,
    RunBudgetDeltaV1,
    RunBudgetOperationKindV1,
    RunBudgetV2,
    merge_run_budget_progress,
    validate_run_budget_v2,
)


class RetrievalReadBudgetExceeded(ValueError):
    """No connector read may be dispatched after the Run budget is exhausted."""


def consume_retrieval_read_budget(
    budget: RunBudgetV2,
    *,
    run_id: str,
    is_detail: bool,
    now_ms: int,
    durable_accountant: Callable[
        [Callable[[Mapping[str, object]], Mapping[str, object]]], Mapping[str, object]
    ]
    | None = None,
) -> None:
    """Reserve before I/O; unsuccessful external calls consume their budget too."""

    def update(current: Mapping[str, object]) -> Mapping[str, object]:
        merged = merge_run_budget_progress(current, budget)
        dimensions: tuple[RunBudgetOperationKindV1, ...] = (
            "CONNECTOR_CALL",
            "DETAIL_FETCH" if is_detail else "SOURCE_PAGE",
        )
        for dimension in dimensions:
            decision = GuardRunBudgetHandler()(
                GuardRunBudgetQueryV1(
                    1,
                    run_id,
                    merged,
                    RunBudgetDeltaV1(1, dimension, 1),
                    now_ms,
                )
            )
            if not decision.allowed:
                raise RetrievalReadBudgetExceeded(decision.reason_code)
        updated: RunBudgetV2 = {
            **merged,
            "connector_calls_used": merged["connector_calls_used"] + 1,
        }
        if is_detail:
            updated["detail_fetches_used"] += 1
        else:
            updated["source_page_calls_used"] += 1
        return validate_run_budget_v2(updated)

    updated = validate_run_budget_v2(
        dict(update(budget) if durable_accountant is None else durable_accountant(update))
    )
    mutable = cast(dict[str, object], budget)
    mutable.clear()
    mutable.update(updated)
