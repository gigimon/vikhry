# Step 34: Embedding UI into the Python Package

## Goal

Make the UI part of the release Python package so that, after installing `vikhry`, orchestrator can serve the SPA without a separate frontend runtime.

## Decisions

- UI source stays in `frontend/` as a standalone Vite project.
- The release frontend build is stored as package data inside `vikhry`, not read from the repository root.
- Orchestrator continues to serve API and WebSocket endpoints while UI routes are served from embedded static assets.
- SPA routes use `index.html` fallback for non-API GET requests.
- Frontend development remains separate through `npm run dev`.

## Implementation

[x] Defined a package directory for embedded assets suitable for wheel and sdist.
[x] Updated `pyproject.toml` and hatch configuration to include built assets in Python distribution.
[x] Added a reproducible frontend build script and build hook for `frontend/dist`.
[x] Added a runtime resolver for UI assets (`vikhry/_ui`) with fallback to `frontend/dist` in a checkout.
[x] Registered `index.html`, root static files, and `/assets` in Robyn.
[x] Prevented conflicts between UI fallback and API/WebSocket routes through explicit backend route registration.
[x] Updated startup and release documentation.

## Progress

- [x] `./scripts/build_frontend.sh` builds the current Vite output
- [x] `uv build --out-dir dist-check` successfully packs `vikhry/_ui/*` into sdist and wheel
- [x] Orchestrator serves UI from `/` and assets from `/assets`
- [x] Frontend defaults to same-origin API calls, matching the embedded deployment

## Risks and Checks

- Packaging must fail loudly if assets are missing.
- Runtime must not depend on `frontend/` being present next to an installed package.
- UI fallback must not intercept existing API tests and backend routes.
