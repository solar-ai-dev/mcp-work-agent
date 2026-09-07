from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src" / "google_work_agent"
GOOGLE_WORKSPACE_CONTRACT = "google_work_agent.ports.connector.contracts.google_workspace"
CONNECTOR_NEUTRAL_SYMBOLS = {
    "DeliveryCertainty",
    "ResourcePage",
    "ResourceSnapshot",
    "ResourceType",
}


def test_github_connector__does_not_depend_on__google_workspace_contract() -> None:
    github = SRC / "adapters" / "connectors" / "github"
    for path in github.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        assert not any(
            isinstance(node, ast.ImportFrom) and node.module == GOOGLE_WORKSPACE_CONTRACT
            for node in ast.walk(tree)
        ), path


def test_google_workspace_contract__does_not_own__connector_neutral_symbols() -> None:
    path = SRC / "ports" / "connector" / "contracts" / "google_workspace.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    definitions = {
        node.name for node in tree.body if isinstance(node, ast.ClassDef | ast.FunctionDef)
    }
    assert definitions.isdisjoint(CONNECTOR_NEUTRAL_SYMBOLS)
