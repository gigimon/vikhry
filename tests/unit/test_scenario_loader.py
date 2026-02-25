from __future__ import annotations

from pathlib import Path

import pytest

from vikhry.orchestrator.scenario_loader import (
    ScenarioLoadError,
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

