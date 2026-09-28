"""Evaluation-only local external ports around the unchanged Production Graph.

No HTTP server, MCP child, OAuth credential store, or live Provider is started.
The default is a zero-network preflight; enabling loopback model traffic is an
explicit caller decision, not authorization to run a trial or approve Actions.
"""

from __future__ import annotations

import json
import socket
import subprocess
from collections.abc import Iterator, Mapping
from contextlib import ExitStack, contextmanager
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Never, cast
from unittest.mock import patch

from evaluation.harness.stateful_provider import StatefulSimulatedProvider
from scripts.serve_canonical_v8_product import _case_resources, _simulated_read_result

from google_work_agent.adapters.connectors.runtime.connector_runtime_registry import (
    ConnectorRuntimeRegistry,
)
from google_work_agent.adapters.llm.runtime.llm_credential_router import SessionMemorySecretStore
from google_work_agent.api import composition
from google_work_agent.ports.connector.mcp_client_port import (
    MCPRestartResultV1,
    MCPRuntimeMetadata,
)
from google_work_agent.ports.connector.oauth_credential_port import (
    OAuthConnectionMetadata,
    OAuthEnvironment,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATASET = PROJECT_ROOT / "evaluation/datasets/e2e/canonical_cases_v8.jsonl"


class SnapshotSafetyError(RuntimeError):
    """A boundary not authorized by this local experiment was requested."""


@dataclass
class SnapshotBoundary:
    case: Mapping[str, Any]
    registry: Any
    resources: list[dict[str, Any]] = field(init=False)
    provider: StatefulSimulatedProvider = field(init=False)
    events: list[dict[str, Any]] = field(default_factory=list)
    read_results: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.resources = _case_resources(self.case)
        self.provider = StatefulSimulatedProvider(
            initial_resources=self.resources, read_result_factory=_simulated_read_result
        )
        for selected in self.case.get("selected_resource_bindings", []):
            identity = (
                selected.get("resource_type"),
                selected.get("resource_id"),
                selected.get("parent_id"),
            )
            matches = [
                item
                for item in self.resources
                if (item["resource_type"], item["resource_id"], item.get("parent_id")) == identity
            ]
            if len(matches) != 1 or not matches[0]["payload"]:
                raise SnapshotSafetyError("selected identity has no complete local snapshot")

    @property
    def account_id(self) -> str:
        selections = self.case.get("selected_resource_bindings", [])
        accounts = {item["account_email"] for item in selections}
        if len(accounts) != 1:
            raise SnapshotSafetyError("one fixture-bound selected account is required")
        return str(next(iter(accounts)))

    def deny(self, boundary: str, *args: Any, **kwargs: Any) -> Never:
        del args, kwargs
        self.events.append({"boundary": boundary, "decision": "DENY"})
        raise SnapshotSafetyError(boundary)

    def execute_read(self, binding: Any, tool_arguments: dict[str, Any]) -> Any:
        if binding.connector_id != "google_workspace" or binding.effect != "READ":
            return self.deny("non_fixture_connector_read")
        expected = self.registry.bind_required(binding.connector_id, binding.tool_id, "READ")
        if expected != binding:
            return self.deny("registry_binding_mismatch")
        self.events.append({"boundary": "snapshot_read", "tool_id": binding.tool_id})
        # Unsupported tools raise; there is deliberately no delegate fallback.
        record: dict[str, Any] = {
            "tool_id": binding.tool_id,
            "arguments": deepcopy(tool_arguments),
        }
        self.read_results.append(record)
        try:
            result = self.provider.execute_read(binding, tool_arguments)
        except Exception as exc:
            record["error_type"] = type(exc).__name__
            raise
        record["result"] = asdict(result)
        return result

    def execute_write(self, *args: Any, **kwargs: Any) -> Any:
        return self.deny("provider_write_dispatch", *args, **kwargs)

    def get_connection_status(self, connector_id: str) -> OAuthConnectionMetadata:
        if connector_id not in {"google_workspace", "github"}:
            return self.deny("unknown_auth_connector")
        self.events.append({"boundary": "local_auth_status", "connector_id": connector_id})
        connected = connector_id == "google_workspace"
        return OAuthConnectionMetadata(
            1,
            connector_id,
            self.account_id if connected else None,
            self.account_id if connected else None,
            "CONNECTED" if connected else "DISCONNECTED",
            tuple(
                sorted(
                    {
                        scope
                        for entry in self.registry.entries
                        if entry.connector_id == connector_id
                        for scope in entry.required_scopes
                    }
                )
            )
            if connected
            else (),
            (),
        )

    def __getattr__(self, name: str) -> Any:
        if name in {
            "start_authorization",
            "refresh_access",
            "revoke_connection",
            "reconcile_authorization_start",
            "reconcile_revoke_connection",
        }:
            return lambda *args, **kwargs: self.deny("oauth_mutation", *args, **kwargs)
        raise AttributeError(name)


class _LocalRuntime:
    def __init__(self, boundary: SnapshotBoundary, connector_id: str, version: str) -> None:
        self.boundary, self.connector_id, self.version = boundary, connector_id, version

    def runtime_metadata(self) -> MCPRuntimeMetadata:
        return MCPRuntimeMetadata(
            "READY",
            self.version,
            self.version,
            self.boundary.registry.contract_version,
            len(self.list_tools()),
            None,
            0,
            f"snapshot-{self.connector_id}",
        )

    def list_tools(self, connector_id: str | None = None) -> list[Any]:
        return list(
            self.boundary.registry.descriptor_expectations(connector_id or self.connector_id)
        )

    def process_instance_id(self, connector_id: str) -> str:
        return f"snapshot-{connector_id}"

    def call_tool(self, *args: Any, **kwargs: Any) -> Any:
        return self.boundary.deny("mcp_dispatch", *args, **kwargs)

    def sign_claim_context(self, *args: Any, **kwargs: Any) -> Any:
        return self.boundary.deny("write_claim", *args, **kwargs)

    def restart_once(self, *args: Any) -> MCPRestartResultV1:
        del args
        return MCPRestartResultV1(1, False, "SNAPSHOT_NO_PROCESS")

    def close(self) -> None:
        pass


def load_case(case_id: str) -> dict[str, Any]:
    rows = [json.loads(line) for line in DATASET.read_text(encoding="utf-8").splitlines()]
    matches = [row for row in rows if row["case_id"] == case_id]
    if len(matches) != 1:
        raise ValueError("case identity must resolve exactly once")
    return cast(dict[str, Any], matches[0])


@contextmanager
def snapshot_production_runtime(
    runtime_root: Path,
    *,
    case_id: str = "CASE-CORE-005",
    allow_loopback_model: bool = False,
    llm_provider_decorator: Any = None,
    sampling_seed: int | None = None,
) -> Iterator[tuple[Any, SnapshotBoundary]]:
    """Build actual Main Graph/SQLite owners with isolated external boundaries.

    This context is process-global and must run in its own evaluation process.
    Model-enabled trials retain the Product's read-only GPU probes; no other
    process is allowed. Hardware eligibility is never fabricated here.
    Callers retain the existing StartRun -> durable handoff -> schedule path.
    No run, startup loop, approval, or model inference is submitted here.
    """
    root = runtime_root.resolve()
    results = (PROJECT_ROOT / "evaluation/results").resolve()
    if not root.is_relative_to(results) or root == results:
        raise ValueError("runtime must be inside a dedicated evaluation/results directory")
    if root.exists() and any(root.iterdir()):
        raise ValueError("runtime directory must be empty; existing DB/settings are preserved")
    case = load_case(case_id)
    if case["evaluation_gold"]["fault_profile"] is not None:
        raise ValueError("fault profiles require their separately registered harness")
    registry = composition.load_development_tool_registry()
    boundary = SnapshotBoundary(case, registry)
    _ = boundary.account_id

    def local_bundle(**kwargs: Any) -> composition.DevelopmentConnectorBundle:
        if kwargs["configuration_source"] != "EXPLICIT_DEVELOPMENT":
            raise SnapshotSafetyError("signed_release_not_supported")
        runtime_registry = ConnectorRuntimeRegistry()
        connectors: dict[str, Any] = {}
        for connector_id in ("google_workspace", "github"):
            handle = _LocalRuntime(boundary, connector_id, kwargs["mcp_manifest_version"])
            runtime_registry.register(connector_id, handle)
            connectors[connector_id] = SimpleNamespace(
                connector_id=connector_id,
                client=handle,
                oauth_port=boundary,
                read_port=boundary,
                write_port=boundary,
                descriptor=SimpleNamespace(
                    artifact_config=SimpleNamespace(
                        manifest_path=str(kwargs["mcp_manifest_path"]),
                        executable_path=str(kwargs["python_executable"]),
                    )
                ),
            )
        return composition.DevelopmentConnectorBundle(
            runtime_registry, registry, composition.load_installed_connector_manifest(), connectors
        )

    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex
    original_getaddrinfo = socket.getaddrinfo
    original_popen = subprocess.Popen

    def permitted(address: Any) -> bool:
        return (
            allow_loopback_model
            and isinstance(address, tuple)
            and len(address) >= 2
            and address[0] in {"127.0.0.1", "::1"}
            and address[1] == 11434
        )

    def connect(sock: Any, address: Any) -> Any:
        if not permitted(address):
            return boundary.deny("network_connect")
        return original_connect(sock, address)

    def connect_ex(sock: Any, address: Any) -> Any:
        if not permitted(address):
            return boundary.deny("network_connect")
        return original_connect_ex(sock, address)

    def getaddrinfo(host: str, port: int, *args: Any, **kwargs: Any) -> Any:
        if not permitted((host, port)):
            return boundary.deny("network_resolve")
        return original_getaddrinfo(host, port, *args, **kwargs)

    def popen(args: Any, *positional: Any, **kwargs: Any) -> Any:
        permitted_probes = (
            ("nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"),
            (
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "Get-CimInstance Win32_VideoController | "
                "Select-Object Name,AdapterRAM | ConvertTo-Json -Compress",
            ),
        )
        if (
            allow_loopback_model
            and isinstance(args, (list, tuple))
            and tuple(args) in permitted_probes
            and not positional
            and not kwargs.get("shell")
            and kwargs.get("executable") is None
        ):
            boundary.events.append({"boundary": "local_hardware_probe", "command": args[0]})
            return original_popen(args, **kwargs)
        return boundary.deny("process")

    with ExitStack() as stack:
        stack.enter_context(patch.object(composition, "_build_connectors", local_bundle))
        for cls in (composition.GoogleWorkspaceConnector, composition.GitHubConnector):
            stack.enter_context(
                patch.object(cls, "start", lambda *a, **k: boundary.deny("live_start"))
            )
        stack.enter_context(
            patch.object(
                composition, "OsKeyringSecretStoreAdapter", lambda **kw: boundary.deny("keyring")
            )
        )
        stack.enter_context(patch.object(subprocess, "Popen", popen))
        stack.enter_context(patch.object(socket.socket, "connect", connect))
        stack.enter_context(patch.object(socket.socket, "connect_ex", connect_ex))
        stack.enter_context(patch.object(socket, "getaddrinfo", getaddrinfo))
        container = composition.build_production_runtime(
            runtime_root=root,
            working_directory=PROJECT_ROOT,
            mcp_manifest_version="2026-08-07.p0",
            bootstrap_secret="snapshot-evaluation-only",
            service_instance_id="snapshot-evaluation",
            release_version="evaluation-snapshot",
            build_channel="TEST",
            deployment_profile="LOCAL_CAPABLE",
            oauth_environment=OAuthEnvironment.DEVELOPMENT,
            oauth_client_id="not-used",
            github_oauth_client_id=None,
            github_oauth_scope="",
            api_contract_version="1",
            policy_version=registry.contract_version,
            database_migration_version="development-latest",
            configuration_source="EXPLICIT_DEVELOPMENT",
            development_sampling_seed=sampling_seed,
            keyring_store=SessionMemorySecretStore(),
            development_runtime_bindings=composition.DevelopmentRuntimeBindings(
                connector_read_decorator=lambda _delegate: boundary,
                connector_write_decorator=lambda _delegate: boundary,
                llm_provider_decorator=llm_provider_decorator,
            ),
        )
        try:
            yield container, boundary
        finally:
            for close in container.shutdown_callbacks:
                close()
