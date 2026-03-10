# Step 37: Public Documentation

## Цель

Поддерживать публичную документацию первого релиза как отдельный статический сайт на Starlight.

## Принятые решения

- Generator: `@astrojs/starlight`.
- Публичная документация живет внутри отдельного docs app в каталоге `docs/`.
- Для первого docs-итерационного среза фиксируем только три раздела:
  - `Introduction`
  - `How to Run`
  - `Scenario`
- Для стабильной сборки используем зафиксированный dependency set, совместимый с официальным Starlight example tree.
- Встроенный Starlight 404 route отключен, используется собственный `src/pages/404.astro`.

## Реализация

[x] Создать Starlight app в `docs/` (`package.json`, `astro.config.mjs`, content config, public assets).
[x] Подготовить страницы `src/content/docs/index.mdx`, `how-to-run.md`, `scenario.md`.
[x] Описать install flow через PyPI и запуск через `vikhry infra up`.
[x] Задокументировать сценарий, lifecycle hooks, step fields и resource model.
[x] Добавить локальные команды docs build/dev в `README.md`.
[ ] Добавить publishing flow для GitHub Pages.

## Прогресс

- [x] Starlight выбран и внедрен.
- [x] Начальные разделы `Introduction`, `How to Run`, `Scenario` готовы.
- [x] `npm run build` и `npm run check` проходят.
- [ ] Публикация на GitHub Pages еще не добавлена.

## Риски и проверки

- Нужно держать docs content минимальным и не расползаться обратно в дублирование с `README.md`.
- `How to Run` должен оставаться синхронным с фактическими CLI флагами.
- При обновлении зависимостей Starlight важно не терять совместимый lock tree: плавающие патч-версии уже ломали `astro build`.
