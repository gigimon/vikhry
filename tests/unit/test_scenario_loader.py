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
