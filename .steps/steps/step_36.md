# Step 36: GitHub Actions для релиза

## Цель

Автоматизировать сборку релизных артефактов первого релиза: Python wheel/sdist с встроенным UI и Docker image для полного runtime `vikhry`.

## Принятые решения

- Один workflow c двумя jobs:
- `release-artifacts` остается для frontend build + `uv build`.
- Docker image вынесен в отдельный workflow `docker-image`, который запускается на каждый push в ветку.
- Runtime image публикуется в `ghcr.io/<owner>/<repo>`.
- На branch builds tag совпадает с именем ветки, для `main` дополнительно публикуется `latest`.
- Python package публикуется в PyPI из отдельного job через `PYPI_TOKEN`.

## Реализация

[x] Добавить workflow в `.github/workflows/` с release triggers.
[x] Настроить job сборки Python artifacts:
  - setup Node + Python + uv;
  - `./scripts/build_frontend.sh`;
  - `uv build`;
  - upload `dist/` artifacts.
[x] Добавить publish job в PyPI через `pypa/gh-action-pypi-publish`.
[x] Добавить Dockerfile для полного runtime image.
[x] Настроить отдельный workflow сборки runtime Docker image c `buildx` и publish в GHCR по branch tags.
[x] Обновить README/release notes под новый CI flow.

## Прогресс

- [x] Добавлен workflow `.github/workflows/release-artifacts.yml`.
- [x] Python artifacts job собирает frontend и выполняет `uv build`.
- [x] PyPI publish выполняется из отдельного job через `PYPI_TOKEN`.
- [x] Runtime image строится из корневого `Dockerfile`.
- [x] GHCR publish включен на каждый push в ветку, `latest` публикуется для `main`.
- [x] README обновлен с описанием release automation.

## Риски и проверки

- Важно не дублировать источник truth для frontend build: и wheel, и image должны использовать один и тот же `frontend/`.
- Workflow должен работать без обязательного PyPI publish, иначе релизный pipeline будет заблокирован секретами.
- Текущий runtime image собирается и публикуется как `linux/amd64`; это нужно явно отражать в документации для ARM-хостов.
