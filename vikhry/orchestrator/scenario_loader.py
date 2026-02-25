from __future__ import annotations

import ast
from pathlib import Path
from typing import Any


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


def load_on_init_spec_from_scenario(scenario_path: str | Path | None) -> dict[str, Any]:
    if not scenario_path:
        return {
            "configured": False,
            "scenario_path": None,
            "vu_class": None,
            "params": [],
            "accepts_arbitrary_kwargs": False,
        }

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

    vu_class = _find_first_vu_class(tree)
    if vu_class is None:
        return {
            "configured": True,
            "scenario_path": str(path),
            "vu_class": None,
            "params": [],
            "accepts_arbitrary_kwargs": False,
        }

    on_init = _find_method(vu_class, "on_init")
    if on_init is None:
        return {
            "configured": True,
            "scenario_path": str(path),
            "vu_class": vu_class.name,
            "params": [],
            "accepts_arbitrary_kwargs": False,
        }

    params: list[dict[str, Any]] = []
    accepts_kwargs = False

    all_args = list(on_init.args.posonlyargs) + list(on_init.args.args)
    if all_args and all_args[0].arg == "self":
        all_args = all_args[1:]

    defaults = [None] * (len(all_args) - len(on_init.args.defaults)) + list(on_init.args.defaults)
    for arg, default_node in zip(all_args, defaults, strict=True):
        params.append(
            {
                "name": arg.arg,
                "kind": "positional_or_keyword",
                "required": default_node is None,
                "annotation": _format_annotation(arg.annotation),
                "default": _format_default(default_node),
            }
        )

    for arg, default_node in zip(on_init.args.kwonlyargs, on_init.args.kw_defaults, strict=True):
        params.append(
            {
                "name": arg.arg,
                "kind": "keyword_only",
                "required": default_node is None,
                "annotation": _format_annotation(arg.annotation),
                "default": _format_default(default_node),
            }
        )

    if on_init.args.kwarg is not None:
        accepts_kwargs = True

    return {
        "configured": True,
        "scenario_path": str(path),
        "vu_class": vu_class.name,
        "params": params,
        "accepts_arbitrary_kwargs": accepts_kwargs,
    }


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


def _find_first_vu_class(tree: ast.AST) -> ast.ClassDef | None:
    for node in tree.body if isinstance(tree, ast.Module) else []:
        if not isinstance(node, ast.ClassDef):
            continue
        if any(_is_vu_base(base) for base in node.bases):
            return node
    return None


def _is_vu_base(base: ast.AST) -> bool:
    if isinstance(base, ast.Name):
        return base.id == "VU"
    if isinstance(base, ast.Attribute):
        return base.attr == "VU"
    return False


def _find_method(class_node: ast.ClassDef, method_name: str) -> ast.AsyncFunctionDef | ast.FunctionDef | None:
    for item in class_node.body:
        if isinstance(item, ast.AsyncFunctionDef | ast.FunctionDef) and item.name == method_name:
            return item
    return None


def _format_annotation(node: ast.AST | None) -> str | None:
    if node is None:
        return None
    try:
        return ast.unparse(node)
    except Exception:  # noqa: BLE001
        return None


def _format_default(node: ast.AST | None) -> Any:
    if node is None:
        return None
    if isinstance(node, ast.Constant):
        return node.value
    try:
        return ast.unparse(node)
    except Exception:  # noqa: BLE001
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
