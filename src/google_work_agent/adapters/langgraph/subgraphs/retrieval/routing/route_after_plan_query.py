from collections.abc import Mapping


def route_after_plan_query(state: object) -> str:
    if isinstance(state, Mapping) and state.get("__context_followup_operation__") == "FINALIZE":
        return "finalize"
    return "build_query"
