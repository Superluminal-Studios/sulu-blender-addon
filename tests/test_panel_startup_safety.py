import ast
from pathlib import Path


PANELS_SOURCE = Path(__file__).resolve().parents[1] / "panels.py"


def _function_node(tree: ast.Module, name: str) -> ast.FunctionDef:
    return next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == name
    )


def test_panel_registration_does_not_schedule_dependency_scans():
    tree = ast.parse(PANELS_SOURCE.read_text(encoding="utf-8"))
    register_node = _function_node(tree, "register")
    register_source = ast.unparse(register_node)

    assert "scan_dependencies_fast" not in register_source
    assert "bpy.app.timers" not in register_source


def test_dependency_scan_requires_an_explicit_operator_execution():
    tree = ast.parse(PANELS_SOURCE.read_text(encoding="utf-8"))
    operator_node = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef)
        and node.name == "SUPERLUMINAL_OT_RefreshProjectScan"
    )
    execute_node = next(
        node
        for node in operator_node.body
        if isinstance(node, ast.FunctionDef) and node.name == "execute"
    )

    assert "scan_dependencies_fast()" in ast.unparse(execute_node)
