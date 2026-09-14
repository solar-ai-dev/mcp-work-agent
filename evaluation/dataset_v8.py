"""Strict Canonical v8 dataset loading without Product imports."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_DATASET_PATH = Path(__file__).parent / "datasets/e2e/canonical_cases_v8.jsonl"
DEFAULT_PROVIDER_FIXTURE_PATH = (
    Path(__file__).parent / "datasets/e2e/fixtures/google_workspace/provider-snapshot-v8.json"
)


def normalized_sha256(path: Path) -> str:
    content = path.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class CanonicalCaseV8:
    raw: dict[str, Any]

    @property
    def case_id(self) -> str:
        return str(self.raw["case_id"])

    @property
    def gold(self) -> dict[str, Any]:
        value = self.raw["evaluation_gold"]
        if not isinstance(value, dict):
            raise ValueError(f"{self.case_id}: evaluation_gold must be an object")
        return value

    def execution_input(self) -> dict[str, Any]:
        allowed = {
            "case_id",
            "canonical_user_prompt",
            "entry_mode",
            "evaluation_context",
            "readiness",
            "selected_resource_bindings",
        }
        payload = {key: self.raw[key] for key in allowed if key in self.raw}
        profile = self.gold.get("fault_profile")
        if profile is not None:
            payload["fault_profile"] = profile
        if "evaluation_gold" in payload:
            raise AssertionError("evaluation Gold leaked into execution input")
        return payload

    def google_resource_scope(
        self,
        fixture_path: Path = DEFAULT_PROVIDER_FIXTURE_PATH,
    ) -> dict[str, list[str]]:
        """Return fixture-declared Google containers for public settings binding."""
        document = json.loads(fixture_path.read_text(encoding="utf-8"))
        packs = document.get("resource_packs")
        if not isinstance(packs, dict):
            raise ValueError("provider fixture resource_packs must be an object")
        result: dict[str, list[str]] = {"calendar_ids": [], "tasklist_ids": []}
        for pack_name in self.raw.get("resource_packs", []):
            pack = packs.get(pack_name)
            if not isinstance(pack, dict):
                raise ValueError(f"{self.case_id}: provider resource pack is missing: {pack_name}")
            resources = pack.get("resources")
            if not isinstance(resources, list):
                raise ValueError(f"{self.case_id}: provider resource pack is invalid: {pack_name}")
            for resource in resources:
                if not isinstance(resource, dict):
                    continue
                resource_id = resource.get("resource_id")
                resource_type = resource.get("resource_type")
                if not isinstance(resource_id, str) or not resource_id:
                    continue
                target = (
                    result["calendar_ids"]
                    if resource_type == "calendar"
                    else result["tasklist_ids"]
                    if resource_type == "task_list"
                    else None
                )
                if target is not None and resource_id not in target:
                    target.append(resource_id)
        return result


def load_cases(path: Path = DEFAULT_DATASET_PATH) -> dict[str, CanonicalCaseV8]:
    result: dict[str, CanonicalCaseV8] = {}
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"dataset line {line_number} must be an object")
        case = CanonicalCaseV8(value)
        if case.case_id in result:
            raise ValueError(f"duplicate case_id: {case.case_id}")
        result[case.case_id] = case
    if len(result) != 92:
        raise ValueError(f"Canonical v8 requires 92 cases, found {len(result)}")
    return result


__all__ = [
    "CanonicalCaseV8",
    "DEFAULT_DATASET_PATH",
    "DEFAULT_PROVIDER_FIXTURE_PATH",
    "load_cases",
    "normalized_sha256",
]
