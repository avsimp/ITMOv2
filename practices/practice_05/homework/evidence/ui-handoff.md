# Передача UI команде API

## Начало реализации

Контракт 1.0.0/agreed прочитан; API-компонент доступен в app/ и проверен стороной API.
UI использует только index.html и assets/ на том же origin. Общий YAML, API-код,
исходный подборщик и снимки before/after не изменяются.
Чеклист требований: 16/16, прочитан без изменения маркеров.

API-D0: Python pytest/Playwright/yaml/jsonschema импортируются из api/.venv.
API-D1/D2: обработчики и статическая выдача изучены в API; фактические браузерные
прогоны UI будут записаны отдельно после реализации. На порту 8000 при начале работы
слушающего процесса не было; проверки запускают собственный сервер с отдельным storage.

Команда запуска API из его каталога:
`.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1`.

## Передача после реализации и браузерных проверок

UI-D1: реальные index.html/assets поставлены и обслужены настоящим API.
UI-D2: реализованы pending/failed/unknown, redirect:error, result/preview/teacher,
Blob и полный GET без Range. UI-D3: реальные PDF/ZIP, restart, удаление материала,
offline-поиск и TCP loss после заголовков проверены. **Полная совместная приёмка открыта**:
pre-header разрыв B-01 и Firefox E-01 остаются непройденными.

Фактические результаты: 30 CONTROLLED + 4 REAL-LOCAL = 34 passed;
LIVE-UI = 4 passed; отдельный boundary_probe = 1 failed; Ruff — All checks passed.
Подробные команды, UUID, источники артефактов и ограничения:
[ui-verification.md](ui-verification.md). Трассировка требований:
[ui-acceptance.md](ui-acceptance.md).

### Вопрос API/человеку B-01

При реальном закрытии TCP до получения заголовков Chromium дал один request-event
для JS Fetch, но TCP relay зафиксировал два POST, API создал два work_id и UI получил 201.
Подмена ответов не использовалась.
Воспроизведение: из ui/ выполнить
`../api/.venv/bin/python -m pytest tests/test_ui.py -q -s -m boundary_probe`.
Тест намеренно не объявлен passed/xfail. После заголовков потерянное тело корректно
даёт unknown без автоматического повтора; это отдельный успешный сценарий.

Нужно совместно определить допустимое решение для транспортной повторной отправки.
UI не добавлял retry, идемпотентные поля, новые endpoint, изменения конфигурации API
или контракта. Нельзя закрывать A-02/A-07 только на основании успеха основного happy path.

### Готовые файлы

- ui/index.html, ui/assets/styles.css и пять JS-модулей app/api/state/render/downloads.
- ui/tests/, ui/pytest.ini, ui/.gitignore, ui/README.md.
- UI tasks.md с выполненными задачами и открытыми gates, обновлённый quickstart.md.
- evidence/ui-handoff.md, ui-verification.md, ui-controlled.md, ui-live.md,
  ui-contract.md, ui-browser.md, ui-compatibility.md, ui-acceptance.md.

Runtime .test-artifacts не включается в коммит. API-код, исходный подборщик,
общий контракт, снимки before/after и checklist не редактировались UI.
Редактирование UI завершено. Файлы переданы API-чату на проверку; коммит не выполнялся,
полная приёмка из-за описанных блокеров не объявлена успешной.
