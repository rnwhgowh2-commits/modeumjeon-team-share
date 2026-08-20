#!/usr/bin/env bash
# SessionStart hook: safely sync local main with origin without touching
# uncommitted work or the currently checked-out branch's history.
set -uo pipefail

root="$(git rev-parse --show-toplevel 2>/dev/null)" || exit 0
cd "$root" || exit 0

cur="$(git branch --show-current 2>/dev/null)"

if [ "$cur" = "main" ]; then
  out="$(git pull origin main --ff-only 2>&1)"
  status=$?
else
  out="$(git fetch origin main:main 2>&1)"
  status=$?
fi

if [ $status -eq 0 ]; then
  msg="main 최신화 완료 (현재 브랜치: ${cur:-detached})"
else
  last_line="$(printf '%s\n' "$out" | tail -1)"
  msg="main 자동 pull/fetch 실패 - 수동 확인 필요: ${last_line}"
fi

esc="$(printf '%s' "$msg" | sed 's/\\/\\\\/g; s/"/\\"/g')"
printf '{"systemMessage": "%s"}' "$esc"
