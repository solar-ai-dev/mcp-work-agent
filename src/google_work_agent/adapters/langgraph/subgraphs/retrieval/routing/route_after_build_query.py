from collections.abc import Mapping, Set


def followup_operation_marker(operation_kinds: Set[str]) -> str:
    """Keep every supported mixed READ plan on the execute-read edge."""

    if len(operation_kinds) == 1:
        operation = next(iter(operation_kinds))
        return "SEARCH" if operation == "FREEBUSY" else operation
    return "READ"


def route_after_build_query(state: object) -> str:
    if isinstance(state, Mapping) and state.get("__context_followup_operation__") == "FINALIZE":
        return "finalize"
    return "execute_read"
