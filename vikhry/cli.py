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

import orjson
import typer
from pyreqwest.client import SyncClientBuilder
from pyreqwest.exceptions import PyreqwestError

from vikhry.orchestrator.models.settings import OrchestratorSettings

app = typer.Typer(
    name="vikhry",
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)
orchestrator_app = typer.Typer(no_args_is_help=True)
test_app = typer.Typer(no_args_is_help=True)
app.add_typer(orchestrator_app, name="orchestrator")
app.add_typer(test_app, name="test")

DEFAULT_ORCHESTRATOR_URL = "http://127.0.0.1:8080"
DEFAULT_PID_FILE = Path(".vikhry-orchestrator.pid")
DEFAULT_LOG_FILE = Path(".vikhry-orchestrator.log")


@orchestrator_app.command("start")
def orchestrator_start(
    host: Annotated[str, typer.Option("--host")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port", min=1, max=65535)] = 8080,
    redis_url: Annotated[str, typer.Option("--redis-url")] = "redis://127.0.0.1:6379/0",
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


@test_app.command("start")
def test_start(
    users: Annotated[int, typer.Option("--users", "-u", min=0)],
    orchestrator_url: Annotated[str, typer.Option("--orchestrator-url")] = DEFAULT_ORCHESTRATOR_URL,
    timeout_s: Annotated[float, typer.Option("--timeout-s", min=0.1)] = 10.0,
) -> None:
    payload = {"target_users": users}
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
        run_orchestrator(settings)
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


def _error(message: str) -> int:
    typer.secho(message, fg=typer.colors.RED, err=True)
    return 1


if __name__ == "__main__":
    main()
