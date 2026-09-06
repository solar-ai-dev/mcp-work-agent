from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from google_work_agent.application.use_cases.run.reconcile_retrieval_cache_restart import (
    ReconcileRetrievalCacheRestartCommandV1,
    ReconcileRetrievalCacheRestartHandler,
)
from google_work_agent.domain.run.model import RunStatusV1


def test_reconcile_retrieval_cache_restart__has_exact__application_owner() -> None:
    assert (
        ReconcileRetrievalCacheRestartHandler.__module__
        == "google_work_agent.application.use_cases.run.reconcile_retrieval_cache_restart"
    )
    assert ReconcileRetrievalCacheRestartHandler.__name__ == "ReconcileRetrievalCacheRestartHandler"


@pytest.mark.parametrize("status", ["WAITING_APPROVAL", "EXECUTING", "VERIFYING"])
def test_durable_plan__does_not_require_lost_retrieval_cache__for_settlement(status):
    cache = Mock()
    checkpoint = Mock()
    checkpoint.load_workflow_binding.return_value = SimpleNamespace(langgraph_thread_id="thread")
    checkpoint.load_same_run_checkpoint.return_value = SimpleNamespace(checkpoint_generation=3)
    handler = ReconcileRetrievalCacheRestartHandler(
        unit_of_work_factory=lambda: nullcontext(
            SimpleNamespace(
                runs=SimpleNamespace(get=lambda _: SimpleNamespace(status=RunStatusV1(status))),
            )
        ),
        checkpoint=checkpoint,
        retrieval_cache=cache,
        resume_target_registry=Mock(),
        schedule_run_execution=Mock(),
        id_factory=lambda: "unused",
    )
    assert (
        handler(ReconcileRetrievalCacheRestartCommandV1(1, "run")).outcome == "NO_RESTART_REQUIRED"
    )
    cache.resolve_read_result.assert_not_called()
