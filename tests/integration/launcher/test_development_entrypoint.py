from __future__ import annotations

import ast
import importlib
import json
import os
import stat
import subprocess
import sys
import time
from http.cookiejar import CookieJar
from pathlib import Path
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit
from urllib.request import HTTPCookieProcessor, Request, build_opener

import pytest
from launcher.development_entrypoint import (
    main,
    read_development_langsmith_environment,
    read_development_sampling_environment,
)

ROOT = Path(__file__).resolve().parents[3]


def test_development_langsmith__explicit_safe_configuration__is_required() -> None:
    trace_environment = {
        "GWA_LANGSMITH_CODE_SHA": "a" * 40,
        "GWA_LANGSMITH_EXPERIMENT_ID": "issue251-read-only-6run",
        "GWA_LANGSMITH_MODEL_DIGEST": "b" * 64,
        "GWA_LANGSMITH_MODEL_ID": "qwen3.5:9b",
        "GWA_LANGSMITH_PROMPT_CONTENT_HASH": "c" * 64,
        "GWA_LANGSMITH_PROMPT_ID": "request_understanding.identify_goal",
        "GWA_LANGSMITH_PROMPT_VERSION": "1.0.50",
        "GWA_LANGSMITH_QUESTION_ID": "Q1",
    }
    assert read_development_langsmith_environment({}) == (None, None, {})
    assert read_development_langsmith_environment(
        {
            "GWA_LANGSMITH_ENABLED": "true",
            "LANGSMITH_API_KEY": "secret-key",
            "LANGSMITH_PROJECT": "quality-development",
            **trace_environment,
        }
    ) == (
        "secret-key",
        "quality-development",
        {
            "code_sha": "a" * 40,
            "experiment_id": "issue251-read-only-6run",
            "model_digest": "b" * 64,
            "model_id": "qwen3.5:9b",
            "prompt_content_hash": "c" * 64,
            "prompt_id": "request_understanding.identify_goal",
            "prompt_version": "1.0.50",
            "question_id": "Q1",
        },
    )

    with pytest.raises(ValueError, match="requires LANGSMITH_API_KEY"):
        read_development_langsmith_environment({"GWA_LANGSMITH_ENABLED": "true"})
    with pytest.raises(ValueError, match="complete experiment binding"):
        read_development_langsmith_environment(
            {
                "GWA_LANGSMITH_ENABLED": "true",
                "LANGSMITH_API_KEY": "secret-key",
            }
        )
    with pytest.raises(ValueError, match="automatic LangSmith tracing"):
        read_development_langsmith_environment({"LANGSMITH_TRACING": "true"})
    with pytest.raises(ValueError, match="automatic LangSmith tracing"):
        read_development_langsmith_environment({"LANGCHAIN_TRACING_V2": "1"})


def test_development_config__ambient_github_values__requires_explicit_handoff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from google_work_agent.api.composition import ProductionRuntimeConfig

    monkeypatch.setenv("GITHUB_APP_CLIENT_ID", "ambient-client")
    monkeypatch.setenv("GITHUB_APP_SCOPE", "ambient-scope")
    base = ProductionRuntimeConfig.development(
        runtime_root=tmp_path, working_directory=ROOT, mcp_manifest_version="test",
    )
    assert base.github_oauth_client_id is None
    assert base.github_oauth_scope == ""
    explicit = ProductionRuntimeConfig.development(
        runtime_root=tmp_path, working_directory=ROOT, mcp_manifest_version="test",
        github_oauth_client_id=" explicit-client ", github_oauth_scope=" explicit-scope ",
    )
    assert explicit.github_oauth_client_id == "explicit-client"
    assert explicit.github_oauth_scope == "explicit-scope"
    from scripts.run_development import development_runtime_config

    handed_off = development_runtime_config(runtime_root=tmp_path)
    assert handed_off.github_oauth_client_id == "ambient-client"
    assert handed_off.github_oauth_scope == "ambient-scope"


def test_development_config__ambient_google_client_id__requires_explicit_handoff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from google_work_agent.api.composition import ProductionRuntimeConfig

    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "ambient-google-client")
    direct = ProductionRuntimeConfig.development(
        runtime_root=tmp_path,
        working_directory=ROOT,
        mcp_manifest_version="test",
    )
    assert direct.oauth_client_id == "development-client-id"

    from scripts.run_development import development_runtime_config

    handed_off = development_runtime_config(runtime_root=tmp_path)
    assert handed_off.oauth_client_id == "ambient-google-client"


def test_development_config__langsmith_secret__requires_explicit_complete_handoff(
    tmp_path: Path,
) -> None:
    from google_work_agent.api.composition import ProductionRuntimeConfig

    config = ProductionRuntimeConfig.development(
        runtime_root=tmp_path,
        working_directory=ROOT,
        mcp_manifest_version="test",
        langsmith_api_key=" secret-key ",
        langsmith_project_name=" quality-development ",
        langsmith_trace_binding={
            "code_sha": "a" * 40,
            "experiment_id": "issue251-read-only-6run",
            "model_digest": "b" * 64,
            "model_id": "qwen3.5:9b",
            "prompt_content_hash": "c" * 64,
            "prompt_id": "request_understanding.identify_goal",
            "prompt_version": "1.0.50",
            "question_id": "Q1",
        },
    )

    assert config.langsmith_api_key == "secret-key"
    assert config.langsmith_project_name == "quality-development"
    assert dict(config.langsmith_trace_binding)["question_id"] == "Q1"
    assert "secret-key" not in repr(config)
    with pytest.raises(ValueError, match="configured together"):
        ProductionRuntimeConfig.development(
            runtime_root=tmp_path,
            working_directory=ROOT,
            mcp_manifest_version="test",
            langsmith_api_key="secret-key",
        )


def test_development_script__missing_github_environment__uses_repository_app_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from launcher.development_entrypoint import DEVELOPMENT_GITHUB_APP_CLIENT_ID
    from scripts.run_development import development_runtime_config

    monkeypatch.delenv("GITHUB_APP_CLIENT_ID", raising=False)

    config = development_runtime_config(runtime_root=tmp_path)

    assert config.github_oauth_client_id == DEVELOPMENT_GITHUB_APP_CLIENT_ID


def test_development_config__prompt_manifest__requires_explicit_handoff(
    tmp_path: Path,
) -> None:
    from scripts.run_development import development_runtime_config

    from google_work_agent.api.composition import ProductionRuntimeConfig

    manifest_path = tmp_path / "candidate" / "prompt_manifest.json"
    direct = ProductionRuntimeConfig.development(
        runtime_root=tmp_path / "runtime",
        working_directory=ROOT,
        mcp_manifest_version="test",
        prompt_manifest_path=manifest_path,
    )
    handed_off = development_runtime_config(
        runtime_root=tmp_path / "runtime-2",
        prompt_manifest_path=manifest_path,
    )

    assert direct.development_prompt_manifest_path == manifest_path.resolve()
    assert handed_off.development_prompt_manifest_path == manifest_path.resolve()


def test_development_config__sampling_policy__requires_explicit_handoff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts.run_development import development_runtime_config

    from google_work_agent.api.composition import ProductionRuntimeConfig

    monkeypatch.setenv("GWA_DEVELOPMENT_LLM_TEMPERATURE", "0.2")
    monkeypatch.setenv("GWA_DEVELOPMENT_LLM_SEED", "1729")
    direct = ProductionRuntimeConfig.development(
        runtime_root=tmp_path / "direct",
        working_directory=ROOT,
        mcp_manifest_version="test",
    )
    handed_off = development_runtime_config(runtime_root=tmp_path / "runner")

    assert direct.development_sampling_temperature is None
    assert direct.development_sampling_seed is None
    assert handed_off.development_sampling_temperature == 0.2
    assert handed_off.development_sampling_seed == 1729


def test_development_sampling_environment__parses_explicit_values__without_defaults() -> None:
    assert read_development_sampling_environment({}) == (None, None)
    assert read_development_sampling_environment(
        {
            "GWA_DEVELOPMENT_LLM_TEMPERATURE": " 0.2 ",
            "GWA_DEVELOPMENT_LLM_SEED": " 1729 ",
        }
    ) == (0.2, 1729)
    with pytest.raises(ValueError, match="temperature"):
        read_development_sampling_environment({"GWA_DEVELOPMENT_LLM_TEMPERATURE": "warm"})
    with pytest.raises(ValueError, match="seed"):
        read_development_sampling_environment({"GWA_DEVELOPMENT_LLM_SEED": "fixed"})


def test_development_config__sampling_policy__rejects_invalid_values(tmp_path: Path) -> None:
    from google_work_agent.api.composition import ProductionRuntimeConfig

    with pytest.raises(ValueError, match="temperature"):
        ProductionRuntimeConfig.development(
            runtime_root=tmp_path,
            working_directory=ROOT,
            mcp_manifest_version="test",
            sampling_temperature=2.1,
        )
    with pytest.raises(ValueError, match="seed"):
        ProductionRuntimeConfig.development(
            runtime_root=tmp_path,
            working_directory=ROOT,
            mcp_manifest_version="test",
            sampling_seed=-1,
        )


def test_development_entrypoint__imports_and_rejects__non_loopback_bind() -> None:
    module = importlib.import_module("launcher.development_entrypoint")

    assert callable(module.main)
    with pytest.raises(ValueError, match="127.0.0.1"):
        main(["--host", "0.0.0.0"])


def test_development_launcher__reuses_product_composition__without_second_root() -> None:
    path = ROOT / "launcher/development_entrypoint.py"
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    constructed = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }

    assert "ProductionRuntimeConfig.development" in source
    assert source.count("create_app(") == 1
    assert "build_production_runtime(" not in source
    assert "DeferredApiContainer(" not in source
    assert "ApiContainer(" not in source
    assert not {name for name in constructed if name.endswith(("Handler", "Registry"))}
    assert {
        path
        for path in (ROOT / "src/google_work_agent").rglob("*.py")
        if "def build_production_runtime(" in path.read_text(encoding="utf-8")
    } == {ROOT / "src/google_work_agent/api/composition.py"}


def test_development_commands__contain_zero_stale__module_references() -> None:
    candidates = [ROOT / "README.md", ROOT / ".claude/launch.json"]
    candidates.extend((ROOT / "docs/canonical").rglob("*.md"))
    offenders = [
        path
        for path in candidates
        if "google_work_agent.launcher.dev" in path.read_text(encoding="utf-8")
    ]

    assert offenders == []


def test_development_process__serves_authenticated_product__and_cleans_descriptor(
    tmp_path: Path,
) -> None:
    descriptor = tmp_path / "development-launch.json"
    runtime_root = tmp_path / "runtime"
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "launcher.development_entrypoint",
            "--runtime-root",
            str(runtime_root),
            "--port",
            "0",
            "--no-browser",
            "--launch-descriptor",
            str(descriptor),
            "--startup-timeout",
            "30",
        ],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    output = ""
    bootstrap_secret = ""
    try:
        launch = _wait_for_descriptor(descriptor, process)
        base_url = cast(str, launch["base_url"])
        bootstrap_url = cast(str, launch["bootstrap_url"])
        bootstrap_secret = parse_qs(urlsplit(bootstrap_url).fragment)["bootstrap_secret"][0]
        service_instance_id = cast(str, launch["service_instance_id"])

        assert urlsplit(base_url).hostname == "127.0.0.1"
        assert cast(int, urlsplit(base_url).port) > 0
        assert launch["readiness_state"] == "READY"
        assert isinstance(launch["process_id"], int)
        assert launch["process_id"] > 0
        _assert_owner_only(descriptor)

        cookie_jar = CookieJar()
        opener = build_opener(HTTPCookieProcessor(cookie_jar))
        ready = _request_json(opener, f"{base_url}/health/ready")
        assert ready["status"] == "READY"

        with opener.open(f"{base_url}/", timeout=5) as response:
            frontend = response.read().decode("utf-8")
        assert response.status == 200
        assert '<div id="root"></div>' in frontend

        bootstrap = _request_json(
            opener,
            f"{base_url}/api/v1/session/bootstrap",
            method="POST",
            base_url=base_url,
            payload={
                "schema_version": 1,
                "bootstrap_secret": bootstrap_secret,
                "frontend_api_contract_version": "1",
            },
        )
        assert bootstrap["session_established"] is True
        assert bootstrap["service_instance_id"] == service_instance_id
        assert len(cookie_jar) == 1

        runtime = _request_json(
            opener,
            f"{base_url}/api/v1/runtime",
            base_url=base_url,
        )
        assert runtime["schema_version"] == 1
        assert runtime["session_status"] == "ESTABLISHED"

        shutdown = _request_json(
            opener,
            f"{base_url}/api/v1/control/shutdown",
            method="POST",
            base_url=base_url,
            payload={"schema_version": 1, "command_id": "development-process-test"},
        )
        assert shutdown == {"schema_version": 1, "accepted": True}
        output = "\n".join(process.communicate(timeout=20))
        assert process.returncode == 0
        assert not descriptor.exists()
        assert bootstrap_secret not in output
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                output = "\n".join(process.communicate(timeout=10))
            except subprocess.TimeoutExpired:
                process.kill()
                output = "\n".join(process.communicate(timeout=10))
        descriptor.unlink(missing_ok=True)


def _wait_for_descriptor(path: Path, process: subprocess.Popen[str]) -> dict[str, Any]:
    deadline = time.monotonic() + 40
    while time.monotonic() < deadline:
        if path.is_file():
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                return cast(dict[str, Any], payload)
        if process.poll() is not None:
            stdout, stderr = process.communicate(timeout=5)
            raise AssertionError(f"launcher exited before descriptor: {stdout}\n{stderr}")
        time.sleep(0.05)
    raise AssertionError("development launch descriptor was not created")


def _request_json(
    opener: Any,
    url: str,
    *,
    method: str = "GET",
    base_url: str | None = None,
    payload: dict[str, object] | None = None,
) -> dict[str, Any]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Accept": "application/json"}
    if base_url is not None:
        headers.update(
            {
                "Origin": base_url,
                "Sec-Fetch-Site": "same-origin",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Dest": "empty",
                "X-Api-Contract-Version": "1",
            }
        )
    if body is not None:
        headers["Content-Type"] = "application/json"
    request = Request(url, data=body, headers=headers, method=method)
    with opener.open(request, timeout=10) as response:
        result = json.loads(response.read().decode("utf-8"))
    assert isinstance(result, dict)
    return cast(dict[str, Any], result)


def _assert_owner_only(path: Path) -> None:
    if os.name != "nt":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        return
    identity = subprocess.run(
        ["whoami"],
        check=True,
        capture_output=True,
        timeout=5,
    ).stdout.decode("utf-8").strip().lower()
    result = subprocess.run(
        ["icacls", str(path)],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    acl = result.stdout.lower()
    entries = [line for line in acl.splitlines() if ":(" in line]
    assert len(entries) == 2
    assert any(identity in line for line in entries)
    assert any("system" in line for line in entries)
    assert "(i)" not in acl
