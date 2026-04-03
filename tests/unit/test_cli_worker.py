from __future__ import annotations

from pathlib import Path

from vikhry.cli import _start_worker_detached
from vikhry.worker.models.settings import WorkerSettings


def test_start_worker_detached_threads_run_probes_flag_spec(
    monkeypatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    def _fake_start_detached_process_or_exit(**kwargs: object) -> int:
        captured.update(kwargs)
        return 321

    monkeypatch.setattr(
        "vikhry.cli._start_detached_process_or_exit",
        _fake_start_detached_process_or_exit,
    )

    pid = _start_worker_detached(
        settings=WorkerSettings(worker_id="w1", run_probes=True),
        pid_file=tmp_path / "worker.pid",
        log_file=tmp_path / "worker.log",
        startup_timeout_s=1.0,
    )

    assert pid == 321
    command = captured["command"]
    assert isinstance(command, list)
    assert "--run-probes" in command


def test_start_worker_detached_omits_run_probes_flag_when_disabled_spec(
    monkeypatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    def _fake_start_detached_process_or_exit(**kwargs: object) -> int:
        captured.update(kwargs)
        return 321

    monkeypatch.setattr(
        "vikhry.cli._start_detached_process_or_exit",
        _fake_start_detached_process_or_exit,
    )

    pid = _start_worker_detached(
        settings=WorkerSettings(worker_id="w1", run_probes=False),
        pid_file=tmp_path / "worker.pid",
        log_file=tmp_path / "worker.log",
        startup_timeout_s=1.0,
    )

    assert pid == 321
    command = captured["command"]
    assert isinstance(command, list)
    assert "--run-probes" not in command
