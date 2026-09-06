from __future__ import annotations

from dataclasses import asdict

from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    AmbiguityV1,
    ConstraintProvenanceSource,
    RequestGoalCandidateV1,
    RequestIntentV2,
)
from google_work_agent.application.agents.request_understanding.validate_intent import (
    materialize_validated_constraint_provenance,
    validate_intent,
)
from google_work_agent.ports.system.settings_port import GitHubRepositoryDefaultV1


def finalize_intent(
    goal_candidate: RequestGoalCandidateV1,
    ambiguity_candidate: AmbiguityV1,
    *,
    artifact_id: str,
    user_request: str,
    confirmation_response_text: str | None = None,
    repository_default: GitHubRepositoryDefaultV1 | None = None,
) -> RequestIntentV2:
    if not artifact_id:
        raise ValueError("artifact_id must be non-empty")
    constraints = materialize_validated_constraint_provenance(
        goal_candidate["constraints"],
        user_request=user_request,
        confirmation_response_text=confirmation_response_text,
    )
    provenance_sources: dict[ConstraintProvenanceSource, str] = {"USER_REQUEST": user_request}
    if confirmation_response_text is not None:
        provenance_sources["CONFIRMATION_RESPONSE"] = confirmation_response_text
    return validate_intent(
        {
            "schema_version": 2,
            **goal_candidate,
            "constraints": constraints,
            "ambiguity": ambiguity_candidate,
            "meta": {"artifact_id": artifact_id, "revision": 1, "based_on": []},
            **(
                {"repository_default": asdict(repository_default)}
                if repository_default is not None
                else {}
            ),
        },
        require_meta=True,
        provenance_sources=provenance_sources,
    )
