# CONTROLLED UI

Фактический итог: 30 браузерных сценариев на Chromium прошли в составе
`pytest -m 'controlled or real_local'`: всего 34 passed, из них 4 REAL-LOCAL.
API и ресурсы в CONTROLLED подменены Playwright, JSON проверен по общему контракту.
Лимит 100/101 проверен через кнопки, дедупликация/порядок — через UI и настоящий ES-модуль.

Команды, red/green история, проверенные классы ошибок и ограничения описаны в
[ui-verification.md](ui-verification.md#controlled--ответы-api-и-ресурсы-подменены).
Это не подтверждение живого Bank/export или Firefox; эти уровни учитываются отдельно.
