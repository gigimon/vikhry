# Step 35: `infra` CLI Command

## Goal

Provide a local operational mode for the first release: start Redis, orchestrator, and multiple workers for a scenario with a single CLI command.

## Decisions

- New CLI namespace: `vikhry infra`
- Minimal API:
  - `vikhry infra up --worker-count N --scenario module.path:ClassName`
  - `vikhry infra down`
- Redis is started only through the local Docker daemon.
- Use a dedicated container name and a dedicated runtime directory inside `DEFAULT_RUNTIME_DIR / "infra"`.
- `infra up` reuses existing detached startup helpers for orchestrator and workers.
- Any startup failure triggers best-effort cleanup of already started processes and the Redis container.

## Implementation

[x] Added `infra_app` to the Typer CLI.
[x] Extracted shared detached-process helpers for reuse across regular commands and `infra`.
[x] Implemented Docker CLI and daemon availability checks.
[x] Implemented Redis container startup with a fixed name and readiness check via `PING`.
[x] Implemented `infra up`:
  - orchestrator at `127.0.0.1:8080`
  - Redis at `redis://127.0.0.1:6379/0`
  - worker IDs like `infra-worker-<n>`
  - pid and log files inside `.../vikhry/infra/`
[x] Implemented `infra down` to stop workers, stop orchestrator, and remove the Redis container.
[x] Updated README and CLI docs for the new operational mode.

## Progress

- [x] `vikhry infra up --worker-count N --scenario ...` registered in the CLI
- [x] Docker checks and Redis readiness added
- [x] Orchestrator and worker startup reuse the common detached bootstrap
- [x] Best-effort cleanup added, including `vikhry infra down`
- [x] README and `docs/0_cli.md` updated

## Risks and Checks

- Missing `docker` or daemon connectivity must fail explicitly.
- Already running infrastructure must not be overwritten silently.
- Cleanup must stay idempotent and safe for partially successful startup.
