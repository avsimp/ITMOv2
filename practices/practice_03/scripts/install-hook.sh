#!/bin/bash
set -eu

root=$(git rev-parse --show-toplevel)
hooks=$(git rev-parse --path-format=absolute --git-path hooks)
source="$root/practices/practice_03/scripts/pre-commit"
destination="$hooks/pre-commit"

if [ -e "$destination" ] || [ -L "$destination" ]; then
    if cmp -s "$source" "$destination" && [ -x "$destination" ]; then
        printf 'Хук уже установлен: %s\n' "$destination"
        exit 0
    fi
    printf 'Существующий хук сохранён: %s. Требуется ручное объединение.\n' "$destination" >&2
    exit 1
fi

mkdir -p "$hooks"
install -m 755 "$source" "$destination"
printf 'Установлен Git pre-commit: %s\n' "$destination"
