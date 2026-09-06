from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "google_work_agent"
AGENT_OWNERS = {
    "request_understanding",
    "tool_routing",
    "retrieval",
    "work_analysis",
    "planning",
    "review",
}


def _symbols(path: Path) -> set[str]:
    module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {
        node.name
        for node in module.body
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _has_asserting_test(path: Path) -> bool:
    module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for function in (
        node
        for node in module.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("test_")
    ):
        if any(isinstance(node, ast.Assert) for node in ast.walk(function)):
            return True
        if any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"raises", "fail"}
            for node in ast.walk(function)
        ):
            return True
    return False


def _pascal(stem: str) -> str:
    return "".join(part.capitalize() for part in stem.split("_"))


def _asserting_tests_for_symbol(symbol: str) -> list[Path]:
    owners: list[Path] = []
    for path in (ROOT / "tests").rglob("test_*.py"):
        if symbol in path.read_text(encoding="utf-8") and _has_asserting_test(path):
            owners.append(path)
    return owners


def test_application_handlers__have_matching__owner_tests() -> None:
    errors: list[str] = []
    for production in (SRC / "application" / "use_cases").glob("*/*.py"):
        if production.name == "__init__.py":
            continue
        expected = f"{_pascal(production.stem)}Handler"
        symbols = _symbols(production)
        if not any(symbol.endswith("Handler") for symbol in symbols):
            continue
        if expected not in symbols:
            errors.append(f"handler does not match filename: {production.relative_to(ROOT)}")
        owner = production.parent.name
        test_owner = (
            ROOT
            / "tests"
            / "unit"
            / "application"
            / "use_cases"
            / owner
            / f"test_{production.name}"
        )
        if (
            not test_owner.is_file() or not _has_asserting_test(test_owner)
        ) and not _asserting_tests_for_symbol(expected):
            errors.append(f"missing asserting test for {expected}")
    assert not errors, "\n" + "\n".join(errors)


def test_agent_operations__match_owner_and__have_owner_tests() -> None:
    errors: list[str] = []
    agent_root = SRC / "application" / "agents"
    actual_owners = {
        path.name for path in agent_root.iterdir() if path.is_dir() and path.name != "__pycache__"
    }
    if actual_owners != AGENT_OWNERS:
        errors.append(
            f"agent owner mismatch: missing={sorted(AGENT_OWNERS - actual_owners)}, "
            f"extra={sorted(actual_owners - AGENT_OWNERS)}"
        )
    for owner in sorted(actual_owners & AGENT_OWNERS):
        for production in (agent_root / owner).glob("*.py"):
            if production.name == "__init__.py":
                continue
            if production.stem not in _symbols(production):
                errors.append(f"operation does not match filename: {production.relative_to(ROOT)}")
            test_owner = (
                ROOT
                / "tests"
                / "unit"
                / "application"
                / "agents"
                / owner
                / f"test_{production.name}"
            )
            if not test_owner.is_file() or not _has_asserting_test(test_owner):
                errors.append(f"missing asserting owner test: {test_owner.relative_to(ROOT)}")
    assert not errors, "\n" + "\n".join(errors)


def test_legacy_application_workflow__has_no__test_owner() -> None:
    legacy_owner = ROOT / "tests" / "unit" / "application" / "workflows"
    legacy_tests = sorted(legacy_owner.rglob("test_*.py")) if legacy_owner.exists() else []
    assert not legacy_tests, "legacy test ownership remains: " + ", ".join(
        str(path.relative_to(ROOT)) for path in legacy_tests
    )
