# Release

## Python package

The Python package includes frontend assets inside `vikhry/_ui`.

Build locally:

```bash
./scripts/build_frontend.sh
uv build
```

The package version is taken from `project.version` in `pyproject.toml`.

## Runtime image

The project runtime image is built from the repository root `Dockerfile`.

Build locally:

```bash
docker build --platform linux/amd64 -t vikhry:local .
```

The image:
- builds frontend assets in a separate stage;
- copies the built UI into the package tree;
- installs the Python package and runtime dependencies;
- uses `vikhry` as the entrypoint.

Example:

```bash
docker run --rm --platform linux/amd64 vikhry:local --help
```

## GitHub Actions

`release-artifacts.yml`:
- builds frontend assets;
- builds Python `wheel` and `sdist`;
- uploads built artifacts;
- publishes the package to PyPI using `PYPI_TOKEN`.

`docker-image.yml`:
- runs on every branch push;
- builds the runtime image;
- publishes `ghcr.io/<owner>/<repo>`;
- tags branch builds with the branch name;
- publishes `latest` for `main`.

## Documentation

Public documentation currently remains in the repository as plain Markdown files under `docs/`.
