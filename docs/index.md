# vikhry

`vikhry` is an async distributed load-testing framework with an orchestrator/worker architecture, Redis-backed coordination, and a built-in web UI.

Source repository: [gigimon/vikhry](https://github.com/gigimon/vikhry)

## What is included in the first release

- a Python package with the bundled UI;
- local environment bootstrap through `vikhry infra up`;
- Python package publishing and Docker image automation;
- public documentation written as Markdown under `docs/`.

## Common use cases

- start a full local test environment quickly;
- install the package and use the UI without a separate frontend server;
- write load scenarios in Python using the VU DSL;
- build and publish package and container artifacts.

## Next steps

- [Quickstart](quickstart.md)
- [CLI](0_cli.md)
- [Architecture](1_architecture.md)
- [Release](release.md)
