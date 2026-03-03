from __future__ import annotations

import pytest

from vikhry.runtime.metrics import (
    build_metric_payload,
    emit_metric,
    metric,
    metric_scope,
    normalize_result_code,
)


def test_build_metric_payload_contains_required_fields_spec() -> None:
    payload = build_metric_payload(
        name="/page1",
        step="open_page",
        status=True,
        time=12.3,
        source="http",
        stage="execute",
        result_code="HTTP_200",
        result_category="ok",
        fatal=False,
        method="GET",
    )
    assert payload["name"] == "/page1"
    assert payload["step"] == "open_page"
    assert payload["status"] is True
    assert payload["time"] == 12.3
    assert payload["source"] == "http"
    assert payload["stage"] == "execute"
    assert payload["result_code"] == "HTTP_200"
    assert payload["result_category"] == "ok"
    assert payload["fatal"] is False
    assert payload["method"] == "GET"


@pytest.mark.asyncio
async def test_emit_metric_returns_false_without_emitter_spec() -> None:
    emitted = await emit_metric(
        name="custom",
        step="ping",
        status=True,
        time=1.0,
        source="custom",
        stage="execute",
        result_code="METRIC_OK",
        result_category="ok",
        fatal=False,
    )
    assert emitted is False


@pytest.mark.asyncio
async def test_metric_scope_emits_payload_with_default_step_spec() -> None:
    captured: list[dict[str, object]] = []

    async def _emitter(payload: dict[str, object]) -> None:
        captured.append(payload)

    with metric_scope(emitter=_emitter, step="ping"):
        emitted = await emit_metric(
            name="/auth",
            status=True,
            time=2.5,
            source="http",
            stage="execute",
            result_code="HTTP_200",
            result_category="ok",
            fatal=False,
            method="POST",
        )

    assert emitted is True
    assert len(captured) == 1
    assert captured[0]["name"] == "/auth"
    assert captured[0]["step"] == "ping"
    assert captured[0]["status"] is True
    assert captured[0]["time"] == 2.5
    assert captured[0]["source"] == "http"
    assert captured[0]["stage"] == "execute"
    assert captured[0]["result_code"] == "HTTP_200"
    assert captured[0]["result_category"] == "ok"
    assert captured[0]["fatal"] is False
    assert captured[0]["method"] == "POST"


@pytest.mark.asyncio
async def test_metric_decorator_emits_around_function_call_spec() -> None:
    captured: list[dict[str, object]] = []

    async def _emitter(payload: dict[str, object]) -> None:
        captured.append(payload)

    @metric(name="helper_call", component="helpers")
    async def _helper() -> None:
        return None

    with metric_scope(emitter=_emitter, step="ping"):
        await _helper()

    assert len(captured) == 1
    assert captured[0]["name"] == "helper_call"
    assert captured[0]["step"] == "ping"
    assert captured[0]["status"] is True
    assert captured[0]["source"] == "custom"
    assert captured[0]["stage"] == "execute"
    assert captured[0]["result_code"] == "METRIC_OK"
    assert captured[0]["result_category"] == "ok"
    assert captured[0]["fatal"] is False
    assert captured[0]["component"] == "helpers"
    assert float(captured[0]["time"]) >= 0.0


def test_normalize_result_code_sanitizes_and_caps_length_spec() -> None:
    raw = "http 500 bad gateway! xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
    normalized = normalize_result_code(raw)
    assert normalized.startswith("HTTP_500_BAD_GATEWAY")
    assert len(normalized) <= 64


def test_normalize_result_code_returns_unknown_when_empty_spec() -> None:
    assert normalize_result_code("") == "UNKNOWN"
