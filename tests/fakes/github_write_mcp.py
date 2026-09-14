"""Production GitHub MCP protocol/operations with only REST and credentials faked."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from google_work_agent.adapters.connectors.github.github.mcp_server import entrypoint
from google_work_agent.adapters.connectors.github.github.mcp_server.composition import (
    GitHubMcpServerState,
)
from google_work_agent.adapters.connectors.github.github.mcp_server.credential_provider import (
    GitHubConnectionStatus,
    GitHubCredentialState,
)
from google_work_agent.adapters.connectors.github.github.mcp_server.github_api import (
    GitHubApiClient,
    GitHubRestResponse,
)


class GitHubWriteFixtureCredentials:
    def __init__(self, root: Path) -> None:
        self.root = root

    def get_access_token(self) -> str:
        return "fixture-only"

    def invalidate_access_token(self) -> None:
        pass

    def get_connection_status(self) -> GitHubConnectionStatus:
        connected = not (self.root / "github-disconnected").exists()
        return GitHubConnectionStatus(
            connected=connected,
            credential_state=GitHubCredentialState.CONNECTED
            if connected
            else GitHubCredentialState.NOT_CONNECTED,
            reauth_required=False,
            last_checked_at_ms=1,
            granted_scopes=(),
            missing_required_scopes=(),
        )


class GitHubWriteFixtureRest:
    def __init__(self, root: Path) -> None:
        self.root = root
        state_path = root / "github-fixture-issues.json"
        self.issues: dict[int, dict[str, Any]] = (
            {int(k): v for k, v in json.loads(state_path.read_text(encoding="utf-8")).items()}
            if state_path.exists()
            else {}
        )
        self.serial = 0

    def request(
        self,
        method: str,
        url: str,
        *,
        access_token: str,
        body: dict[str, object] | None = None,
    ) -> GitHubRestResponse:
        del access_token
        self.serial += 1
        with (self.root / "github-provider-events.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"method": method, "url": url, "body": body}) + "\n")
        path = urlsplit(url).path
        if path == "/search/issues":
            if (self.root / "github-lookup-unavailable").exists():
                return GitHubRestResponse(503, {"message": "Controlled lookup failure"})
            query = parse_qs(urlsplit(url).query)["q"][0]
            marker = query.split('"')[1]
            matches = [i for i in self.issues.values() if marker in i.get("body", "")]
            return GitHubRestResponse(
                200, {"items": matches, "total_count": len(matches), "incomplete_results": False}
            )
        if path == "/user":
            return GitHubRestResponse(200, {"id": 161282085, "login": "bonggyulim"})
        if path == "/user/installations":
            return GitHubRestResponse(200, {"installations": [{"id": 1}]})
        if path == "/user/installations/1/repositories":
            return GitHubRestResponse(
                200,
                {
                    "repositories": [
                        {
                            "id": 841389122,
                            "full_name": "bonggyulim/search-save",
                            "private": True,
                        }
                    ]
                },
            )
        prefix = "/repos/bonggyulim/search-save/issues"
        if not path.startswith(prefix):
            return GitHubRestResponse(404, {})
        if path == prefix and method == "GET":
            return GitHubRestResponse(200, list(self.issues.values()))
        if path == prefix and method == "POST":
            number = len(self.issues) + 1
            self.issues[number] = {
                "number": number,
                "state": "open",
                "body": "",
                "title": "",
                "html_url": f"https://github.com/bonggyulim/search-save/issues/{number}",
                "labels": [],
                "assignees": [],
            }
        else:
            try:
                number = int(path.removeprefix(prefix + "/"))
            except ValueError:
                return GitHubRestResponse(404, {})
            if number not in self.issues:
                return GitHubRestResponse(404, {})
        if method != "GET":
            self.issues[number].update(body or {})
            self.issues[number]["updated_at"] = f"2026-09-06T01:00:{self.serial % 60:02d}Z"
            (self.root / "github-fixture-issues.json").write_text(
                json.dumps(self.issues), encoding="utf-8"
            )
        return GitHubRestResponse(201 if method == "POST" else 200, dict(self.issues[number]))


def main() -> None:
    root = Path(os.environ["GWA_MCP_MANIFEST_PATH"]).parent
    credentials = GitHubWriteFixtureCredentials(root)
    state = GitHubMcpServerState(
        credential_provider=credentials,  # type: ignore[arg-type]
        api_client=GitHubApiClient(
            credential_provider=credentials,  # type: ignore[arg-type]
            transport=GitHubWriteFixtureRest(root),
        ),
    )
    entrypoint.GitHubMcpServerState = lambda: state  # type: ignore[misc,assignment]
    entrypoint.github_mcp_main()


if __name__ == "__main__":
    main()
