# Step 36: GitHub Actions for Release Automation

## Goal

Automate release artifact production for the first release: Python wheel and sdist with embedded UI, plus a Docker image for the full `vikhry` runtime.

## Decisions

- Use a workflow split across artifact publishing and Docker image publishing.
- `release-artifacts` handles frontend build plus `uv build`.
- Docker image publishing is separated into a dedicated `docker-image` workflow on each branch push.
- Runtime images are published to `ghcr.io/<owner>/<repo>`.
- Branch builds use the branch name as the tag; `main` additionally publishes `latest`.
- Python package publishing to PyPI happens in a dedicated job via `PYPI_TOKEN`.

## Implementation

[x] Added release workflows in `.github/workflows/`.
[x] Configured Python artifact build jobs:
  - setup Node, Python, and `uv`
  - run `./scripts/build_frontend.sh`
  - run `uv build`
  - upload `dist/` artifacts
[x] Added a PyPI publish job through `pypa/gh-action-pypi-publish`.
[x] Added a Dockerfile for the full runtime image.
[x] Configured a separate Docker image workflow using `buildx` and publishing to GHCR.
[x] Updated README and release notes for the CI flow.

## Progress

- [x] Added `.github/workflows/release-artifacts.yml`
- [x] Python artifact job builds frontend and runs `uv build`
- [x] PyPI publish runs in a separate job via `PYPI_TOKEN`
- [x] Runtime image builds from the root `Dockerfile`
- [x] GHCR publish runs on every branch push, with `latest` for `main`
- [x] README updated with release automation details

## Risks and Checks

- Wheel and image must share the same frontend build source of truth.
- Workflow must not require PyPI secrets to execute non-publish paths.
- The runtime image is currently published as `linux/amd64`; documentation must state that clearly for ARM hosts.
