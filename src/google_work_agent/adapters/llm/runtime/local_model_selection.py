"""Single runtime authority for installed and approved local-model selection."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from google_work_agent.ports.llm.llm_runtime_status_port import LocalModelRuntimeOptionV1
from google_work_agent.ports.llm.local_model_catalog_port import (
    InstalledLocalModelV1,
    LocalModelCatalogPort,
)
from google_work_agent.ports.llm.local_model_profile import SELECTABLE_LOCAL_MODEL_IDS
from google_work_agent.ports.llm.runtime_selection import LlmRuntimeSelectionV1
from google_work_agent.ports.llm.structured_inference_contracts import ApprovedModelInfo


@dataclass(frozen=True, slots=True)
class LocalModelSelectionResolver:
    runtime_selection: LlmRuntimeSelectionV1
    catalog: LocalModelCatalogPort
    allow_development_models: bool = False
    preferred_model_id: Callable[[], str | None] = lambda: None

    def get_approved_model(self, model_id: str) -> ApprovedModelInfo | None:
        installed_by_id = self._installed_by_id()
        return self._approved_installed_model(model_id, installed_by_id)

    def get_selected_model(self) -> ApprovedModelInfo | None:
        return self._select_model(self._installed_by_id())

    def get_model_for_prompt(self, prompt_id: str) -> ApprovedModelInfo | None:
        del prompt_id
        return self.get_selected_model()

    def list_options(self) -> tuple[LocalModelRuntimeOptionV1, ...]:
        installed_by_id = self._installed_by_id()
        ready_by_id = self._ready_by_id(installed_by_id)
        selected = self._select_model(installed_by_id)
        selected_model_id = None if selected is None else selected.model_id
        return tuple(
            LocalModelRuntimeOptionV1(
                schema_version=1,
                model_id=model_id,
                installed=model_id in installed_by_id,
                approved=model_id in ready_by_id,
                selected=model_id == selected_model_id,
            )
            for model_id in SELECTABLE_LOCAL_MODEL_IDS
        )

    def _select_model(
        self, installed_by_id: dict[str, InstalledLocalModelV1]
    ) -> ApprovedModelInfo | None:
        ready_by_id = self._ready_by_id(installed_by_id)
        if len(ready_by_id) == 1:
            return next(iter(ready_by_id.values()))
        preferred = self.preferred_model_id()
        if preferred is not None:
            return ready_by_id.get(preferred)
        return None

    def _ready_by_id(
        self, installed_by_id: dict[str, InstalledLocalModelV1]
    ) -> dict[str, ApprovedModelInfo]:
        return {
            model_id: approved
            for model_id in SELECTABLE_LOCAL_MODEL_IDS
            if (approved := self._approved_installed_model(model_id, installed_by_id)) is not None
        }

    def _approved_installed_model(
        self,
        model_id: str,
        installed_by_id: dict[str, InstalledLocalModelV1],
    ) -> ApprovedModelInfo | None:
        installed = installed_by_id.get(model_id)
        if installed is None:
            return None
        approved = self.runtime_selection.get_approved_model(model_id)
        if approved is None:
            profile = self.runtime_selection.local_model_profile
            if (
                not self.allow_development_models
                or profile is None
                or model_id not in SELECTABLE_LOCAL_MODEL_IDS
            ):
                return None
            installed_digest = (
                None
                if installed.digest is None
                else installed.digest.removeprefix("sha256:")
            )
            return ApprovedModelInfo(
                model_id=installed.model_id,
                runtime="OLLAMA",
                manifest_version="DEVELOPMENT",
                schema_version="1",
                digest=installed_digest,
            )
        installed_digest = (
            None if installed.digest is None else installed.digest.removeprefix("sha256:")
        )
        if approved.digest is not None and installed_digest != approved.digest:
            return None
        return approved

    def _installed_by_id(self) -> dict[str, InstalledLocalModelV1]:
        return {item.model_id: item for item in self.catalog.list_installed_models()}


__all__ = ["LocalModelSelectionResolver"]
