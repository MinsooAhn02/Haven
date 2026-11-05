# 필수(설명은 AI를 돌렸습니다. 이민성 역시 자세히 아는것이 아니며 AI를 돌린 결과물이라 난이도 및 자료공부가 필요함)

---

## 3. 네트워크 보안 장비 (IPS)

### 보안 장비별 역할 분리

| 계층 | 장비/서비스 | 위치 | 담당 |
|---|---|---|---|
| L7 웹 | AWS WAF | ALB에 연결 | SQLi, XSS, 악성 봇, 요청 속도 제한 (HTTP 내용 검사) |
| L3~L4/L7 네트워크 | AWS Network Firewall | VPC 경계 (방화벽 서브넷) | 악성 IP·도메인 차단, 아웃바운드 도메인 허용 목록, 비허용 포트·프로토콜 차단 |
| 위협 탐지 | GuardDuty | 계정 전체 (로그 분석) | 무차별 대입, 악성 IP 통신, 비정상 API 호출 탐지 |

> Network Firewall의 상태 저장 규칙 엔진은 **Suricata 호환 규칙**을 사용한다.
> 즉 Suricata는 별도 장비가 아니라 Network Firewall에 적용하는 **규칙 문법**이다.

### Network Firewall 규칙 예시

| 규칙 | 유형 | 목적 |
|---|---|---|
| AWS 관리형 위협 서명 (악성 도메인, 봇넷 C&C) | 관리형 | 알려진 악성 통신 차단 |
| 아웃바운드 도메인 허용 목록 (`.ubuntu.com`, `.amazonaws.com`) | 도메인 목록 | NAT 경유 외부 통신을 필요한 곳으로만 제한 |
| 인바운드 80·443 외 차단 | 상태 저장 | 불필요한 포트 접근 차단 |

```
# Suricata 호환 규칙 예시: 웹 서브넷으로 들어오는 SSH 차단
drop tcp any any -> 10.0.1.0/24 22 (msg:"Block inbound SSH"; sid:1000001; rev:1;)
```

> HTTPS 트래픽은 암호화되어 있어 Network Firewall에서 내용 검사가 불가하므로,
> 웹 공격(SQLi, XSS) 탐지는 TLS가 종료되는 ALB 앞단의 **WAF가 담당**한다.

### 검토 후 제외한 항목

| 항목 | 제외 사유 |
|---|---|
| fail2ban | SSH 포트를 Session Manager로 대체하여 차단 대상 없음. ALB 경유로 서버 로그에 ALB IP가 기록되어, 차단 시 정상 사용자 전체가 차단될 위험 |
| 호스트 Suricata | Network Firewall에서 동일 규칙 엔진으로 VPC 경계 검사를 수행하므로 중복 |

---
