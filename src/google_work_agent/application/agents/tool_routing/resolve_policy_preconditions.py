from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestIntentV3,
)
from google_work_agent.application.agents.tool_routing.bind_registry_candidates import (
    coarse_resource_category,
)
from google_work_agent.application.agents.tool_routing.contracts.semantic_route_candidate import (
    SemanticRouteCandidate,
)
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    ScopeExpansionRequiredV1,
    ToolRoutePlanV2,
)
from google_work_agent.application.use_cases.run.policy_confirmation_receipt import (
    PolicyConfirmationReceiptV1,
)
from google_work_agent.domain.canonical import calculate_canonical_json_hash


@dataclass(frozen=True, slots=True)
class PolicyPreconditionResolutionV1:
    candidate: SemanticRouteCandidate
    workflow_signal: ScopeExpansionRequiredV1 | None


_ANALYSIS_REQUIRED_REASON_CODES = frozenset(
    {
        "POLICY_TASK_DUPLICATE_CHECK",
        "POLICY_CALENDAR_CONFLICT_CHECK",
    }
)


def effective_analysis_required(
    *,
    request_intent: RequestIntentV3,
    tool_route_plan: ToolRoutePlanV2,
) -> bool:
    """Derive Work Analysis applicability from current semantic artifacts.

    Request Understanding owns the explicit analysis requirement. Policy
    preconditions may additionally require analysis; their frozen IN-route
    reason codes preserve that decision through Tool Routing without a second
    durable skip flag.
    """

    if request_intent["analysis_requirement"] == "REQUIRED":
        return True
    return policy_analysis_required(tool_route_plan)


def policy_analysis_required(tool_route_plan: ToolRoutePlanV2) -> bool:
    """Return whether frozen Policy preconditions require guarded analysis."""
    return any(
        reason_code in _ANALYSIS_REQUIRED_REASON_CODES
        for route in tool_route_plan["input_plan"]["input_routes"]
        for reason_code in route["reason_codes"]
    )


def resolve_policy_preconditions(
    *,
    request_intent: RequestIntentV3,
    candidate: SemanticRouteCandidate,
    policy_confirmation_receipts: Sequence[PolicyConfirmationReceiptV1] = (),
    current_interrupt_id: str | None = None,
    scope_expansion: ScopeExpansionResolver | None = None,
) -> PolicyPreconditionResolutionV1:
    """Check direct and mandatory READ scope without changing any OUT route.

    An out-of-scope READ is never materialized until the Application-owned
    confirmation receipt for the current interrupt validates successfully.
    """

    required_reads = _required_reads(candidate)
    required_bindings = _required_read_bindings(candidate)
    scope_reads, scope_bindings = _scope_read_bindings(
        candidate, required_reads=required_reads, required_bindings=required_bindings
    )
    resolver = scope_expansion or ScopeExpansionResolver()
    out_of_scope = resolver.out_of_scope_reads(
        request_intent=request_intent,
        required_reads=scope_reads,
        category_of=coarse_resource_category,
        required_work_unit_bindings=scope_bindings,
    )
    if out_of_scope:
        required_resource_types = tuple(sorted({read[1] for read in out_of_scope}))
        reason_codes = tuple(sorted({read[2] for read in out_of_scope}))
        approval = resolver.find_valid_approval(
            request_intent=request_intent,
            required_resource_types=required_resource_types,
            reason_codes=reason_codes,
            receipts=policy_confirmation_receipts,
            current_interrupt_id=current_interrupt_id,
        )
        if approval is None:
            return PolicyPreconditionResolutionV1(
                candidate=candidate,
                workflow_signal={
                    "schema_version": 1,
                    "kind": "SCOPE_EXPANSION_REQUIRED",
                    "reason_codes": list(reason_codes),
                    "required_resource_types": list(required_resource_types),
                },
            )
    return PolicyPreconditionResolutionV1(
        candidate=_merge_required_reads(
            candidate, required_reads=required_reads, required_bindings=required_bindings
        ),
        workflow_signal=None,
    )


def _required_reads(
    candidate: SemanticRouteCandidate,
) -> tuple[tuple[str, str, str], ...]:
    required: set[tuple[str, str, str]] = set()
    for resource_type, effect in candidate.output_pairs:
        required.update(_reads_for_output(resource_type, effect.value))
    return tuple(sorted(required))


def _reads_for_output(resource_type: str, effect: str) -> tuple[tuple[str, str, str], ...]:
    if (resource_type, effect) == ("TASK", "CREATE"):
        return tuple(
            ("", resource, "POLICY_TASK_DUPLICATE_CHECK") for resource in ("TASK", "TASK_LIST")
        )
    if (resource_type, effect) == ("CALENDAR_EVENT", "CREATE"):
        return tuple(
            ("", resource, "POLICY_CALENDAR_CONFLICT_CHECK")
            for resource in ("CALENDAR", "CALENDAR_EVENT", "CALENDAR_FREEBUSY")
        )
    return ()


def _required_read_bindings(
    candidate: SemanticRouteCandidate,
) -> dict[tuple[str, str, str], tuple[str, ...]]:
    bindings: dict[tuple[str, str, str], tuple[str, ...]] = {}
    for resource, effect, unit_ids in candidate.output_work_unit_bindings:
        for read in _reads_for_output(resource, effect.value):
            bindings[read] = tuple(dict.fromkeys((*bindings.get(read, ()), *unit_ids)))
    return bindings


def _scope_read_bindings(
    candidate: SemanticRouteCandidate,
    *,
    required_reads: Sequence[tuple[str, str, str]],
    required_bindings: Mapping[tuple[str, str, str], tuple[str, ...]],
) -> tuple[
    tuple[tuple[str, str, str], ...],
    dict[tuple[str, str, str], tuple[str, ...]],
]:
    reads_by_resource = {read[1]: read for read in required_reads}
    bindings = {read: required_bindings.get(read, ()) for read in required_reads}
    direct_reasons = dict(candidate.input_reason_codes)
    direct_bindings = dict(candidate.input_work_unit_bindings)
    for resource_type in candidate.input_resource_types:
        read = reads_by_resource.setdefault(
            resource_type,
            ("", resource_type, direct_reasons.get(resource_type, "REQUESTED_INPUT")),
        )
        direct_ids = direct_bindings.get(resource_type, ())
        # A missing legacy binding cannot narrow the comparison to known IDs.
        if not direct_ids or (read in bindings and not bindings[read]):
            bindings[read] = ()
        else:
            bindings[read] = tuple(dict.fromkeys((*bindings.get(read, ()), *direct_ids)))
    return tuple(sorted(bindings)), bindings


def _merge_required_reads(
    candidate: SemanticRouteCandidate,
    *,
    required_reads: Sequence[tuple[str, str, str]],
    required_bindings: Mapping[tuple[str, str, str], tuple[str, ...]],
) -> SemanticRouteCandidate:
    input_resources = set(candidate.input_resource_types)
    reason_codes = dict(candidate.input_reason_codes)
    work_unit_ids_by_resource = dict(candidate.input_work_unit_bindings)
    for read in required_reads:
        _connector_id, resource_type, reason_code = read
        input_resources.add(resource_type)
        reason_codes[resource_type] = reason_code
        existing = list(work_unit_ids_by_resource.get(resource_type, ()))
        existing.extend(
            unit_id for unit_id in required_bindings.get(read, ()) if unit_id not in existing
        )
        work_unit_ids_by_resource[resource_type] = tuple(existing)
    return SemanticRouteCandidate(
        input_resource_types=tuple(sorted(input_resources)),
        output_pairs=candidate.output_pairs,
        output_mode=candidate.output_mode,
        analysis_requirement=candidate.analysis_requirement,
        input_reason_codes=tuple(sorted(reason_codes.items())),
        input_work_unit_bindings=tuple(
            (resource_type, work_unit_ids_by_resource[resource_type])
            for resource_type in sorted(input_resources)
        ),
        output_work_unit_bindings=candidate.output_work_unit_bindings,
    )


# Preserved scope-expansion policy is owned by this precondition operation.

PolicyReadTriple = tuple[str, str, str]
"""``(connector_id, resource_type, reason_code)`` -- the shape returned by
``resolve_policy_preconditions``."""


class ScopeExpansionResolver:
    """Compare direct and Policy Precondition reads against explicit user scope.

    "Explicit scope" is read from ``RequestIntentV3.constraints`` entries with
    ``kind="SCOPE"``, ``field in {"required_sources", "forbidden_sources"}``
    -- the same coarse EMAIL/TASK/CALENDAR source vocabulary
    ``coarse_resource_category`` already produces, established (not
    invented) by the ``canonical_rebase_v7`` dataset fixtures (e.g.
    ``canonical_e2e/core/CASE-CORE-004/projection-uu.json``). ``RESOURCE``-kind
    constraints are a different, already-consumed concept (specific selected
    resource ids -- see ``retrieval_ranking.py._selected_resource_ids``) and
    are intentionally not read here.
    """

    def out_of_scope_reads(
        self,
        *,
        request_intent: RequestIntentV3,
        required_reads: Iterable[PolicyReadTriple],
        category_of: Callable[[str], str],
        required_work_unit_bindings: Mapping[PolicyReadTriple, tuple[str, ...]] | None = None,
    ) -> tuple[PolicyReadTriple, ...]:
        out_of_scope: list[PolicyReadTriple] = []
        for read in required_reads:
            _connector_id, resource_type, _reason_code = read
            category = category_of(resource_type)
            unit_ids = (required_work_unit_bindings or {}).get(read, ())
            # Missing legacy bindings remain conservative; a typed binding only
            # limits the comparison to the WorkUnits that require this READ.
            for unit_id in unit_ids or (None,):
                required_sources, forbidden_sources = _explicit_source_scope(
                    request_intent, work_unit_id=unit_id
                )
                forbidden = category in forbidden_sources
                not_allowed = required_sources is not None and category not in required_sources
                if forbidden or not_allowed:
                    out_of_scope.append(read)
                    break
        return tuple(out_of_scope)

    def find_valid_approval(
        self,
        *,
        request_intent: RequestIntentV3,
        required_resource_types: tuple[str, ...],
        reason_codes: tuple[str, ...],
        receipts: Sequence[PolicyConfirmationReceiptV1],
        current_interrupt_id: str | None,
    ) -> PolicyConfirmationReceiptV1 | None:
        """Fail-closed lookup: a receipt only unlocks the exact resume it was
        built for. It must be APPROVED, carry the ``interrupt_id`` that was
        *just* resolved (never an older or foreign one -- receipts are not
        standing credentials), reference the current ``RequestIntentV3``
        revision in ``meta.based_on``, and its ``decision_context_hash`` must
        match the exact current out-of-scope read set recomputed fresh. Any
        mismatch (wrong run, wrong interrupt, stale revision, tampered hash)
        fails closed -- ``None``, meaning Scope Expansion is asked again.
        """
        if current_interrupt_id is None:
            return None
        meta = request_intent["meta"]
        artifact_id = meta["artifact_id"]
        revision = meta["revision"]
        for receipt in receipts:
            if receipt["decision"] != "APPROVED":
                continue
            if receipt["confirmation_kind"] != "SCOPE_EXPANSION":
                continue
            if receipt["interrupt_id"] != current_interrupt_id:
                continue
            if not any(
                ref["artifact_id"] == artifact_id and ref["revision"] == revision
                for ref in receipt["meta"]["based_on"]
            ):
                continue
            expected_hash = calculate_canonical_json_hash(
                _decision_context(
                    request_intent_artifact_id=artifact_id,
                    request_intent_revision=revision,
                    interrupt_id=receipt["interrupt_id"],
                    required_resource_types=required_resource_types,
                    reason_codes=reason_codes,
                )
            )
            if receipt["decision_context_hash"] == expected_hash:
                return receipt
        return None


def build_policy_confirmation_receipt(
    *,
    id_factory: Callable[[], str],
    interrupt_id: str,
    decision: Literal["APPROVED", "DECLINED"],
    request_intent: RequestIntentV3,
    required_resource_types: tuple[str, ...],
    reason_codes: tuple[str, ...],
    affected_route_ids: list[str],
) -> PolicyConfirmationReceiptV1:
    """Build one immutable ``PolicyConfirmationReceiptV1``.

    Called only by the Application/Confirmation Controller layer
    (``adapters/langgraph/subgraphs/tool_routing.py``'s scope-expansion
    resolution), immediately after a real ``ConfirmationResponseProjectionV1`` for
    ``interrupt_id`` has already been validated -- never speculatively, and
    never by an LLM/Agent. ``decision_context_hash`` binds this receipt to
    the exact request-intent revision and out-of-scope read set it answered,
    via the same deterministic hashing ``domain/canonical.py`` already
    provides for other content-addressed artifacts.
    """
    meta = request_intent["meta"]
    artifact_id = meta["artifact_id"]
    revision = meta["revision"]
    decision_context_hash = calculate_canonical_json_hash(
        _decision_context(
            request_intent_artifact_id=artifact_id,
            request_intent_revision=revision,
            interrupt_id=interrupt_id,
            required_resource_types=required_resource_types,
            reason_codes=reason_codes,
        )
    )
    receipt_id = id_factory()
    return {
        "schema_version": 1,
        "meta": {
            "artifact_id": receipt_id,
            "revision": 1,
            "based_on": [{"artifact_id": artifact_id, "revision": revision}],
        },
        "interrupt_id": interrupt_id,
        "confirmation_kind": "SCOPE_EXPANSION",
        "decision": decision,
        "semantic_owner_id": "TOOL_ROUTE",
        "decision_context_hash": decision_context_hash,
        "affected_route_ids": affected_route_ids,
        "affected_resource_refs": list(required_resource_types),
    }


def _explicit_source_scope(
    request_intent: RequestIntentV3,
    *,
    work_unit_id: str | None = None,
) -> tuple[frozenset[str] | None, frozenset[str]]:
    required: set[str] | None = None
    forbidden: set[str] = set()
    for constraint in request_intent["constraints"]:
        if constraint["kind"] != "SCOPE":
            continue
        bound_ids = constraint.get("work_unit_ids", ())
        if work_unit_id is not None and bound_ids and work_unit_id not in bound_ids:
            continue
        value = constraint["value"]
        values = value if isinstance(value, list) else [value]
        if constraint["field"] == "required_sources":
            required = (required or set()) | {str(item) for item in values}
        elif constraint["field"] == "forbidden_sources":
            forbidden |= {str(item) for item in values}
    return (frozenset(required) if required is not None else None), frozenset(forbidden)


def _decision_context(
    *,
    request_intent_artifact_id: str,
    request_intent_revision: int,
    interrupt_id: str,
    required_resource_types: tuple[str, ...],
    reason_codes: tuple[str, ...],
) -> dict[str, object]:
    return {
        "request_intent_artifact_id": request_intent_artifact_id,
        "request_intent_revision": request_intent_revision,
        "interrupt_id": interrupt_id,
        "required_resource_types": sorted(required_resource_types),
        "reason_codes": sorted(reason_codes),
    }


__all__ = [
    "PolicyPreconditionResolutionV1",
    "ScopeExpansionResolver",
    "build_policy_confirmation_receipt",
    "effective_analysis_required",
    "policy_analysis_required",
    "resolve_policy_preconditions",
]
