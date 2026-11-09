#!/usr/bin/env bash
# Django 시험 로그에서 "Ran N test(s)"를 찾아 N이 0이거나 줄이 없으면 실패시킨다.
# 왜: 시험 수집이 잘못돼 0건이 실행돼도 Django는 OK로 끝날 수 있어, CI가 아무것도 안 하고 초록불이 되는 걸 막는다.
set -euo pipefail
log="${1:?usage: require_tests_ran.sh <test-log>}"
[ -f "$log" ] || { echo "ERROR: test log not found: $log" >&2; exit 1; }
n=$(grep -oE '^Ran [0-9]+ tests?' "$log" | grep -oE '[0-9]+' | tail -n 1 || true)
if [ -z "$n" ]; then
  echo "ERROR: no 'Ran N tests' line in $log (tests did not run)" >&2
  exit 1
fi
if [ "$n" -eq 0 ]; then
  echo "ERROR: 0 tests ran" >&2
  exit 1
fi
echo "OK: $n tests ran"
