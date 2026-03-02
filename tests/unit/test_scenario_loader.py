from __future__ import annotations

from pathlib import Path

import pytest

from vikhry.orchestrator.scenario_loader import (
    ScenarioLoadError,
    load_on_init_spec_from_scenario,
    load_resource_names_from_scenario,
)


def test_scenario_loader_extracts_resource_names_spec(tmp_path: Path) -> None:
    scenario = tmp_path / "scenario.py"
    scenario.write_text(
        """
from vikhry import resource

@resource(name="users")
async def make_user(id, ctx):
    return {"id": id}

@resource("products")
async def make_product(id, ctx):
    return {"id": id}
""".strip(),
        encoding="utf-8",
    )

    names = load_resource_names_from_scenario(scenario)
    assert names == ["products", "users"]


def test_scenario_loader_handles_missing_file_spec(tmp_path: Path) -> None:
    missing = tmp_path / "missing.py"
    with pytest.raises(ScenarioLoadError):
        load_resource_names_from_scenario(missing)


def test_scenario_loader_ignores_non_resource_decorators_spec(tmp_path: Path) -> None:
    scenario = tmp_path / "scenario.py"
    scenario.write_text(
        """
def other():
    pass

@other
async def fn():
    return None
""".strip(),
        encoding="utf-8",
    )

    assert load_resource_names_from_scenario(scenario) == []


def test_scenario_loader_extracts_on_init_spec_spec(tmp_path: Path) -> None:
    scenario = tmp_path / "scenario.py"
    scenario.write_text(
        """
from vikhry import VU

class DemoVU(VU):
    async def on_init(self, tenant: str, warmup: int = 1, *, mode: str = "safe", **kwargs):
        pass
""".strip(),
        encoding="utf-8",
    )

    spec = load_on_init_spec_from_scenario(scenario)
    assert spec["configured"] is True
    assert spec["vu_class"] == "DemoVU"
    assert spec["accepts_arbitrary_kwargs"] is True
    params = spec["params"]
    assert isinstance(params, list)
    assert params[0]["name"] == "tenant"
    assert params[0]["required"] is True
    assert params[1]["name"] == "warmup"
    assert params[1]["default"] == 1
    assert params[2]["name"] == "mode"
    assert params[2]["kind"] == "keyword_only"


def test_scenario_loader_returns_empty_on_init_spec_without_scenario_spec() -> None:
    spec = load_on_init_spec_from_scenario(None)
    assert spec["configured"] is False
    assert spec["params"] == []


def test_scenario_loader_extracts_resource_names_from_import_path_spec(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package = tmp_path / "tmp_case_resources" / "scenarios"
    package.mkdir(parents=True, exist_ok=True)
    (tmp_path / "tmp_case_resources" / "__init__.py").write_text("", encoding="utf-8")
    (package / "__init__.py").write_text("", encoding="utf-8")
    scenario = package / "first_test.py"
    scenario.write_text(
        """
from vikhry import VU, resource

@resource(name="users")
async def make_user(id, ctx):
    return {"id": id}

@resource(name="sessions")
async def make_session(id, ctx):
    return {"id": id}

class FirstTestVU(VU):
    pass
    """.strip(),
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    names = load_resource_names_from_scenario(
        "tmp_case_resources.scenarios.first_test:FirstTestVU"
    )
    assert names == ["sessions", "users"]


def test_scenario_loader_extracts_on_init_spec_from_import_path_spec(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package = tmp_path / "tmp_case_on_init" / "scenarios"
    package.mkdir(parents=True, exist_ok=True)
    (tmp_path / "tmp_case_on_init" / "__init__.py").write_text("", encoding="utf-8")
    (package / "__init__.py").write_text("", encoding="utf-8")
    scenario = package / "second_test.py"
    scenario.write_text(
        """
from vikhry import VU

class FirstTestVU(VU):
    async def on_init(self, base_url: str, timeout: float = 5.0, **kwargs):
        pass
    """.strip(),
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    spec = load_on_init_spec_from_scenario(
        "tmp_case_on_init.scenarios.second_test:FirstTestVU"
    )
    assert spec["configured"] is True
    assert spec["vu_class"] == "FirstTestVU"
    assert spec["accepts_arbitrary_kwargs"] is True
    params = spec["params"]
    assert isinstance(params, list)
    assert params[0]["name"] == "base_url"
    assert params[0]["required"] is True
    assert params[1]["name"] == "timeout"
    assert params[1]["default"] == 5.0


def test_scenario_loader_reads_inherited_on_init_for_import_path_spec(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package = tmp_path / "tmp_case_inherited_on_init" / "scenarios"
    package.mkdir(parents=True, exist_ok=True)
    (tmp_path / "tmp_case_inherited_on_init" / "__init__.py").write_text("", encoding="utf-8")
    (package / "__init__.py").write_text("", encoding="utf-8")
    scenario = package / "third_test.py"
    scenario.write_text(
        """
from vikhry import VU

class FirstTestVU(VU):
    pass
    """.strip(),
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    spec = load_on_init_spec_from_scenario(
        "tmp_case_inherited_on_init.scenarios.third_test:FirstTestVU"
    )
    assert spec["configured"] is True
    params = spec["params"]
    assert isinstance(params, list)
    assert params[0]["name"] == "base_url"
    assert params[0]["required"] is False
