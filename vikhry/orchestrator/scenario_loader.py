from __future__ import annotations

import ast
import importlib
import inspect
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from vikhry.runtime import VU, collect_probe_specs, collect_resource_factories


class ScenarioLoadError(RuntimeError):
    pass


def load_resource_factories_from_scenario(
    scenario_path: str | Path | None,
) -> dict[str, Callable[..., Awaitable[Any]]]:
    """Return mapping of resource_name -> async factory callable from scenario."""
    if not scenario_path:
        return {}

    scenario_ref = str(scenario_path).strip()
    if not _is_existing_file_path(scenario_ref) and _looks_like_import_path(scenario_ref):
        module, _vu_type = _load_module_and_vu_type(scenario_ref)
        return collect_resource_factories(module.__dict__)

    # File-path scenarios: import the module to get live factory callables.
    path = Path(scenario_ref).expanduser().resolve()
    if not path.exists():
        raise ScenarioLoadError(f"Scenario file not found: {path}")
    import importlib.util

    spec = importlib.util.spec_from_file_location("_vikhry_scenario_tmp", path)
    if spec is None or spec.loader is None:
        raise ScenarioLoadError(f"Cannot load scenario module from: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return collect_resource_factories(module.__dict__)


def load_resource_names_from_scenario(scenario_path: str | Path | None) -> list[str]:
    if not scenario_path:
        return []

    scenario_ref = str(scenario_path).strip()
    if not _is_existing_file_path(scenario_ref) and _looks_like_import_path(scenario_ref):
        module, _vu_type = _load_module_and_vu_type(scenario_ref)
        factories = collect_resource_factories(module.__dict__)
        return sorted(factories)

    tree = _load_scenario_ast(scenario_ref)
    resource_names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef):
            continue
        for decorator in node.decorator_list:
            resource_name = _extract_resource_name(decorator)
            if resource_name:
                resource_names.add(resource_name)
    return sorted(resource_names)


def load_probe_names_from_scenario(scenario_path: str | Path | None) -> list[str]:
    if not scenario_path:
        return []

    scenario_ref = str(scenario_path).strip()
    if not _is_existing_file_path(scenario_ref) and _looks_like_import_path(scenario_ref):
        module, _vu_type = _load_module_and_vu_type(scenario_ref)
        probes = collect_probe_specs(module.__dict__)
        return sorted(spec.name for spec in probes)

    tree = _load_scenario_ast(scenario_ref)
    probe_names: set[str] = set()
    for node in tree.body if isinstance(tree, ast.Module) else []:
        if not isinstance(node, ast.AsyncFunctionDef):
            continue
        for decorator in node.decorator_list:
            probe_name = _extract_probe_name(decorator)
            if probe_name:
                probe_names.add(probe_name)
    return sorted(probe_names)


def load_on_init_spec_from_scenario(scenario_path: str | Path | None) -> dict[str, Any]:
    if not scenario_path:
        return {
            "configured": False,
            "scenario_path": None,
            "vu_class": None,
            "params": [],
            "accepts_arbitrary_kwargs": False,
        }

    scenario_ref = str(scenario_path).strip()
    if not _is_existing_file_path(scenario_ref) and _looks_like_import_path(scenario_ref):
        module, vu_type = _load_module_and_vu_type(scenario_ref)
        _ = module
        on_init = getattr(vu_type, "on_init", None)
        if not callable(on_init):
            return {
                "configured": True,
                "scenario_path": scenario_ref,
                "vu_class": vu_type.__name__,
                "params": [],
                "accepts_arbitrary_kwargs": False,
            }

        signature = inspect.signature(on_init)
        params: list[dict[str, Any]] = []
        accepts_kwargs = False
        for parameter in signature.parameters.values():
            if parameter.name == "self":
                continue
            if parameter.kind is inspect.Parameter.VAR_KEYWORD:
                accepts_kwargs = True
                continue

            params.append(
                {
                    "name": parameter.name,
                    "kind": _normalize_parameter_kind(parameter.kind),
                    "required": parameter.default is inspect.Signature.empty,
                    "annotation": _format_runtime_annotation(parameter.annotation),
                    "default": _format_runtime_default(parameter.default),
                }
            )

        return {
            "configured": True,
            "scenario_path": scenario_ref,
            "vu_class": vu_type.__name__,
            "params": params,
            "accepts_arbitrary_kwargs": accepts_kwargs,
        }

    tree = _load_scenario_ast(scenario_ref)
    vu_class = _find_first_vu_class(tree)
    if vu_class is None:
        return {
            "configured": True,
            "scenario_path": str(Path(scenario_ref).expanduser().resolve()),
            "vu_class": None,
            "params": [],
            "accepts_arbitrary_kwargs": False,
        }

    on_init = _find_method(vu_class, "on_init")
    if on_init is None:
        return {
            "configured": True,
            "scenario_path": str(Path(scenario_ref).expanduser().resolve()),
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
        "scenario_path": str(Path(scenario_ref).expanduser().resolve()),
        "vu_class": vu_class.name,
        "params": params,
        "accepts_arbitrary_kwargs": accepts_kwargs,
    }


def _load_scenario_ast(scenario_path: str) -> ast.AST:
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
    return tree


def _load_module_and_vu_type(scenario_import: str) -> tuple[Any, type[VU]]:
    module_name, vu_name = _parse_scenario_import(scenario_import)
    try:
        module = importlib.import_module(module_name)
    except Exception as exc:  # noqa: BLE001
        raise ScenarioLoadError(
            f"Failed to import scenario module `{module_name}`: {exc}"
        ) from exc

    candidate = getattr(module, vu_name, None)
    if candidate is None:
        raise ScenarioLoadError(
            f"Scenario class `{vu_name}` not found in module `{module_name}`"
        )
    if not inspect.isclass(candidate):
        raise ScenarioLoadError(
            f"Scenario target `{scenario_import}` must be a class"
        )
    if not issubclass(candidate, VU):
        raise ScenarioLoadError(
            f"Scenario class `{scenario_import}` must inherit from VU"
        )
    return module, candidate


def _looks_like_import_path(value: str) -> bool:
    if ":" not in value:
        return False
    module_name, sep, vu_name = value.partition(":")
    return bool(
        sep and module_name and vu_name and "/" not in module_name and "\\" not in module_name
    )


def _is_existing_file_path(value: str) -> bool:
    try:
        return Path(value).expanduser().exists()
    except OSError:
        return False


def _parse_scenario_import(value: str) -> tuple[str, str]:
    module_name, sep, vu_name = value.partition(":")
    if not sep or not module_name or not vu_name:
        raise ScenarioLoadError(
            "Scenario must use import path format `module.path:ClassName`"
        )
    return module_name.strip(), vu_name.strip()


def _normalize_parameter_kind(kind: inspect._ParameterKind) -> str:
    if kind is inspect.Parameter.KEYWORD_ONLY:
        return "keyword_only"
    if kind is inspect.Parameter.POSITIONAL_ONLY:
        return "positional_only"
    if kind is inspect.Parameter.VAR_POSITIONAL:
        return "var_positional"
    return "positional_or_keyword"


def _format_runtime_annotation(annotation: object) -> str | None:
    if annotation is inspect.Signature.empty:
        return None
    if isinstance(annotation, str):
        return annotation
    name = getattr(annotation, "__name__", None)
    if isinstance(name, str):
        return name
    return str(annotation)


def _format_runtime_default(default: object) -> Any:
    if default is inspect.Signature.empty:
        return None
    if isinstance(default, (str, int, float, bool)) or default is None:
        return default
    if isinstance(default, (list, dict, tuple)):
        return default
    return repr(default)


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


def _extract_probe_name(decorator: ast.AST) -> str | None:
    if not isinstance(decorator, ast.Call):
        return None
    if not _is_probe_decorator(decorator.func):
        return None

    for keyword in decorator.keywords:
        if keyword.arg != "name":
            continue
        return _as_nonempty_string(keyword.value)

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


def _is_probe_decorator(func: ast.AST) -> bool:
    if isinstance(func, ast.Name):
        return func.id == "probe"
    if isinstance(func, ast.Attribute):
        return func.attr == "probe"
    return False


def _as_nonempty_string(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        value = node.value.strip()
        return value or None
    return None
