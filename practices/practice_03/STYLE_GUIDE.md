# Стиль Python: Notify Mini

Область: Python-файлы в `lab/demo/`, включая тесты. Применять при разработке и ревью.

Источник: [PEP 8 — Style Guide for Python Code](https://peps.python.org/pep-0008/).
Версия источника: актуальный текст PEP 8, проверенный 02.10.2026; статус **Active**.
PEP 8 — развивающийся документ без номера релиза; дата проверки не является номером его версии.
Версия этой проектной выжимки: **1.0**. Код проекта совместим с Python 3.10+.

## Пять правил

1. **Отступы:** четыре пробела на уровень, без табуляции в отступах.
   [Indentation](https://peps.python.org/pep-0008/#indentation).
2. **Длина строк:** код — до 79 символов, комментарии и docstring — до 72.
   Длинные выражения переносить внутри скобок, предпочитая их обратному слешу.
   [Maximum Line Length](https://peps.python.org/pep-0008/#maximum-line-length).
3. **Пустые строки:** две между функциями и классами верхнего уровня;
   одна между методами класса.
   [Blank Lines](https://peps.python.org/pep-0008/#blank-lines).
4. **Импорты:** в начале файла; группы в порядке «стандартная библиотека,
   сторонние пакеты, локальные модули», между группами — пустая строка.
   Не использовать `import *`. Несколько имён из одного модуля в `from ... import ...` допустимы.
   [Imports](https://peps.python.org/pep-0008/#imports).
5. **Имена:** функции, переменные и собственные методы — `snake_case`,
   классы — `CapWords`, константы — `UPPER_CASE`.
   Имена методов существующего API сохранять: например, `setUp` и `assertEqual` в `unittest`.
   [Naming Conventions](https://peps.python.org/pep-0008/#naming-conventions).

## Пример из фичи A

Фрагмент `lab/demo/service.py`, функция `unsubscribe`:

```python
def unsubscribe(name):
    name = name.strip()
    if not name:
        raise ValueError("empty name")
    if name not in subscribers:
        return {"unsubscribed": False}
    subscribers.remove(name)
    return {"unsubscribed": True}
```

Здесь используются отступы по четыре пробела, короткие строки и имена в нижнем регистре.
В исходном файле между `subscribe` и `unsubscribe` оставлены две пустые строки.

## Применение и проверка

При добавлении гайда просмотрены `lab/demo/service.py` и `lab/demo/test_service.py`
по пяти правилам выше. В тестах исправлено разделение групп импортов:
между `import unittest` и `from service import ...` добавлена пустая строка (правило 4).
Остальные перечисленные правила в этих двух файлах соблюдены.

При ревью сверять изменённые строки с правилами и просматривать `git diff`.
После правок Python-файлов выполнять `make check` из папки практики и `git diff --check`.
`make check` запускает Ruff (`make lint`) и тесты (`make test`).
Ruff 0.15.6 настроен в `ruff.toml`: правила E/W для оформления,
I для импортов, N для имён и F для распространённых ошибок Python.
Preview включён для проверок пустых строк и отступов; версия Ruff закреплена.
Линтер автоматизирует проверяемую часть гайда, но не заменяет ревью читаемости.
Установка и Git pre-commit описаны в `AUTOMATIC_CHECKS.md`.
