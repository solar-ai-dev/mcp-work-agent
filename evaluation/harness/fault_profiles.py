"""Resolve Canonical v8 fault profiles without importing Product internals."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = HERE / "canonical_v8_fault_profiles.json"
DEFAULT_DATASET_PATH = (
    HERE.parent / "datasets" / "e2e" / "canonical_cases_v8.jsonl"
)


@dataclass(frozen=True)
class FaultTrigger:
    kind: str
    ordinal: int | None
    prerequisite: str | None


@dataclass(frozen=True)
class FaultPersistence:
    mode: str
    max_injections: int | None
    until_checkpoint: str | None


@dataclass(frozen=True)
class FaultOutcome:
    kind: str
    safe_code: str | None
    delivery_certainty: str | None
    apply_effect_before_outcome: bool
    payload: Mapping[str, Any]


@dataclass(frozen=True)
class FaultRecovery:
    kind: str
    checkpoint: str
    max_restarts: int | None


@dataclass(frozen=True)
class FaultRule:
    rule_id: str
    boundary: str
    connector: str | None
    operations: tuple[str, ...]
    trigger: FaultTrigger
    outcome: FaultOutcome
    persistence: FaultPersistence
    recovery: FaultRecovery


@dataclass(frozen=True)
class FaultProfile:
    name: str
    expected_checkpoint: str
    unaffected_boundaries: tuple[str, ...]
    rules: tuple[FaultRule, ...]


@dataclass(frozen=True)
class FaultObservation:
    case_id: str
    boundary: str
    connector: str | None = None
    operation: str | None = None
    checkpoints: frozenset[str] = frozenset()


@dataclass(frozen=True)
class FaultDirective:
    profile_name: str
    rule_id: str
    outcome: FaultOutcome
    recovery: FaultRecovery
    injection_number: int


@dataclass(frozen=True)
class FaultInvocation:
    directive: FaultDirective | None
    delegated: bool
    effect_result: Any = None


def _required_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value


def _optional_text(value: Any, field: str) -> str | None:
    if value is None:
        return None
    return _required_text(value, field)


def _optional_positive_int(value: Any, field: str) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{field} must be a positive integer")
    return value


def _rule(value: Mapping[str, Any], profile_name: str) -> FaultRule:
    trigger = value.get("trigger")
    outcome = value.get("outcome")
    persistence = value.get("persistence")
    recovery = value.get("recovery")
    if not all(isinstance(item, dict) for item in (trigger, outcome, persistence, recovery)):
        raise ValueError(f"{profile_name}: rule contracts must be objects")
    operations = value.get("operations")
    if not isinstance(operations, list) or not operations:
        raise ValueError(f"{profile_name}: operations must be non-empty")
    payload = outcome.get("payload")
    if not isinstance(payload, dict) or not payload:
        raise ValueError(f"{profile_name}: outcome payload must be non-empty")
    return FaultRule(
        rule_id=_required_text(value.get("rule_id"), "rule_id"),
        boundary=_required_text(value.get("boundary"), "boundary"),
        connector=_optional_text(value.get("connector"), "connector"),
        operations=tuple(_required_text(item, "operation") for item in operations),
        trigger=FaultTrigger(
            kind=_required_text(trigger.get("kind"), "trigger.kind"),
            ordinal=_optional_positive_int(trigger.get("ordinal"), "trigger.ordinal"),
            prerequisite=_optional_text(
                trigger.get("prerequisite"), "trigger.prerequisite"
            ),
        ),
        outcome=FaultOutcome(
            kind=_required_text(outcome.get("kind"), "outcome.kind"),
            safe_code=_optional_text(outcome.get("safe_code"), "outcome.safe_code"),
            delivery_certainty=_optional_text(
                outcome.get("delivery_certainty"), "outcome.delivery_certainty"
            ),
            apply_effect_before_outcome=bool(
                outcome.get("apply_effect_before_outcome", False)
            ),
            payload=payload,
        ),
        persistence=FaultPersistence(
            mode=_required_text(persistence.get("mode"), "persistence.mode"),
            max_injections=_optional_positive_int(
                persistence.get("max_injections"), "persistence.max_injections"
            ),
            until_checkpoint=_optional_text(
                persistence.get("until_checkpoint"), "persistence.until_checkpoint"
            ),
        ),
        recovery=FaultRecovery(
            kind=_required_text(recovery.get("kind"), "recovery.kind"),
            checkpoint=_required_text(recovery.get("checkpoint"), "recovery.checkpoint"),
            max_restarts=_optional_positive_int(
                recovery.get("max_restarts"), "recovery.max_restarts"
            ),
        ),
    )


def load_fault_profiles(path: Path = DEFAULT_CONFIG_PATH) -> dict[str, FaultProfile]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("schema_version") != 1:
        raise ValueError("Unsupported fault profile schema")
    raw_profiles = document.get("profiles")
    if not isinstance(raw_profiles, list):
        raise ValueError("profiles must be a list")
    profiles: dict[str, FaultProfile] = {}
    for value in raw_profiles:
        if not isinstance(value, dict):
            raise ValueError("profile must be an object")
        name = _required_text(value.get("name"), "profile.name")
        rules = value.get("rules")
        unaffected = value.get("unaffected_boundaries", [])
        if name in profiles:
            raise ValueError(f"Duplicate fault profile: {name}")
        if not isinstance(rules, list) or not rules:
            raise ValueError(f"{name}: rules must be non-empty")
        if not isinstance(unaffected, list):
            raise ValueError(f"{name}: unaffected_boundaries must be a list")
        profile = FaultProfile(
            name=name,
            expected_checkpoint=_required_text(
                value.get("expected_checkpoint"), "expected_checkpoint"
            ),
            unaffected_boundaries=tuple(
                _required_text(item, "unaffected_boundary") for item in unaffected
            ),
            rules=tuple(_rule(rule, name) for rule in rules),
        )
        if len({rule.rule_id for rule in profile.rules}) != len(profile.rules):
            raise ValueError(f"{name}: duplicate rule_id")
        profiles[name] = profile
    return profiles


class FaultHarness:
    """Stateful per-case evaluator boundary; one instance never crosses cases."""

    def __init__(self, *, case_id: str, profile: FaultProfile) -> None:
        self.case_id = case_id
        self.profile = profile
        self._match_counts: dict[str, int] = {}
        self._injection_counts: dict[str, int] = {}

    @classmethod
    def for_case(
        cls,
        case_id: str,
        *,
        dataset_path: Path = DEFAULT_DATASET_PATH,
        config_path: Path = DEFAULT_CONFIG_PATH,
    ) -> FaultHarness:
        cases = _load_cases(dataset_path)
        try:
            case = cases[case_id]
        except KeyError as error:
            raise ValueError(f"Unknown canonical case: {case_id}") from error
        profile_name = case["evaluation_gold"].get("fault_profile")
        if not isinstance(profile_name, str) or not profile_name:
            raise ValueError(f"{case_id} has no fault_profile")
        profiles = load_fault_profiles(config_path)
        try:
            profile = profiles[profile_name]
        except KeyError as error:
            raise ValueError(f"Unresolved fault_profile: {profile_name}") from error
        return cls(case_id=case_id, profile=profile)

    def observe(self, observation: FaultObservation) -> FaultDirective | None:
        if observation.case_id != self.case_id:
            return None
        for rule in self.profile.rules:
            if not self._matches(rule, observation):
                continue
            matched = self._match_counts.get(rule.rule_id, 0) + 1
            self._match_counts[rule.rule_id] = matched
            if rule.trigger.ordinal is not None and matched != rule.trigger.ordinal:
                continue
            injected = self._injection_counts.get(rule.rule_id, 0)
            if (
                rule.persistence.max_injections is not None
                and injected >= rule.persistence.max_injections
            ):
                continue
            if (
                rule.persistence.until_checkpoint is not None
                and rule.persistence.until_checkpoint in observation.checkpoints
            ):
                continue
            injected += 1
            self._injection_counts[rule.rule_id] = injected
            return FaultDirective(
                profile_name=self.profile.name,
                rule_id=rule.rule_id,
                outcome=rule.outcome,
                recovery=rule.recovery,
                injection_number=injected,
            )
        return None

    def invoke(
        self,
        observation: FaultObservation,
        delegate: Callable[[], Any],
    ) -> FaultInvocation:
        """Apply pre/post-effect behavior at an evaluator-owned call boundary."""
        directive = self.observe(observation)
        if directive is None:
            return FaultInvocation(directive=None, delegated=True, effect_result=delegate())
        if directive.outcome.apply_effect_before_outcome:
            return FaultInvocation(
                directive=directive,
                delegated=True,
                effect_result=delegate(),
            )
        return FaultInvocation(directive=directive, delegated=False)

    @staticmethod
    def _matches(rule: FaultRule, observation: FaultObservation) -> bool:
        if rule.boundary != observation.boundary:
            return False
        if rule.connector is not None and rule.connector != observation.connector:
            return False
        if observation.operation not in rule.operations:
            return False
        prerequisite = rule.trigger.prerequisite
        return prerequisite is None or prerequisite in observation.checkpoints


def _load_cases(path: Path) -> dict[str, dict[str, Any]]:
    cases: dict[str, dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        case = json.loads(line)
        case_id = _required_text(case.get("case_id"), "case_id")
        if case_id in cases:
            raise ValueError(f"Duplicate canonical case: {case_id}")
        cases[case_id] = case
    return cases


def validate_canonical_stress_profiles(
    *,
    dataset_path: Path = DEFAULT_DATASET_PATH,
    config_path: Path = DEFAULT_CONFIG_PATH,
) -> list[str]:
    """Dry-validate all v8 STRESS profile bindings and a matching directive."""
    failures: list[str] = []
    try:
        cases = _load_cases(dataset_path)
        profiles = load_fault_profiles(config_path)
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as error:
        return [str(error)]
    stress = [case for case in cases.values() if case.get("split") == "STRESS"]
    names = [case.get("evaluation_gold", {}).get("fault_profile") for case in stress]
    if len(stress) != 20:
        failures.append(f"Expected 20 STRESS cases, found {len(stress)}")
    if any(not isinstance(name, str) or not name for name in names):
        failures.append("Every STRESS case must have a fault_profile")
    if len(set(names)) != len(names):
        failures.append("STRESS fault_profile names must be unique")
    if set(names) != set(profiles):
        failures.append("Dataset and config fault_profile names differ")
    for case in stress:
        case_id = str(case["case_id"])
        profile_name = case["evaluation_gold"].get("fault_profile")
        profile = profiles.get(profile_name)
        if profile is None:
            continue
        if profile.expected_checkpoint != case["evaluation_gold"].get(
            "expected_checkpoint"
        ):
            failures.append(f"{case_id}: expected_checkpoint mismatch")
        for rule in profile.rules:
            checkpoints = (
                frozenset({rule.trigger.prerequisite})
                if rule.trigger.prerequisite
                else frozenset()
            )
            observation = FaultObservation(
                case_id=case_id,
                boundary=rule.boundary,
                connector=rule.connector,
                operation=rule.operations[0],
                checkpoints=checkpoints,
            )
            harness = FaultHarness(case_id=case_id, profile=profile)
            directive: FaultDirective | None = None
            attempts = rule.trigger.ordinal or 1
            for _ in range(attempts):
                directive = harness.observe(observation)
            if directive is None or directive.rule_id != rule.rule_id:
                failures.append(f"{case_id}/{rule.rule_id}: dry trigger did not resolve")
            other = FaultObservation(
                case_id="CASE-STRESS-999",
                boundary=rule.boundary,
                connector=rule.connector,
                operation=rule.operations[0],
                checkpoints=checkpoints,
            )
            if harness.observe(other) is not None:
                failures.append(f"{case_id}/{rule.rule_id}: leaked to another case")
    return failures
