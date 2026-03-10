# Step 37: Public Documentation

## Цель

Поддерживать публичную документацию первого релиза как отдельный слой поверх существующих markdown-материалов репозитория.

## Принятые решения

- Новые страницы:
  - `docs/index.md` как landing;
  - `docs/quickstart.md` под сценарий первого запуска через `vikhry infra up`;
  - `docs/release.md` под packaged UI, release artifacts и CI flow.
- Существующие технические документы (`0_cli.md`, `1_architecture.md`, `2_orchestrator.md`, `3_worker.md`, `4_test_structure.md`, `5_ui.md`, `contracts/v1.md`) поддерживаются как plain Markdown.
- Конкретный documentation generator и publishing flow будут выбраны отдельно.

## Реализация

[x] Создать `docs/index.md`, `docs/quickstart.md`, `docs/release.md`.
[x] Перевести публичную документацию на английский.
[x] Обновить README и docs под хранение documentation content в plain Markdown.
[ ] Выбрать новый documentation generator.
[ ] Добавить новый publishing flow после выбора генератора.

## Прогресс

- [x] Добавлены landing, quickstart и release страницы.
- [x] Публичная документация переведена на английский.
- [x] Previous documentation-site tooling was removed from the repository.
- [ ] Новый generator/publishing flow еще не выбран.

## Риски и проверки

- Важно не дублировать уже существующие docs-файлы без необходимости.
- Quickstart должен отражать новый релизный путь через `infra up`, а не старый ручной bootstrap.
- Стоит сохранить простую структуру документации, пока не выбран новый сайт-генератор.
