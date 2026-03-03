# Step 30: UI breakdown и операционная видимость

## Цель

Добавить в UI прозрачную диагностику ошибок и исходов выполнения на базе `result_code`/`result_category`/`fatal`.

## Реализация

[ ] Добавить в API typings frontend поля новых агрегатов из `/metrics`:
  - `result_code_counts`;
  - `result_category_counts`;
  - `fatal_count`;
  - `top_result_codes` (+`OTHER`).
[ ] Реализовать на вкладке статистики блок breakdown:
  - топ result codes;
  - распределение по категориям;
  - отдельный индикатор fatal lifecycle ошибок.
[ ] Добавить фильтрацию/группировку по `source` (`lifecycle`, `step`, `http`, ...).
[ ] Обеспечить стабильный UX на больших объемах:
  - top-K + `OTHER`;
  - ограничение числа отображаемых строк;
  - сортировка по убыванию частоты.
[ ] Добавить frontend тесты форматирования/рендера breakdown и smoke-проверки.
[ ] Обновить `docs/5_ui.md` описанием новых блоков.

## Прогресс

- [ ] Типы frontend обновлены.
- [ ] UI breakdown реализован.
- [ ] Тесты frontend проходят.
