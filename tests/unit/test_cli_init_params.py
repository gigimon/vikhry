from __future__ import annotations

import pytest
import typer

from vikhry.cli import _parse_init_params


def test_parse_init_params_merges_json_and_key_values_spec() -> None:
    parsed = _parse_init_params(
        ["warmup=3", "enabled=true", "tenant=demo"],
        '{"region":"us"}',
    )
    assert parsed == {
        "region": "us",
        "warmup": 3,
        "enabled": True,
        "tenant": "demo",
    }


def test_parse_init_params_rejects_invalid_key_value_spec() -> None:
    with pytest.raises(typer.Exit):
        _parse_init_params(["bad-format"], None)
