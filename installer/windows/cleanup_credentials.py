"""Delete product-owned credentials and invalidate local runtime sessions on uninstall."""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import re
import sys
from collections.abc import Sequence
from ctypes import wintypes
from pathlib import Path

from installer.windows.uninstall_definition import WindowsUninstallDefinition
from launcher.release_build_config import load_signed_build_config
from launcher.verify_installation import verify_installation

from google_work_agent.adapters.connectors.google.workspace.mcp_server.credential_provider import (
    GOOGLE_REFRESH_TOKEN_ACCOUNT,
)
from google_work_agent.adapters.keyring.os_keyring_secret_store import (
    OsKeyringSecretStoreAdapter,
    keyring_service_name,
)
from google_work_agent.adapters.llm.gemini.credential import GeminiLlmCredentialAdapter
from google_work_agent.adapters.llm.runtime.llm_credential_router import SessionMemorySecretStore

_RUNTIME_METADATA_NAMES = (
    "service-instance.json",
    ".service-instance.json.tmp",
    "service.lock",
    ".service.lock.tmp",
    "service.lock.stale-guard",
    "shutdown.marker",
    ".shutdown.marker.tmp",
)
_SAFE_CODE = re.compile(r"[A-Z][A-Z0-9_]{0,79}")


class CredentialCleanupError(RuntimeError):
    def __init__(self, safe_code: str) -> None:
        super().__init__(safe_code)
        self.safe_code = safe_code


def main(argv: Sequence[str] | None = None) -> int:
    """Run the default uninstall policy without exposing a broad deletion mode."""

    parser = argparse.ArgumentParser(description="Clean up mcp-work-agent credentials")
    parser.add_argument("--mode", choices=("prompt",), default="prompt")
    arguments = parser.parse_args(argv)
    if arguments.mode != "prompt":
        return 2

    try:
        install_root = Path(sys.executable).resolve().parent.parent
        installation = verify_installation(install_root)
        build_config = load_signed_build_config(installation)
        definition = WindowsUninstallDefinition()
        data_root = _data_root()
        _require_runtime_stopped(data_root / "runtime")
        _delete_credentials(build_config.oauth_env, definition=definition)
        if definition.invalidate_runtime_session:
            _invalidate_runtime_session(data_root / "runtime")
        return 0
    except Exception as error:
        candidate = getattr(error, "safe_code", None)
        safe_code = (
            candidate
            if isinstance(candidate, str) and _SAFE_CODE.fullmatch(candidate)
            else "CREDENTIAL_CLEANUP_FAILED"
        )
        if sys.stderr is not None:
            print(f"Credential cleanup failed: {safe_code}", file=sys.stderr)
        return 1


def _delete_credentials(
    environment: str,
    *,
    definition: WindowsUninstallDefinition,
) -> None:
    failures = 0
    if definition.delete_google_oauth_keyring_entry:
        try:
            google_store = OsKeyringSecretStoreAdapter(
                service_name=keyring_service_name(
                    environment=environment,
                    credential_type="google-oauth",
                )
            )
            google_store.delete(GOOGLE_REFRESH_TOKEN_ACCOUNT)
        except Exception:
            failures += 1

    if definition.delete_llm_api_key_keyring_entry:
        try:
            llm_store = OsKeyringSecretStoreAdapter(
                service_name=keyring_service_name(
                    environment=environment,
                    credential_type="llm-api-key",
                )
            )
            GeminiLlmCredentialAdapter(
                provider="gemini",
                environment=environment,
                keyring_store=llm_store,
                session_store=SessionMemorySecretStore(),
            ).delete("uninstall-credential-cleanup-v1")
        except Exception:
            failures += 1

    if failures:
        raise CredentialCleanupError("KEYRING_CLEANUP_FAILED")


def _data_root() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        raise CredentialCleanupError("LOCALAPPDATA_UNAVAILABLE")
    return (Path(local_app_data) / "GoogleWorkAgent").resolve()


def _require_runtime_stopped(runtime_dir: Path) -> None:
    for name in ("service-instance.json", "service.lock"):
        path = runtime_dir / name
        if not path.is_file():
            continue
        try:
            if path.stat().st_size > 4_096:
                raise ValueError("runtime metadata is too large")
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
            raise CredentialCleanupError("RUNTIME_SESSION_INVALIDATION_UNSAFE") from error
        if not isinstance(payload, dict):
            raise CredentialCleanupError("RUNTIME_SESSION_INVALIDATION_UNSAFE")
        for field in ("launcher_pid", "service_pid"):
            pid = payload.get(field)
            if isinstance(pid, int) and not isinstance(pid, bool) and pid > 0:
                if _is_process_running(pid):
                    raise CredentialCleanupError("APPLICATION_STILL_RUNNING")


def _is_process_running(pid: int) -> bool:
    if os.name != "nt":
        raise CredentialCleanupError("UNSUPPORTED_OS")
    process_query_limited_information = 0x1000
    still_active = 259
    invalid_parameter = 87
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL
    handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
    if not handle:
        return ctypes.get_last_error() != invalid_parameter
    try:
        exit_code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return True
        return exit_code.value == still_active
    finally:
        kernel32.CloseHandle(handle)


def _invalidate_runtime_session(runtime_dir: Path) -> None:
    try:
        for name in _RUNTIME_METADATA_NAMES:
            path = runtime_dir / name
            if path.is_dir():
                raise CredentialCleanupError("RUNTIME_SESSION_INVALIDATION_UNSAFE")
            path.unlink(missing_ok=True)
    except OSError as error:
        raise CredentialCleanupError("RUNTIME_SESSION_INVALIDATION_FAILED") from error


__all__ = ["CredentialCleanupError", "main"]


if __name__ == "__main__":
    raise SystemExit(main())
