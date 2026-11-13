# 전후 비교

- 전: run_id `1c9e3706-f262-48af-8ea8-ea4f19b64bb2` · 2026-11-13T06:45:17.524530+00:00 · 전체 FAIL · {'PASS': 10, 'FAIL': 2, 'UNKNOWN': 0, 'ERROR': 0}
- 후: run_id `80db5e5e-672d-4ee2-a5ec-96503efe04ef` · 2026-11-13T08:31:37.876431+00:00 · 전체 PASS · {'PASS': 11, 'FAIL': 0, 'UNKNOWN': 0, 'ERROR': 0}

> 주의: 두 실행의 모드나 범위가 달라 결과를 그대로 비교할 수 없음

| 규칙 | 자산 | SG | 내용 | 전 | 후 |
|---|---|---|---|---|---|
| SG-07 | (default SG) | sg-#d760e060 | (default SG 비어 있음) | (없음) | PASS |
| SG-07 | (default SG) | sg-#d760e060 | egress 전체 프로토콜 전체 0.0.0.0/0 | FAIL | (없음) |
| SG-07 | (default SG) | sg-#d760e060 | ingress 전체 프로토콜 전체 sg-#d760e060 | FAIL | (없음) |
