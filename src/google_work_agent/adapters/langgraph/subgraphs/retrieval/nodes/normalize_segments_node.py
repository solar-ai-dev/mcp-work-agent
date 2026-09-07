from collections.abc import Mapping

from google_work_agent.application.agents.retrieval.normalize_segments import normalize_segments

from ..projections.normalize_segments_projection import project_normalize_segments_input


def normalize_segments_node(state: Mapping[str, object]) -> dict[str, object]:
    segments = normalize_segments(**project_normalize_segments_input(state))
    return {
        "normalized_segments": segments,
        "segment_handles": [segment.segment_id for segment in segments],
    }
