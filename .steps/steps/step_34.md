# Step 34: Встраивание UI в Python-пакет

## Цель

Сделать UI частью релизного Python-пакета, чтобы после установки `vikhry` orchestrator мог сразу отдавать SPA без отдельного frontend runtime.

## Принятые решения

- Источник UI остается в `frontend/` как отдельный Vite-проект.
- Релизный build frontend складывается в package data внутри `vikhry`, а не читается из корня репозитория.
- Orchestrator отдает API и WebSocket как раньше, а UI-маршруты обслуживает из встроенной статики.
- Для SPA используется fallback на `index.html` для не-API GET-маршрутов.
- Dev-режим frontend не смешивается с packaged runtime: локальная разработка UI остается через `npm run dev`.

## Реализация

[x] Определить package directory для встроенных assets, который можно безопасно включать в wheel/sdist.
[x] Обновить `pyproject.toml`/hatch config для включения built assets в Python distribution.
[x] Добавить reproducible frontend build script и build-hook для включения `frontend/dist` в package data.
[x] Добавить runtime-resolver директории UI-assets (`vikhry/_ui` с fallback на `frontend/dist` в checkout).
[x] Зарегистрировать в Robyn раздачу `index.html`, корневых static files и `/assets`.
[x] Исключить конфликт UI-раздачи с API/WebSocket endpoints за счет явной регистрации backend routes и точечных UI-routes.
[x] Обновить документацию первого запуска и release expectations.

## Прогресс

- [x] `./scripts/build_frontend.sh` собирает актуальный Vite build.
- [x] `uv build --out-dir dist-check` успешно собирает `sdist` и `wheel` с `vikhry/_ui/*`.
- [x] Orchestrator поднимает UI с `/` и static assets с `/assets`.
- [x] Frontend по умолчанию использует same-origin API, что совместимо со встроенной раздачей.

## Риски и проверки

- Если assets не собраны, packaging должен падать явно, а не выпускать пустой wheel.
- Нужно избежать зависимости runtime от наличия `frontend/` рядом с установленным пакетом.
- Важно не сломать текущие API тесты: UI fallback не должен перехватывать backend routes.
