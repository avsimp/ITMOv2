#!/bin/bash
# Запускать из папки практики через make check.
set -u

result=0
for target in lint test; do
    printf '\ncommand=make %s\n' "$target"
    make "$target"
    code=$?
    printf 'command=make %s exit_code=%s\n' "$target" "$code"
    if [ "$code" -ne 0 ]; then
        result=1
    fi
done

printf 'check exit_code=%s\n' "$result"
exit "$result"
