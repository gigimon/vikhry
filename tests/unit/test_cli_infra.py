from __future__ import annotations

from vikhry.cli import _format_infra_up_summary


def test_format_infra_up_summary_lists_orchestrator_and_worker_logs_spec() -> None:
    message = _format_infra_up_summary(2)

    assert "Infra started." in message
    assert "Logs:" in message
    assert "- orchestrator:" in message
    assert "- worker-1:" in message
    assert "- worker-2:" in message
    assert "tail -f <log-file>" in message
