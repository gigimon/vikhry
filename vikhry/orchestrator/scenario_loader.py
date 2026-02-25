from __future__ import annotations

import ast
from pathlib import Path


class ScenarioLoadError(RuntimeError):
    pass


def load_resource_names_from_scenario(scenario_path: str | Path | None) -> list[str]:
    if not scenario_path:
        return []

    path = Path(scenario_path).expanduser().resolve()
    if not path.exists():
        raise ScenarioLoadError(f"Scenario file not found: {path}")
    if not path.is_file():
        raise ScenarioLoadError(f"Scenario path is not a file: {path}")

    try:
        source = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ScenarioLoadError(f"Failed to read scenario file: {path}: {exc}") from exc

    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        raise ScenarioLoadError(f"Scenario parse error in {path}: {exc}") from exc

    resource_names: set[str] = set()

    for node in ast.walk(tree):
        if not isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef):
            continue
        for decorator in node.decorator_list:
            resource_name = _extract_resource_name(decorator)
            if resource_name:
                resource_names.add(resource_name)

    return sorted(resource_names)


def _extract_resource_name(decorator: ast.AST) -> str | None:
    if not isinstance(decorator, ast.Call):
        return None
    if not _is_resource_decorator(decorator.func):
        return None

    for keyword in decorator.keywords:
        if keyword.arg != "name":
            continue
        return _as_nonempty_string(keyword.value)

    # Support @resource("users") style.
    if decorator.args:
        return _as_nonempty_string(decorator.args[0])

    return None


def _is_resource_decorator(func: ast.AST) -> bool:
    if isinstance(func, ast.Name):
        return func.id == "resource"
    if isinstance(func, ast.Attribute):
        return func.attr == "resource"
    return False


def _as_nonempty_string(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        value = node.value.strip()
        return value or None
    return None

