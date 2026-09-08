"""Review confirmation routing at the Main graph boundary."""

from google_work_agent.adapters.langgraph.main.nodes.review_entry_node import review_entry_node
from google_work_agent.adapters.langgraph.main.routing.route_after_review import (
    ROUTE_AFTER_REVIEW_SUCCESSORS,
    route_after_review,
)


def test_review_confirmation__reenters_review__to_materialize_interrupt() -> None:
    state = {
        "run_id": "run-1",
        "__target__": "end",
        "workflow_phase": "WAITING_CONFIRMATION",
        "user_interrupt": {
            "interrupt_kind": "CONFIRMATION",
            "interrupt_id": "interrupt-1",
        },
    }
    target = route_after_review(
        state,
        available_targets=ROUTE_AFTER_REVIEW_SUCCESSORS,
        should_stop_for_cancel=lambda _run_id: False,
    )

    assert target == "review_entry"
    entry = review_entry_node(
        state,
        prepare_persisted_review=lambda _state: {},
        settle_persisted_review=lambda _state: {},
        review_node="review",
    )
    assert entry["__target__"] == "review"
    assert entry["workflow_phase"] == "PLAN_REVIEW"


def test_review_without_confirmation__keeps_end__target() -> None:
    target = route_after_review(
        {
            "run_id": "run-1",
            "__target__": "end",
            "workflow_phase": "PLAN_REVIEW",
        },
        available_targets=ROUTE_AFTER_REVIEW_SUCCESSORS,
        should_stop_for_cancel=lambda _run_id: False,
    )

    assert target == "end"
