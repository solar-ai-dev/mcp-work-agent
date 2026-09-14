import ast
from pathlib import Path

ROOT = Path(__file__).parents[2] / "src" / "google_work_agent"


def test_run_phase_handlers__depend_only_on__domain_and_ports() -> None:
    for name in ("start_analysis.py", "begin_retrieval.py", "begin_planning.py"):
        source = (ROOT / "application" / "use_cases" / "run" / name).read_text(encoding="utf-8")
        assert "google_work_agent.adapters" not in source
        assert "google_work_agent.ports.repositories" not in source
        assert "update_if_version_and_status(" in source


def test_run_repository__has_no_phase__transition_command_authority() -> None:
    repository_sources = (
        ROOT / "ports" / "persistence" / "run_repository.py",
        ROOT / "adapters" / "persistence" / "sqlite" / "repositories" / "run_repository.py",
    )
    for path in repository_sources:
        source = path.read_text(encoding="utf-8")
        for method in (
            "def start_analysis(",
            "def begin_retrieval(",
            "def begin_planning(",
            "def replan(",
        ):
            assert method not in source
    assert not (ROOT / "adapters" / "persistence" / "repositories.py").exists()


def test_workflow_uses_explicit__phase_handlers_without__dynamic_repository_dispatch() -> None:
    source = (ROOT / "adapters" / "langgraph" / "main" / "workflow.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    attribute_bindings = {
        target.attr: (node.value.value.id, node.value.attr)
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance((target := node.targets[0]), ast.Attribute)
        and isinstance(node.value, ast.Attribute)
        and isinstance(node.value.value, ast.Name)
    }
    assert attribute_bindings["_start_analysis_handler"] == (
        "run_handlers",
        "start_analysis",
    )
    assert attribute_bindings["_begin_retrieval_handler"] == (
        "run_handlers",
        "begin_retrieval",
    )
    assert attribute_bindings["_begin_planning_handler"] == (
        "run_handlers",
        "begin_planning",
    )
    assert "StartAnalysisHandler(" not in source
    assert "BeginRetrievalHandler(" not in source
    assert "BeginPlanningHandler(" not in source
    assert "getattr(unit_of_work.runs" not in source
    assert ".runs.replan(" not in source


def test_cancel_callbacks__at_composition_boundary__use_exact_bindings() -> None:
    callbacks_path = (
        ROOT / "adapters" / "langgraph" / "main" / "cancel_resolution_runtime_callbacks.py"
    )
    tree = ast.parse(callbacks_path.read_text(encoding="utf-8"))
    dynamic_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "getattr"
    ]
    assert dynamic_calls == []

    composition_tree = ast.parse(
        (ROOT / "api" / "composition.py").read_text(encoding="utf-8")
    )
    handler_calls = [
        node
        for node in ast.walk(composition_tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "ContinueCancelResolutionHandler"
    ]
    assert len(handler_calls) == 1
    callback_bindings = {
        keyword.arg: ast.unparse(keyword.value)
        for keyword in handler_calls[0].keywords
        if keyword.arg is not None
    }
    assert callback_bindings["settle_pending_action"] == (
        "cancel_resolution_callbacks.settle_pending_action"
    )
    assert callback_bindings["reconcile_inflight_action"] == (
        "cancel_resolution_callbacks.reconcile_inflight_action"
    )
    assert callback_bindings["verify_executed_action"] == (
        "cancel_resolution_callbacks.verify_executed_action"
    )
    assert callback_bindings["resolve_unknown_action"] == (
        "cancel_resolution_callbacks.resolve_unknown_action"
    )


def test_workflow_application_handler_bindings__at_runtime_boundary__have_explicit_types() -> None:
    bindings_path = (
        ROOT / "adapters" / "langgraph" / "main" / "application_handler_bindings.py"
    )
    tree = ast.parse(bindings_path.read_text(encoding="utf-8"))
    any_annotations = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AnnAssign) and ast.unparse(node.annotation) == "Any"
    ]
    assert any_annotations == []


def test_main_graph_node_bindings__at_composition_boundary__have_explicit_types() -> None:
    graph_path = ROOT / "adapters" / "langgraph" / "main" / "graph.py"
    tree = ast.parse(graph_path.read_text(encoding="utf-8"))
    binding_classes = {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.ClassDef)
        and node.name in {"GraphNodeBindings", "MainControlNodeBindings"}
    }
    assert set(binding_classes) == {"GraphNodeBindings", "MainControlNodeBindings"}
    any_annotations = [
        node
        for class_node in binding_classes.values()
        for node in class_node.body
        if isinstance(node, ast.AnnAssign) and ast.unparse(node.annotation) == "Any"
    ]
    assert any_annotations == []


def test_superseded_plan_children__cannot_regain_mutation__or_execution_authority() -> None:
    guarded_operations = (
        ROOT / "application" / "use_cases" / "action" / "modify_action.py",
        ROOT / "application" / "use_cases" / "action" / "approve_action.py",
        ROOT / "application" / "use_cases" / "action" / "prepare_write_retry.py",
    )
    for path in guarded_operations:
        source = path.read_text(encoding="utf-8")
        assert "PlanStatusV1.SUPERSEDED" in source
        assert "superseded Plan children are history-only" in source
    claim = (ROOT / "application" / "use_cases" / "claim" / "claim_execution.py").read_text(
        encoding="utf-8"
    )
    assert "plan_status=plan.status" in claim
    assert "plan_is_current=current_plan is not None and current_plan.id == plan.id" in claim
