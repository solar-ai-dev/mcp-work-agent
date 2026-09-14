"""Build the canonical Windows x64 executable distributions with PyInstaller."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "build" / "windows-executables"


@dataclass(frozen=True, slots=True)
class _PackageData:
    source: str
    destination: str


@dataclass(frozen=True, slots=True)
class _ExecutableTarget:
    executable_name: str
    distribution_path: str
    entrypoint: str
    console: bool
    collect_submodules: tuple[str, ...] = ()
    package_data: tuple[_PackageData, ...] = ()


_SERVICE_PACKAGE_DATA = (
    _PackageData(
        "src/google_work_agent/adapters/persistence/migrations",
        "google_work_agent/adapters/persistence/migrations",
    ),
    _PackageData(
        "src/google_work_agent/application/prompt_runtime",
        "google_work_agent/application/prompt_runtime",
    ),
    _PackageData(
        "src/google_work_agent/application/tool_registry/tool_registry_manifest.json",
        "google_work_agent/application/tool_registry",
    ),
    _PackageData(
        "src/google_work_agent/adapters/connectors/runtime/installed_connector_manifest.json",
        "google_work_agent/adapters/connectors/runtime",
    ),
    _PackageData(
        "src/google_work_agent/adapters/connectors/google/workspace/mcp_server/"
        "tool_descriptor_projection.json",
        "google_work_agent/adapters/connectors/google/workspace/mcp_server",
    ),
    _PackageData(
        "src/google_work_agent/adapters/connectors/github/github/mcp_server/"
        "tool_descriptor_projection.json",
        "google_work_agent/adapters/connectors/github/github/mcp_server",
    ),
)
_GOOGLE_MCP_PACKAGE_DATA = (
    _PackageData(
        "src/google_work_agent/adapters/connectors/google/workspace/mcp_server/"
        "tool_descriptor_projection.json",
        "google_work_agent/adapters/connectors/google/workspace/mcp_server",
    ),
)
_GITHUB_MCP_PACKAGE_DATA = (
    _PackageData(
        "src/google_work_agent/adapters/connectors/github/github/mcp_server/"
        "tool_descriptor_projection.json",
        "google_work_agent/adapters/connectors/github/github/mcp_server",
    ),
)
_TARGETS = (
    _ExecutableTarget(
        executable_name="GoogleWorkAgentLauncher",
        distribution_path="launcher-dist",
        entrypoint="from launcher.entrypoint import main\nraise SystemExit(main())\n",
        console=False,
    ),
    _ExecutableTarget(
        executable_name="GoogleWorkAgentService",
        distribution_path="service-dist",
        entrypoint=(
            "from google_work_agent.api.app import _run_installed_service\n"
            "raise SystemExit(_run_installed_service())\n"
        ),
        console=True,
        collect_submodules=(
            "fastapi",
            "google_work_agent",
            "keyring.backends",
            "langgraph",
            "uvicorn",
        ),
        package_data=_SERVICE_PACKAGE_DATA,
    ),
    _ExecutableTarget(
        executable_name="GoogleWorkspaceMcpServer",
        distribution_path="mcp-dist/google_workspace",
        entrypoint=(
            "from google_work_agent.adapters.connectors.google.workspace.mcp_server."
            "entrypoint import main\nmain()\n"
        ),
        console=True,
        collect_submodules=(
            "google_work_agent.adapters.connectors.google.workspace",
            "keyring.backends",
        ),
        package_data=_GOOGLE_MCP_PACKAGE_DATA,
    ),
    _ExecutableTarget(
        executable_name="GitHubMcpServer",
        distribution_path="mcp-dist/github",
        entrypoint=(
            "from google_work_agent.adapters.connectors.github.github.mcp_server."
            "entrypoint import github_mcp_main\ngithub_mcp_main()\n"
        ),
        console=True,
        collect_submodules=(
            "google_work_agent.adapters.connectors.github.github",
            "keyring.backends",
        ),
        package_data=_GITHUB_MCP_PACKAGE_DATA,
    ),
    _ExecutableTarget(
        executable_name="GoogleWorkAgentCredentialCleanup",
        distribution_path="uninstaller-dist",
        entrypoint=(
            "from installer.windows.cleanup_credentials import main\n"
            "raise SystemExit(main())\n"
        ),
        console=False,
        collect_submodules=("keyring.backends",),
    ),
)
_COPY_METADATA = (
    "cryptography",
    "fastapi",
    "keyring",
    "langgraph",
    "langgraph-checkpoint-sqlite",
    "tzdata",
    "uvicorn",
)
_COLLECT_DATA = ("tzdata",)
_ALLOWED_PACKAGE_DATA_SUFFIXES = frozenset({".json", ".md", ".sql"})


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build mcp-work-agent Windows executable distributions"
    )
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    arguments = parser.parse_args(argv)
    _require_build_environment()
    output_root = arguments.output_root.resolve()
    _require_empty_destination(output_root)
    output_root.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(
        prefix="gwa-windows-executables-", dir=output_root.parent
    ) as temporary:
        temporary_root = Path(temporary)
        staged_output = temporary_root / "output"
        staged_output.mkdir()
        for target in _TARGETS:
            _build_target(target, temporary_root=temporary_root, output_root=staged_output)
        _validate_output(staged_output)
        if output_root.exists():
            output_root.rmdir()
        staged_output.replace(output_root)

    for target in _TARGETS:
        executable = output_root / Path(target.distribution_path) / (
            f"{target.executable_name}.exe"
        )
        payload = {
            "path": str(executable),
            "size": executable.stat().st_size,
            "sha256": _sha256(executable),
        }
        print(json.dumps(payload, sort_keys=True))
    print(
        "release_dist_arguments="
        f'--launcher-dist "{output_root / "launcher-dist"}" '
        f'--service-dist "{output_root / "service-dist"}" '
        f'--mcp-dist "{output_root / "mcp-dist"}" '
        f'--uninstaller-dist "{output_root / "uninstaller-dist"}"'
    )
    return 0


def _require_build_environment() -> None:
    if sys.platform != "win32":
        raise RuntimeError("Windows executable builds require Windows")
    if sys.version_info[:2] != (3, 12):
        raise RuntimeError("Windows executable builds require Python 3.12")
    if platform.machine().upper() not in {"AMD64", "X86_64"}:
        raise RuntimeError("Windows executable builds require x64 Python")
    try:
        version = importlib.metadata.version("pyinstaller")
    except importlib.metadata.PackageNotFoundError as error:
        raise RuntimeError(
            'PyInstaller is unavailable; install the "windows-build" project extra'
        ) from error
    major = int(version.partition(".")[0])
    if not 6 <= major < 7:
        raise RuntimeError("Windows executable builds require PyInstaller 6.x")


def _require_empty_destination(output_root: Path) -> None:
    if output_root == REPO_ROOT or output_root == Path(output_root.anchor):
        raise ValueError("output root is too broad")
    if output_root.exists() and (not output_root.is_dir() or any(output_root.iterdir())):
        raise ValueError("output root must be absent or empty")


def _build_target(
    target: _ExecutableTarget,
    *,
    temporary_root: Path,
    output_root: Path,
) -> None:
    target_key = target.distribution_path.replace("/", "-")
    target_root = temporary_root / target_key
    wrapper = target_root / "entrypoint.py"
    wrapper.parent.mkdir(parents=True)
    wrapper.write_text(target.entrypoint, encoding="utf-8", newline="\n")
    dist_root = target_root / "dist"
    (target_root / "spec").mkdir()
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--onedir",
        "--noupx",
        "--name",
        target.executable_name,
        "--distpath",
        str(dist_root),
        "--workpath",
        str(target_root / "work"),
        "--specpath",
        str(target_root / "spec"),
        "--paths",
        str(REPO_ROOT),
        "--paths",
        str(SRC_ROOT),
        "--console" if target.console else "--windowed",
    ]
    for package in target.collect_submodules:
        command.extend(("--collect-submodules", package))
    for distribution in _COPY_METADATA:
        command.extend(("--copy-metadata", distribution))
    for package in _COLLECT_DATA:
        command.extend(("--collect-data", package))
    for source, destination in _resolve_package_data(target.package_data):
        command.extend(("--add-data", f"{source};{destination}"))
    command.append(str(wrapper))
    subprocess.run(command, cwd=REPO_ROOT, check=True, shell=False)

    built = dist_root / target.executable_name
    destination = output_root / Path(target.distribution_path)
    if not (built / f"{target.executable_name}.exe").is_file():
        raise RuntimeError(f"PyInstaller did not create {target.executable_name}.exe")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(built), str(destination))


def _resolve_package_data(
    package_data: tuple[_PackageData, ...],
) -> tuple[tuple[Path, str], ...]:
    resolved: list[tuple[Path, str]] = []
    for declaration in package_data:
        source = (REPO_ROOT / declaration.source).resolve()
        try:
            source.relative_to(REPO_ROOT)
        except ValueError as error:
            raise ValueError("package data escaped repository") from error
        if source.is_file():
            if source.suffix.lower() not in _ALLOWED_PACKAGE_DATA_SUFFIXES:
                raise ValueError(f"unsupported package data: {source.name}")
            resolved.append((source, declaration.destination))
            continue
        if not source.is_dir():
            raise FileNotFoundError(f"package data is missing: {source}")
        for path in sorted(source.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in _ALLOWED_PACKAGE_DATA_SUFFIXES:
                continue
            relative_parent = path.relative_to(source).parent
            destination = Path(declaration.destination) / relative_parent
            resolved.append((path, destination.as_posix()))
    return tuple(resolved)


def _validate_output(output_root: Path) -> None:
    for target in _TARGETS:
        executable = output_root / Path(target.distribution_path) / (
            f"{target.executable_name}.exe"
        )
        if not executable.is_file() or executable.stat().st_size == 0:
            raise RuntimeError(f"required executable is missing: {executable.name}")
    for path in output_root.rglob("*"):
        if not path.is_file():
            continue
        lowered = path.name.lower()
        if lowered.startswith(".env") or "client_secret" in lowered:
            raise RuntimeError(f"sensitive build input was packaged: {path.name}")
        if path.suffix.lower() in {".py", ".pyc", ".jsonl"}:
            raise RuntimeError(f"forbidden source or evaluation artifact was packaged: {path.name}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
