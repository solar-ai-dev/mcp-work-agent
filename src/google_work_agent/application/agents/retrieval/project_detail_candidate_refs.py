"""Project bounded detail candidates from selected and acquired resources."""

from __future__ import annotations

from collections.abc import Sequence

from google_work_agent.application.agents.retrieval.contracts.retrieval_result import (
    AcquisitionResultV1,
    EvidenceDraftV1,
)


def project_detail_candidate_refs(
    *,
    evidence_drafts: Sequence[EvidenceDraftV1],
    acquisition_result: AcquisitionResultV1 | None,
) -> list[str]:
    """Prefer selected evidence, then retain acquired candidates for required hydration."""

    acquired = [] if acquisition_result is None else acquisition_result["resource_handles"]
    return list(
        dict.fromkeys(
            [draft["resource_handle"] for draft in evidence_drafts]
            + [handle for handle in acquired if isinstance(handle, str)]
        )
    )


__all__ = ["project_detail_candidate_refs"]
