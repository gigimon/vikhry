from __future__ import annotations

import errno
import os
import signal
import subprocess
import sys
import time
from datetime import timedelta
from pathlib import Path
from typing import Annotated, Any
from uuid import uuid4

import orjson
import typer
from pyreqwest.client import SyncClientBuilder
from pyreqwest.exceptions import PyreqwestError

from vikhry.orchestrator.models.settings import OrchestratorSettings
from vikhry.orchestrator.scenario_loader import ScenarioLoadError
from vikhry.worker.models.settings import WorkerSettings

app = typer.Typer(
    name="vikhry",
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)
orchestrator_app = typer.Typer(no_args_is_help=True)
test_app = typer.Typer(no_args_is_help=True)
worker_app = typer.Typer(no_args_is_help=True)
app.add_typer(orchestrator_app, name="orchestrator")
app.add_typer(test_app, name="test")
app.add_typer(worker_app, name="worker")

DEFAULT_ORCHESTRATOR_URL = "http://127.0.0.1:8080"


def _default_runtime_dir() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches"

    if sys.platform.startswith("linux"):
        xdg_runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
        if xdg_runtime_dir:
            xdg_path = Path(xdg_runtime_dir)
            if xdg_path.is_dir() and os.access(xdg_path, os.W_OK):
                return xdg_path

        run_user_dir = Path("/run/user") / str(os.getuid())
        if run_user_dir.is_dir() and os.access(run_user_dir, os.W_OK):
            return run_user_dir

        return Path("/tmp")

    # Non-target platforms fallback to temporary directory.
    return Path("/tmp")


DEFAULT_RUNTIME_DIR = _default_runtime_dir() / "vikhry"
DEFAULT_PID_FILE = DEFAULT_RUNTIME_DIR / "orchestrator.pid"
DEFAULT_LOG_FILE = DEFAULT_RUNTIME_DIR / "orchestrator.log"
DEFAULT_WORKER_PID_FILE = DEFAULT_RUNTIME_DIR / "worker.pid"
DEFAULT_WORKER_LOG_FILE = DEFAULT_RUNTIME_DIR / "worker.log"


@orchestrator_app.command("start")
def orchestrator_start(
    host: Annotated[str, typer.Option("--host")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port", min=1, max=65535)] = 8080,
    redis_url: Annotated[str, typer.Option("--redis-url")] = "redis://127.0.0.1:6379/0",
    scenario: Annotated[
        str | None,
        typer.Option(
            "--scenario",
            help="Scenario import path in `module.path:ClassName` format.",
        ),
    ] = None,
    heartbeat_timeout_s: Annotated[int, typer.Option("--heartbeat-timeout-s", min=1)] = 15,
    worker_scan_interval_s: Annotated[int, typer.Option("--worker-scan-interval-s", min=1)] = 5,
    metrics_poll_interval_s: Annotated[
        float, typer.Option("--metrics-poll-interval-s", min=0.1)
    ] = 1.0,
    metrics_window_s: Annotated[int, typer.Option("--metrics-window-s", min=1)] = 60,
    metrics_max_events_per_poll: Annotated[
        int, typer.Option("--metrics-max-events-per-poll", min=1)
    ] = 300,
    metrics_recent_events_per_metric: Annotated[
        int, typer.Option("--metrics-recent-events-per-metric", min=1)
    ] = 1000,
    metrics_subscriber_queue_size: Annotated[
        int, typer.Option("--metrics-subscriber-queue-size", min=1)
    ] = 64,
    detach: Annotated[
        bool,
        typer.Option(
            "--detach/--foreground",
            help="Run orchestrator in background and return control to terminal.",
        ),
    ] = True,
    startup_timeout_s: Annotated[
        float,
        typer.Option("--startup-timeout-s", min=0.1),
    ] = 10.0,
    log_file: Annotated[Path, typer.Option("--log-file")] = DEFAULT_LOG_FILE,
    pid_file: Annotated[Path, typer.Option("--pid-file")] = DEFAULT_PID_FILE,
) -> None:
    settings = OrchestratorSettings(
        host=host,
        port=port,
        redis_url=redis_url,
        scenario=scenario or None,
        heartbeat_timeout_s=heartbeat_timeout_s,
        worker_scan_interval_s=worker_scan_interval_s,
        metrics_poll_interval_s=metrics_poll_interval_s,
        metrics_window_s=metrics_window_s,
        metrics_max_events_per_poll=metrics_max_events_per_poll,
        metrics_recent_events_per_metric=metrics_recent_events_per_metric,
        metrics_subscriber_queue_size=metrics_subscriber_queue_size,
    )
    if detach:
        _start_orchestrator_detached_or_exit(
            settings=settings,
            pid_file=pid_file,
            log_file=log_file,
            startup_timeout_s=startup_timeout_s,
        )
        return
    _run_orchestrator_foreground(settings=settings, pid_file=pid_file)


@orchestrator_app.command("serve", hidden=True)
def orchestrator_serve(
    host: Annotated[str, typer.Option("--host")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port", min=1, max=65535)] = 8080,
    redis_url: Annotated[str, typer.Option("--redis-url")] = "redis://127.0.0.1:6379/0",
    scenario: Annotated[
        str | None,
        typer.Option(
            "--scenario",
            help="Scenario import path in `module.path:ClassName` format.",
        ),
    ] = None,
    heartbeat_timeout_s: Annotated[int, typer.Option("--heartbeat-timeout-s", min=1)] = 15,
    worker_scan_interval_s: Annotated[int, typer.Option("--worker-scan-interval-s", min=1)] = 5,
    metrics_poll_interval_s: Annotated[
        float, typer.Option("--metrics-poll-interval-s", min=0.1)
    ] = 1.0,
    metrics_window_s: Annotated[int, typer.Option("--metrics-window-s", min=1)] = 60,
    metrics_max_events_per_poll: Annotated[
        int, typer.Option("--metrics-max-events-per-poll", min=1)
    ] = 300,
    metrics_recent_events_per_metric: Annotated[
        int, typer.Option("--metrics-recent-events-per-metric", min=1)
    ] = 1000,
    metrics_subscriber_queue_size: Annotated[
        int, typer.Option("--metrics-subscriber-queue-size", min=1)
    ] = 64,
    pid_file: Annotated[Path, typer.Option("--pid-file")] = DEFAULT_PID_FILE,
) -> None:
    settings = OrchestratorSettings(
        host=host,
        port=port,
        redis_url=redis_url,
        scenario=scenario or None,
        heartbeat_timeout_s=heartbeat_timeout_s,
        worker_scan_interval_s=worker_scan_interval_s,
        metrics_poll_interval_s=metrics_poll_interval_s,
        metrics_window_s=metrics_window_s,
        metrics_max_events_per_poll=metrics_max_events_per_poll,
        metrics_recent_events_per_metric=metrics_recent_events_per_metric,
        metrics_subscriber_queue_size=metrics_subscriber_queue_size,
    )
    _run_orchestrator_foreground(settings=settings, pid_file=pid_file)


@orchestrator_app.command("stop")
def orchestrator_stop(
    pid_file: Annotated[Path, typer.Option("--pid-file")] = DEFAULT_PID_FILE,
    timeout_s: Annotated[float, typer.Option("--timeout-s", min=0.1)] = 10.0,
    force: Annotated[bool, typer.Option("--force")] = False,
) -> None:
    pid = _read_pid_or_exit(pid_file)
    if pid == os.getpid():
        raise typer.Exit(
            code=_error(
                "PID file points to current process; refusing self-termination. "
                "Run stop from another shell."
            )
        )

    if not _is_process_alive(pid):
        _remove_pid_file_if_matches(pid_file, pid)
        raise typer.Exit(
            code=_error(
                f"Process {pid} is not running. Removed stale pid file `{pid_file}`."
            )
        )

    if _send_stop_signal_and_wait(pid, signal.SIGINT, timeout_s * 0.5):
        _remove_pid_file_if_matches(pid_file, pid)
        typer.echo(f"Orchestrator process {pid} stopped.")
        raise typer.Exit(code=0)

    if _send_stop_signal_and_wait(pid, signal.SIGTERM, timeout_s * 0.5):
        _remove_pid_file_if_matches(pid_file, pid)
        typer.echo(f"Orchestrator process {pid} stopped.")
        raise typer.Exit(code=0)

    if force:
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError as exc:
            raise typer.Exit(
                code=_error(f"Failed to force-stop process {pid} with SIGKILL: {exc}")
            ) from exc
        _remove_pid_file_if_matches(pid_file, pid)
        typer.echo(f"Orchestrator process {pid} force-stopped.")
        raise typer.Exit(code=0)

    raise typer.Exit(
        code=_error(
            f"Process {pid} did not stop within {timeout_s:.1f}s. "
            "Use `--force` to send SIGKILL."
        )
    )


@worker_app.command("start")
def worker_start(
    redis_url: Annotated[str, typer.Option("--redis-url")] = "redis://127.0.0.1:6379/0",
    worker_id: Annotated[str | None, typer.Option("--worker-id")] = None,
    log_level: Annotated[
        str,
        typer.Option("--log-level", help="Python logging level (e.g. DEBUG, INFO, WARNING)."),
    ] = "INFO",
    heartbeat_interval_s: Annotated[
        float, typer.Option("--heartbeat-interval-s", min=0.1)
    ] = 3.0,
    command_poll_timeout_s: Annotated[
        float, typer.Option("--command-poll-timeout-s", min=0.1)
    ] = 1.0,
    graceful_stop_timeout_s: Annotated[
        float, typer.Option("--graceful-stop-timeout-s", min=0.1)
    ] = 5.0,
    scenario: Annotated[
        str,
        typer.Option(
            "--scenario",
            help="Scenario import path in `module.path:ClassName` format.",
        ),
    ] = "vikhry.runtime.defaults:IdleVU",
    http_base_url: Annotated[
        str,
        typer.Option(
            "--http-base-url",
            help="Base URL for scenario HTTP calls that use relative paths.",
        ),
    ] = "",
    vu_idle_sleep_s: Annotated[
        float,
        typer.Option(
            "--vu-idle-sleep-s",
            min=0.01,
            help="Sleep interval when scenario has no eligible steps.",
        ),
    ] = 0.05,
    vu_startup_jitter_ms: Annotated[
        float,
        typer.Option(
            "--vu-startup-jitter-ms",
            min=0.0,
            help="Max startup jitter per VU in milliseconds (uniform in [0, value]).",
        ),
    ] = 5.0,
    detach: Annotated[
        bool,
        typer.Option(
            "--detach/--foreground",
            help="Run worker in background and return control to terminal.",
        ),
    ] = True,
    startup_timeout_s: Annotated[float, typer.Option("--startup-timeout-s", min=0.1)] = 10.0,
    log_file: Annotated[Path, typer.Option("--log-file")] = DEFAULT_WORKER_LOG_FILE,
    pid_file: Annotated[Path, typer.Option("--pid-file")] = DEFAULT_WORKER_PID_FILE,
) -> None:
    resolved_worker_id = _resolve_worker_id(worker_id)
    settings = WorkerSettings(
        redis_url=redis_url,
        worker_id=resolved_worker_id,
        log_level=log_level,
        heartbeat_interval_s=heartbeat_interval_s,
        command_poll_timeout_s=command_poll_timeout_s,
        graceful_stop_timeout_s=graceful_stop_timeout_s,
        scenario=scenario,
        http_base_url=http_base_url,
        vu_idle_sleep_s=vu_idle_sleep_s,
        vu_startup_jitter_ms=vu_startup_jitter_ms,
    )
    if detach:
        _start_worker_detached_or_exit(
            settings=settings,
            pid_file=pid_file,
            log_file=log_file,
            startup_timeout_s=startup_timeout_s,
        )
        return
    typer.echo(f"Starting worker in foreground (worker_id={resolved_worker_id}).")
    _run_worker_foreground(settings=settings, pid_file=pid_file)


@worker_app.command("serve", hidden=True)
def worker_serve(
    redis_url: Annotated[str, typer.Option("--redis-url")] = "redis://127.0.0.1:6379/0",
    worker_id: Annotated[str | None, typer.Option("--worker-id")] = None,
    log_level: Annotated[
        str,
        typer.Option("--log-level", help="Python logging level (e.g. DEBUG, INFO, WARNING)."),
    ] = "INFO",
    heartbeat_interval_s: Annotated[
        float, typer.Option("--heartbeat-interval-s", min=0.1)
    ] = 3.0,
    command_poll_timeout_s: Annotated[
        float, typer.Option("--command-poll-timeout-s", min=0.1)
    ] = 1.0,
    graceful_stop_timeout_s: Annotated[
        float, typer.Option("--graceful-stop-timeout-s", min=0.1)
    ] = 5.0,
    scenario: Annotated[
        str,
        typer.Option(
            "--scenario",
            help="Scenario import path in `module.path:ClassName` format.",
        ),
    ] = "vikhry.runtime.defaults:IdleVU",
    http_base_url: Annotated[
        str,
        typer.Option(
            "--http-base-url",
            help="Base URL for scenario HTTP calls that use relative paths.",
        ),
    ] = "",
    vu_idle_sleep_s: Annotated[
        float,
        typer.Option(
            "--vu-idle-sleep-s",
            min=0.01,
            help="Sleep interval when scenario has no eligible steps.",
        ),
    ] = 0.05,
    vu_startup_jitter_ms: Annotated[
        float,
        typer.Option(
            "--vu-startup-jitter-ms",
            min=0.0,
            help="Max startup jitter per VU in milliseconds (uniform in [0, value]).",
        ),
    ] = 5.0,
    pid_file: Annotated[Path, typer.Option("--pid-file")] = DEFAULT_WORKER_PID_FILE,
) -> None:
    settings = WorkerSettings(
        redis_url=redis_url,
        worker_id=_resolve_worker_id(worker_id),
        log_level=log_level,
        heartbeat_interval_s=heartbeat_interval_s,
        command_poll_timeout_s=command_poll_timeout_s,
        graceful_stop_timeout_s=graceful_stop_timeout_s,
        scenario=scenario,
        http_base_url=http_base_url,
        vu_idle_sleep_s=vu_idle_sleep_s,
        vu_startup_jitter_ms=vu_startup_jitter_ms,
    )
    _run_worker_foreground(settings=settings, pid_file=pid_file)


@worker_app.command("stop")
def worker_stop(
    pid_file: Annotated[Path, typer.Option("--pid-file")] = DEFAULT_WORKER_PID_FILE,
    timeout_s: Annotated[float, typer.Option("--timeout-s", min=0.1)] = 10.0,
    force: Annotated[bool, typer.Option("--force")] = False,
) -> None:
    pid = _read_worker_pid_or_exit(pid_file)
    if pid == os.getpid():
        raise typer.Exit(
            code=_error(
                "PID file points to current process; refusing self-termination. "
                "Run stop from another shell."
            )
        )

    if not _is_process_alive(pid):
        _remove_pid_file_if_matches(pid_file, pid)
        raise typer.Exit(
            code=_error(
                f"Process {pid} is not running. Removed stale pid file `{pid_file}`."
            )
        )

    if _send_stop_signal_and_wait(pid, signal.SIGINT, timeout_s * 0.5):
        _remove_pid_file_if_matches(pid_file, pid)
        typer.echo(f"Worker process {pid} stopped.")
        raise typer.Exit(code=0)

    if _send_stop_signal_and_wait(pid, signal.SIGTERM, timeout_s * 0.5):
        _remove_pid_file_if_matches(pid_file, pid)
        typer.echo(f"Worker process {pid} stopped.")
        raise typer.Exit(code=0)

    if force:
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError as exc:
            raise typer.Exit(
                code=_error(f"Failed to force-stop process {pid} with SIGKILL: {exc}")
            ) from exc
        _remove_pid_file_if_matches(pid_file, pid)
        typer.echo(f"Worker process {pid} force-stopped.")
        raise typer.Exit(code=0)

    raise typer.Exit(
        code=_error(
            f"Process {pid} did not stop within {timeout_s:.1f}s. "
            "Use `--force` to send SIGKILL."
        )
    )


@test_app.command("start")
def test_start(
    users: Annotated[int, typer.Option("--users", "-u", min=0)],
    orchestrator_url: Annotated[str, typer.Option("--orchestrator-url")] = DEFAULT_ORCHESTRATOR_URL,
    init_param: Annotated[
        list[str] | None,
        typer.Option(
            "--init-param",
            help="Init param in key=value form. Value can be JSON literal.",
        ),
    ] = None,
    init_params_json: Annotated[
        str | None,
        typer.Option(
            "--init-params-json",
            help="JSON object with on_init params.",
        ),
    ] = None,
    timeout_s: Annotated[float, typer.Option("--timeout-s", min=0.1)] = 10.0,
) -> None:
    payload = {"target_users": users}
    parsed_init_params = _parse_init_params(init_param or [], init_params_json)
    if parsed_init_params:
        payload["init_params"] = parsed_init_params
    _call_orchestrator_json(
        method="post",
        base_url=orchestrator_url,
        path="/start_test",
        payload=payload,
        timeout_s=timeout_s,
    )
    typer.echo(f"Requested test start with target_users={users}.")


@test_app.command("change-users")
def test_change_users(
    users: Annotated[int, typer.Option("--users", "-u", min=0)],
    orchestrator_url: Annotated[str, typer.Option("--orchestrator-url")] = DEFAULT_ORCHESTRATOR_URL,
    timeout_s: Annotated[float, typer.Option("--timeout-s", min=0.1)] = 10.0,
) -> None:
    payload = {"target_users": users}
    _call_orchestrator_json(
        method="post",
        base_url=orchestrator_url,
        path="/change_users",
        payload=payload,
        timeout_s=timeout_s,
    )
    typer.echo(f"Requested target_users update to {users}.")


@test_app.command("stop")
def test_stop(
    orchestrator_url: Annotated[str, typer.Option("--orchestrator-url")] = DEFAULT_ORCHESTRATOR_URL,
    timeout_s: Annotated[float, typer.Option("--timeout-s", min=0.1)] = 10.0,
) -> None:
    _call_orchestrator_json(
        method="post",
        base_url=orchestrator_url,
        path="/stop_test",
        payload={},
        timeout_s=timeout_s,
    )
    typer.echo("Requested test stop.")


def main() -> None:
    app()


def _run_orchestrator_foreground(settings: OrchestratorSettings, pid_file: Path) -> None:
    from vikhry.orchestrator.app import run_orchestrator

    _ensure_pid_file_writable_or_exit(pid_file)
    _write_pid_file_or_exit(pid_file)
    try:
        try:
            run_orchestrator(settings)
        except ScenarioLoadError as exc:
            raise typer.Exit(code=_error(str(exc))) from exc
    finally:
        _remove_pid_file_if_matches(pid_file, os.getpid())


def _run_worker_foreground(settings: WorkerSettings, pid_file: Path) -> None:
    from vikhry.worker.app import run_worker

    _ensure_pid_file_writable_or_exit(pid_file)
    _write_worker_pid_file_or_exit(pid_file)
    try:
        run_worker(settings)
    finally:
        _remove_pid_file_if_matches(pid_file, os.getpid())


def _start_orchestrator_detached_or_exit(
    *,
    settings: OrchestratorSettings,
    pid_file: Path,
    log_file: Path,
    startup_timeout_s: float,
) -> None:
    _ensure_pid_file_writable_or_exit(pid_file)
    _ensure_no_active_orchestrator_or_exit(pid_file)

    log_parent = log_file.parent if log_file.parent != Path("") else Path(".")
    log_parent.mkdir(parents=True, exist_ok=True)

    command = [
        sys.executable,
        "-m",
        "vikhry.cli",
        "orchestrator",
        "serve",
        "--host",
        settings.host,
        "--port",
        str(settings.port),
        "--redis-url",
        settings.redis_url,
        "--heartbeat-timeout-s",
        str(settings.heartbeat_timeout_s),
        "--worker-scan-interval-s",
        str(settings.worker_scan_interval_s),
        "--metrics-poll-interval-s",
        str(settings.metrics_poll_interval_s),
        "--metrics-window-s",
        str(settings.metrics_window_s),
        "--metrics-max-events-per-poll",
        str(settings.metrics_max_events_per_poll),
        "--metrics-recent-events-per-metric",
        str(settings.metrics_recent_events_per_metric),
        "--metrics-subscriber-queue-size",
        str(settings.metrics_subscriber_queue_size),
        "--pid-file",
        str(pid_file),
    ]
    if settings.scenario:
        command.extend(["--scenario", settings.scenario])

    try:
        with log_file.open("ab") as log_handle:
            process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=log_handle,
                stderr=log_handle,
                start_new_session=True,
                close_fds=True,
            )
    except OSError as exc:
        raise typer.Exit(code=_error(f"Failed to spawn orchestrator process: {exc}")) from exc

    deadline = time.time() + startup_timeout_s
    while time.time() < deadline:
        pid = _read_pid(pid_file)
        if pid is not None and _is_process_alive(pid):
            typer.echo(
                f"Orchestrator started in background (pid={pid}). "
                f"Logs: {log_file}, pid file: {pid_file}"
            )
            raise typer.Exit(code=0)
        if process.poll() is not None:
            break
        time.sleep(0.1)

    if process.poll() is None:
        _send_stop_signal_and_wait(process.pid, signal.SIGINT, 1.0)
    if process.poll() is None:
        _send_stop_signal_and_wait(process.pid, signal.SIGTERM, 1.0)
    if process.poll() is None:
        try:
            os.kill(process.pid, signal.SIGKILL)
        except OSError:
            pass

    tail = _tail_file(log_file, max_lines=20)
    tail_suffix = f"\nRecent logs:\n{tail}" if tail else ""
    raise typer.Exit(
        code=_error(
            f"Orchestrator failed to start within {startup_timeout_s:.1f}s.{tail_suffix}"
        )
    )


def _start_worker_detached_or_exit(
    *,
    settings: WorkerSettings,
    pid_file: Path,
    log_file: Path,
    startup_timeout_s: float,
) -> None:
    _ensure_pid_file_writable_or_exit(pid_file)
    _ensure_no_active_worker_or_exit(pid_file)

    log_parent = log_file.parent if log_file.parent != Path("") else Path(".")
    log_parent.mkdir(parents=True, exist_ok=True)

    command = [
        sys.executable,
        "-m",
        "vikhry.cli",
        "worker",
        "serve",
        "--redis-url",
        settings.redis_url,
        "--worker-id",
        settings.worker_id,
        "--log-level",
        settings.log_level,
        "--heartbeat-interval-s",
        str(settings.heartbeat_interval_s),
        "--command-poll-timeout-s",
        str(settings.command_poll_timeout_s),
        "--graceful-stop-timeout-s",
        str(settings.graceful_stop_timeout_s),
        "--scenario",
        settings.scenario,
        "--http-base-url",
        settings.http_base_url,
        "--vu-idle-sleep-s",
        str(settings.vu_idle_sleep_s),
        "--vu-startup-jitter-ms",
        str(settings.vu_startup_jitter_ms),
        "--pid-file",
        str(pid_file),
    ]

    try:
        with log_file.open("ab") as log_handle:
            process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=log_handle,
                stderr=log_handle,
                start_new_session=True,
                close_fds=True,
            )
    except OSError as exc:
        raise typer.Exit(code=_error(f"Failed to spawn worker process: {exc}")) from exc

    deadline = time.time() + startup_timeout_s
    while time.time() < deadline:
        pid = _read_pid(pid_file)
        if pid is not None and _is_process_alive(pid):
            typer.echo(
                f"Worker started in background (worker_id={settings.worker_id}, pid={pid}). "
                f"Logs: {log_file}, pid file: {pid_file}"
            )
            raise typer.Exit(code=0)
        if process.poll() is not None:
            break
        time.sleep(0.1)

    if process.poll() is None:
        _send_stop_signal_and_wait(process.pid, signal.SIGINT, 1.0)
    if process.poll() is None:
        _send_stop_signal_and_wait(process.pid, signal.SIGTERM, 1.0)
    if process.poll() is None:
        try:
            os.kill(process.pid, signal.SIGKILL)
        except OSError:
            pass

    tail = _tail_file(log_file, max_lines=20)
    tail_suffix = f"\nRecent logs:\n{tail}" if tail else ""
    raise typer.Exit(
        code=_error(f"Worker failed to start within {startup_timeout_s:.1f}s.{tail_suffix}")
    )


def _ensure_pid_file_writable_or_exit(pid_file: Path) -> None:
    parent = pid_file.parent if pid_file.parent != Path("") else Path(".")
    parent.mkdir(parents=True, exist_ok=True)
    if not parent.is_dir():
        raise typer.Exit(code=_error(f"PID directory is not valid: `{parent}`"))


def _write_pid_file_or_exit(pid_file: Path) -> None:
    existing_pid = _read_pid(pid_file)
    if existing_pid is not None and _is_process_alive(existing_pid):
        raise typer.Exit(
            code=_error(
                f"Orchestrator seems already running with pid={existing_pid}. "
                f"Use `vikhry orchestrator stop --pid-file {pid_file}` first."
            )
        )
    try:
        pid_file.write_text(str(os.getpid()), encoding="ascii")
    except OSError as exc:
        raise typer.Exit(code=_error(f"Cannot write pid file `{pid_file}`: {exc}")) from exc


def _write_worker_pid_file_or_exit(pid_file: Path) -> None:
    existing_pid = _read_pid(pid_file)
    if existing_pid is not None and _is_process_alive(existing_pid):
        raise typer.Exit(
            code=_error(
                f"Worker seems already running with pid={existing_pid}. "
                f"Use `vikhry worker stop --pid-file {pid_file}` first."
            )
        )
    try:
        pid_file.write_text(str(os.getpid()), encoding="ascii")
    except OSError as exc:
        raise typer.Exit(code=_error(f"Cannot write pid file `{pid_file}`: {exc}")) from exc


def _ensure_no_active_orchestrator_or_exit(pid_file: Path) -> None:
    existing_pid = _read_pid(pid_file)
    if existing_pid is None:
        return
    if _is_process_alive(existing_pid):
        raise typer.Exit(
            code=_error(
                f"Orchestrator seems already running with pid={existing_pid}. "
                f"Use `vikhry orchestrator stop --pid-file {pid_file}` first."
            )
        )
    _remove_pid_file_if_matches(pid_file, existing_pid)


def _ensure_no_active_worker_or_exit(pid_file: Path) -> None:
    existing_pid = _read_pid(pid_file)
    if existing_pid is None:
        return
    if _is_process_alive(existing_pid):
        raise typer.Exit(
            code=_error(
                f"Worker seems already running with pid={existing_pid}. "
                f"Use `vikhry worker stop --pid-file {pid_file}` first."
            )
        )
    _remove_pid_file_if_matches(pid_file, existing_pid)


def _read_pid(pid_file: Path) -> int | None:
    try:
        raw = pid_file.read_text(encoding="ascii").strip()
    except FileNotFoundError:
        return None
    except OSError:
        return None
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _read_pid_or_exit(pid_file: Path) -> int:
    pid = _read_pid(pid_file)
    if pid is None:
        raise typer.Exit(
            code=_error(
                f"Cannot read orchestrator pid from `{pid_file}`. "
                "Start orchestrator first or pass correct `--pid-file`."
            )
        )
    return pid


def _read_worker_pid_or_exit(pid_file: Path) -> int:
    pid = _read_pid(pid_file)
    if pid is None:
        raise typer.Exit(
            code=_error(
                f"Cannot read worker pid from `{pid_file}`. "
                "Start worker first or pass correct `--pid-file`."
            )
        )
    return pid


def _remove_pid_file_if_matches(pid_file: Path, expected_pid: int) -> None:
    pid = _read_pid(pid_file)
    if pid != expected_pid:
        return
    try:
        pid_file.unlink()
    except FileNotFoundError:
        return
    except OSError:
        return


def _is_process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError as exc:
        if exc.errno == errno.ESRCH:
            return False
        if exc.errno == errno.EPERM:
            return True
        return False
    return True


def _send_stop_signal_and_wait(pid: int, sig: signal.Signals, timeout_s: float) -> bool:
    if timeout_s <= 0:
        timeout_s = 0.1
    try:
        os.kill(pid, sig)
    except OSError:
        return not _is_process_alive(pid)

    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if not _is_process_alive(pid):
            return True
        time.sleep(0.2)
    return not _is_process_alive(pid)


def _tail_file(path: Path, max_lines: int = 20) -> str:
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    lines = raw.splitlines()
    if not lines:
        return ""
    return "\n".join(lines[-max_lines:])


def _resolve_worker_id(worker_id: str | None) -> str:
    if worker_id is not None:
        normalized = worker_id.strip()
        if normalized:
            return normalized
    return uuid4().hex[:8]


def _call_orchestrator_json(
    *,
    method: str,
    base_url: str,
    path: str,
    payload: dict[str, Any] | None,
    timeout_s: float,
) -> dict[str, Any]:
    base_url = _normalize_base_url(base_url)
    url = f"{base_url}{path}"

    try:
        with SyncClientBuilder().timeout(timedelta(seconds=timeout_s)).build() as client:
            request_builder = getattr(client, method.lower())(url)
            if payload is not None:
                request_builder = request_builder.body_json(payload)
            response = request_builder.build().send()
    except PyreqwestError as exc:
        raise typer.Exit(code=_error(f"HTTP request failed: {exc}")) from exc
    except Exception as exc:  # noqa: BLE001
        raise typer.Exit(code=_error(f"Unexpected HTTP client error: {exc}")) from exc

    body_text = response.text()
    body_json: dict[str, Any] | None = None
    if body_text:
        try:
            parsed = response.json()
            if isinstance(parsed, dict):
                body_json = parsed
        except Exception:
            body_json = None

    if response.status >= 400:
        message = _extract_error_message(body_json) or body_text or "request failed"
        raise typer.Exit(
            code=_error(f"Orchestrator returned HTTP {response.status}: {message}")
        )

    if body_json is None:
        typer.echo("{}")
        return {}

    typer.echo(orjson.dumps(body_json, option=orjson.OPT_INDENT_2).decode("utf-8"))
    return body_json


def _normalize_base_url(base_url: str) -> str:
    normalized = base_url.strip().rstrip("/")
    if not normalized.startswith(("http://", "https://")):
        raise typer.Exit(
            code=_error(
                "Invalid `--orchestrator-url`: must start with `http://` or `https://`."
            )
        )
    return normalized


def _extract_error_message(payload: dict[str, Any] | None) -> str | None:
    if payload is None:
        return None
    error = payload.get("error")
    if isinstance(error, dict):
        message = error.get("message")
        if isinstance(message, str) and message:
            return message
    return None


def _parse_init_params(
    key_value_items: list[str],
    json_payload: str | None,
) -> dict[str, Any]:
    result: dict[str, Any] = {}

    if json_payload:
        try:
            parsed = orjson.loads(json_payload)
        except Exception as exc:  # noqa: BLE001
            raise typer.Exit(
                code=_error(f"Invalid `--init-params-json`: {exc}")
            ) from exc
        if not isinstance(parsed, dict):
            raise typer.Exit(
                code=_error("`--init-params-json` must be a JSON object.")
            )
        result.update({str(key): value for key, value in parsed.items()})

    for raw_item in key_value_items:
        item = raw_item.strip()
        if not item:
            continue
        if "=" not in item:
            raise typer.Exit(
                code=_error(
                    f"Invalid `--init-param` value `{raw_item}`. Use key=value format."
                )
            )
        key, raw_value = item.split("=", 1)
        key = key.strip()
        if not key:
            raise typer.Exit(
                code=_error("`--init-param` key must not be empty.")
            )
        value = _parse_init_param_value(raw_value.strip())
        result[key] = value

    return result


def _parse_init_param_value(raw_value: str) -> Any:
    if raw_value == "":
        return ""
    try:
        return orjson.loads(raw_value)
    except Exception:
        return raw_value


def _error(message: str) -> int:
    typer.secho(message, fg=typer.colors.RED, err=True)
    return 1


if __name__ == "__main__":
    main()
