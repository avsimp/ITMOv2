# Проверка контракта со стороны UI

Единственный YAML: contracts/api-v1.yaml, 1.0.0/agreed; не менялся.
tests/contract_support.py загружает его напрямую, без второй схемы.
tests/test_contract_conformance.py проверяет шесть настоящих HTTP-операций:
CategoryResult/SearchResult, бинарный task resource, POST 201 Work, GET Work,
все основные материалы/их MIME и Content-Disposition/nosniff, SourcesManifest и 422.

Этот тест прошёл на REAL-LOCAL: реальные UI/API/Bank/export, фиксирован только upstream.
LIVE-UI дополнительно проверил настоящие Work/поисковые страницы/источники, файлы
и 404/400/422, Range 206/400/416. Успех форматов не закрывает транспортный блокер B-01.
Подробности и фактические команды: [ui-verification.md](ui-verification.md).
