"""SG 설정 점검 CLI (읽기 전용) - 이민성

network/설계.md 4장의 SG 연결표(baseline.json)와 실제(또는 fixture) SG 규칙을 비교해
PASS / FAIL / UNKNOWN / ERROR 로 판정한다.

사용법 (1회차: fixture 모드만 구현):
    python network_audit.py fixture --fixture <json> --baseline <json> --output-dir <새 폴더>

종료 코드: 0=PASS, 1=FAIL, 2=ERROR, 3=UNKNOWN (여러 개면 ERROR > UNKNOWN > FAIL > PASS)
"""

import argparse
import csv
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

TOOL_VERSION = "0.1.0"

# 인터넷 전체를 뜻하는 주소
PUBLIC_CIDRS = {"0.0.0.0/0", "::/0"}
# 인터넷에 열리면 안 되는 포트: SSH, RDP, PostgreSQL
SENSITIVE_PORTS = {22: "SSH", 3389: "RDP", 5432: "PostgreSQL"}

EXIT_CODE = {"PASS": 0, "FAIL": 1, "ERROR": 2, "UNKNOWN": 3}

FINDING_FIELDS = [
    "check_id", "region", "vpc_id", "sg_id", "asset_id", "asset_role",
    "direction", "protocol", "from_port", "to_port", "source_type", "source_value",
    "expected", "actual", "verdict", "reason", "evidence",
]


# ---------------------------------------------------------------------------
# 1. 파일 읽기
# ---------------------------------------------------------------------------
def load_json(path):
    """JSON 파일을 읽어 파이썬 dict로 돌려준다. 실패하면 ValueError."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        raise ValueError(f"파일이 없습니다: {path}")
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON 문법 오류: {path} ({e})")


# ---------------------------------------------------------------------------
# 2. AWS 모양의 SG 규칙을 한 줄짜리 규칙 목록으로 펼치기
# ---------------------------------------------------------------------------
def flatten_rules(sg):
    """SG 하나의 IpPermissions/IpPermissionsEgress를
    {direction, protocol, from_port, to_port, source_type, source_value} 목록으로 바꾼다."""
    rules = []
    for direction, key in (("ingress", "IpPermissions"), ("egress", "IpPermissionsEgress")):
        for perm in sg.get(key, []):
            protocol = str(perm.get("IpProtocol", "")).lower()
            from_port = perm.get("FromPort")
            to_port = perm.get("ToPort")
            base = {"direction": direction, "protocol": protocol,
                    "from_port": from_port, "to_port": to_port}
            for r in perm.get("IpRanges", []):
                rules.append({**base, "source_type": "cidr", "source_value": r.get("CidrIp")})
            for r in perm.get("Ipv6Ranges", []):
                rules.append({**base, "source_type": "cidr", "source_value": r.get("CidrIpv6")})
            for r in perm.get("UserIdGroupPairs", []):
                rules.append({**base, "source_type": "sg", "source_value": r.get("GroupId")})
            for r in perm.get("PrefixListIds", []):
                rules.append({**base, "source_type": "prefix_list", "source_value": r.get("PrefixListId")})
    return rules


# ---------------------------------------------------------------------------
# 3. 판정
# ---------------------------------------------------------------------------
def covers_port(rule, port):
    """규칙이 특정 포트를 포함하는지. 전체 프로토콜(-1)이나 포트가 없으면 포함으로 본다."""
    if rule["protocol"] == "-1" or rule["from_port"] is None or rule["to_port"] is None:
        return True
    return rule["from_port"] <= port <= rule["to_port"]


def same_rule(actual, allowed):
    """실제 규칙(SG 참조는 역할로 바꾼 뒤)이 허용 규칙과 정확히 같은지."""
    return (actual["direction"] == allowed["direction"]
            and actual["protocol"] == allowed["protocol"]
            and actual["from_port"] == allowed["from_port"]
            and actual["to_port"] == allowed["to_port"]
            and actual["source_type"] == allowed["source_type"]
            and actual["source_value"] == allowed["source_value"])


def describe(rule):
    """사람이 읽기 쉬운 규칙 설명. 예: ingress tcp 5432-5432 cidr:0.0.0.0/0"""
    return (f'{rule["direction"]} {rule["protocol"]} {rule["from_port"]}-{rule["to_port"]} '
            f'{rule["source_type"]}:{rule["source_value"]}')


def classify_violation(rule, role):
    """허용표에 없는 규칙의 check_id와 이유를 정한다. 더 심각한 것부터 확인한다."""
    if rule["direction"] == "ingress" and rule["source_value"] in PUBLIC_CIDRS:
        for port, name in SENSITIVE_PORTS.items():
            if covers_port(rule, port):
                return "SG-01", f"인터넷 전체({rule['source_value']})에 {name}({port}) 포트가 열려 있음"
    if rule["protocol"] == "-1":
        return "SG-02", "전체 프로토콜(-1) 허용 규칙"
    if role == "web" and rule["direction"] == "ingress" and covers_port(rule, 80):
        return "SG-03", "Web TCP 80의 출발지가 ALB SG가 아님"
    if role == "db" and rule["direction"] == "ingress" and covers_port(rule, 5432):
        return "SG-04", "DB TCP 5432의 출발지가 Web SG가 아님"
    return "SG-05", "baseline 허용표에 없는 규칙"


def make_finding(ctx, **kw):
    """finding 한 줄을 만든다. 빠진 필드는 빈 값으로 채운다."""
    finding = {field: "" for field in FINDING_FIELDS}
    finding["region"] = ctx["region"]
    finding["vpc_id"] = ctx["vpc_id"]
    finding.update(kw)
    return finding


def audit(baseline, fixture):
    """baseline과 fixture를 비교해 findings 목록을 만든다."""
    ctx = {"region": fixture.get("region", ""), "vpc_id": fixture.get("vpc_id", "")}
    findings = []

    # baseline 정리: 자산 → 역할, SG ID → 역할
    asset_role = {a["asset_id"]: a["asset_role"] for a in baseline.get("assets", [])}
    expected_sgs = {a["asset_id"]: a.get("expected_sg_ids", []) for a in baseline.get("assets", [])}
    sg_role = {}
    for a in baseline.get("assets", []):
        for sg_id in a.get("expected_sg_ids", []):
            sg_role[sg_id] = a["asset_role"]
    allowed_by_role = {}
    for rule in baseline.get("allowed_rules", []):
        allowed_by_role.setdefault(rule["asset_role"], []).append(rule)

    # fixture 정리: SG ID → SG 정보
    sgs = {sg["GroupId"]: sg for sg in fixture.get("security_groups", [])}
    attached_sg_ids = set()

    for att in fixture.get("attachments", []):
        asset_id = att["asset_id"]
        sg_ids = att.get("sg_ids", [])
        attached_sg_ids.update(sg_ids)

        # (1) baseline에 없는 자산 → UNKNOWN (SG-06)
        if asset_id not in asset_role:
            findings.append(make_finding(
                ctx, check_id="SG-06", sg_id=";".join(sg_ids), asset_id=asset_id,
                expected="baseline에 정의된 자산", actual="정의되지 않은 자산",
                verdict="UNKNOWN", reason="baseline에 없는 자산이라 역할과 허용 규칙을 알 수 없음",
                evidence=f"attachments: {asset_id} -> {sg_ids}"))
            continue

        role = asset_role[asset_id]

        # (2) 기대 SG가 붙어 있지 않음 → FAIL (SG-05)
        for missing in set(expected_sgs[asset_id]) - set(sg_ids):
            findings.append(make_finding(
                ctx, check_id="SG-05", sg_id=missing, asset_id=asset_id, asset_role=role,
                expected=f"{missing} 연결", actual="연결 안 됨", verdict="FAIL",
                reason="baseline의 기대 SG가 자산에 연결되어 있지 않음",
                evidence=f"attachments: {asset_id} -> {sg_ids}"))

        # (3) 자산에 붙은 모든 SG 규칙의 합집합
        effective = []
        for sg_id in sg_ids:
            if sg_id not in sgs:
                findings.append(make_finding(
                    ctx, check_id="SG-06", sg_id=sg_id, asset_id=asset_id, asset_role=role,
                    expected="SG 규칙 수집", actual="수집 결과 없음", verdict="UNKNOWN",
                    reason="자산에 연결된 SG의 규칙을 찾을 수 없음", evidence=f"sg_id: {sg_id}"))
                continue
            for rule in flatten_rules(sgs[sg_id]):
                effective.append((sg_id, rule))

        allowed = allowed_by_role.get(role, [])
        matched_allowed = set()

        # (4) 실제 규칙 하나하나를 허용표와 비교
        for sg_id, rule in effective:
            compare = dict(rule)
            if rule["source_type"] == "sg":
                if rule["source_value"] not in sg_role:
                    findings.append(make_finding(
                        ctx, check_id="SG-06", sg_id=sg_id, asset_id=asset_id, asset_role=role,
                        **{k: rule[k] for k in ("direction", "protocol", "from_port", "to_port",
                                                "source_type", "source_value")},
                        expected="baseline에 정의된 SG 참조", actual=describe(rule),
                        verdict="UNKNOWN", reason="참조한 SG의 역할을 알 수 없음",
                        evidence=f"{sg_id}: {describe(rule)}"))
                    continue
                compare["source_type"] = "sg_role"
                compare["source_value"] = sg_role[rule["source_value"]]

            hit = next((i for i, a in enumerate(allowed) if same_rule(compare, a)), None)
            common = dict(check_id="SG-05", sg_id=sg_id, asset_id=asset_id, asset_role=role,
                          direction=rule["direction"], protocol=rule["protocol"],
                          from_port=rule["from_port"], to_port=rule["to_port"],
                          source_type=rule["source_type"], source_value=rule["source_value"],
                          actual=describe(compare), evidence=f"{sg_id}: {describe(rule)}")
            if hit is not None:
                matched_allowed.add(hit)
                findings.append(make_finding(
                    ctx, **common, expected=describe(allowed[hit]),
                    verdict="PASS", reason="baseline 허용 규칙과 일치"))
            else:
                check_id, reason = classify_violation(compare, role)
                common["check_id"] = check_id
                findings.append(make_finding(
                    ctx, **common, expected="허용표에 없음(거부되어야 함)",
                    verdict="FAIL", reason=reason))

        # (5) 허용표에는 있는데 실제로 없는 규칙 → FAIL (SG-05)
        for i, a in enumerate(allowed):
            if i not in matched_allowed:
                findings.append(make_finding(
                    ctx, check_id="SG-05", asset_id=asset_id, asset_role=role,
                    direction=a["direction"], protocol=a["protocol"],
                    from_port=a["from_port"], to_port=a["to_port"],
                    source_type=a["source_type"], source_value=a["source_value"],
                    expected=describe(a), actual="규칙 없음", verdict="FAIL",
                    reason="baseline 허용 규칙이 실제로 없음(서비스 연결 실패 가능)",
                    evidence=f"asset: {asset_id}"))

    # (6) 어느 자산에도 연결되지 않은 SG → UNKNOWN (SG-06)
    for sg_id in sgs:
        if sg_id not in attached_sg_ids:
            findings.append(make_finding(
                ctx, check_id="SG-06", sg_id=sg_id, expected="자산에 연결된 SG",
                actual="연결된 자산 없음", verdict="UNKNOWN",
                reason="어느 자산에도 연결되지 않은 SG", evidence=f"sg_id: {sg_id}"))

    return findings


def overall_verdict(findings, errors):
    """전체 판정: ERROR > UNKNOWN > FAIL > PASS. 결과가 없으면 UNKNOWN."""
    if errors:
        return "ERROR"
    if not findings:
        return "UNKNOWN"
    verdicts = {f["verdict"] for f in findings}
    for v in ("ERROR", "UNKNOWN", "FAIL"):
        if v in verdicts:
            return v
    return "PASS"


# ---------------------------------------------------------------------------
# 4. 결과 저장
# ---------------------------------------------------------------------------
def prepare_output_dir(path):
    """출력 폴더는 새 폴더(또는 빈 폴더)만 허용한다. 기존 결과를 덮어쓰지 않는다."""
    out = Path(path)
    if out.exists() and any(out.iterdir()):
        raise ValueError(f"출력 폴더가 비어 있지 않습니다(덮어쓰기 금지): {out}")
    out.mkdir(parents=True, exist_ok=True)
    return out


def write_results(out, envelope):
    with open(out / "results.json", "w", encoding="utf-8") as f:
        json.dump(envelope, f, ensure_ascii=False, indent=2)
    # utf-8-sig: 엑셀에서 열어도 한글이 깨지지 않게 한다
    with open(out / "findings.csv", "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FINDING_FIELDS)
        writer.writeheader()
        writer.writerows(envelope["findings"])


# ---------------------------------------------------------------------------
# 5. 명령 실행
# ---------------------------------------------------------------------------
def run_fixture(args):
    started = datetime.now(timezone.utc)
    try:
        baseline = load_json(args.baseline)
        fixture = load_json(args.fixture)
        out = prepare_output_dir(args.output_dir)
    except ValueError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        return EXIT_CODE["ERROR"]

    errors = fixture.get("errors", [])
    findings = [] if errors else audit(baseline, fixture)
    verdict = overall_verdict(findings, errors)

    counts = {v: 0 for v in ("PASS", "FAIL", "UNKNOWN", "ERROR")}
    for f in findings:
        counts[f["verdict"]] += 1
    counts["ERROR"] += len(errors)

    envelope = {
        "schema_version": 1,
        "run_id": str(uuid.uuid4()),
        "started_at_utc": started.isoformat(),
        "finished_at_utc": datetime.now(timezone.utc).isoformat(),
        "tool_version": TOOL_VERSION,
        "mode": "fixture",
        "account_id": fixture.get("account_id", ""),
        "region": fixture.get("region", ""),
        "scope": {"vpc_id": fixture.get("vpc_id", ""), "fixture_id": fixture.get("fixture_id", "")},
        "collection_status": "FAILED" if errors else "COMPLETE",
        "overall_verdict": verdict,
        "counts": counts,
        "findings": findings,
        "errors": errors,
    }

    try:
        write_results(out, envelope)
    except OSError as e:
        print(f"[ERROR] 결과 저장 실패: {e}", file=sys.stderr)
        return EXIT_CODE["ERROR"]

    print(f"모드: fixture ({fixture.get('fixture_id', '')})  계정: {envelope['account_id']}  리전: {envelope['region']}")
    print(f"수집 상태: {envelope['collection_status']}  결과: {counts}")
    for f in findings:
        if f["verdict"] != "PASS":
            print(f"  [{f['verdict']}] {f['check_id']} {f['asset_id']} {f['sg_id']}: {f['reason']}")
    for e in errors:
        print(f"  [ERROR] {e.get('stage')}: {e.get('code')} - {e.get('message')}")
    print(f"전체 판정: {verdict} (종료 코드 {EXIT_CODE[verdict]})")
    print(f"저장 위치: {out / 'results.json'}, {out / 'findings.csv'}")
    return EXIT_CODE[verdict]


def main():
    parser = argparse.ArgumentParser(description="SG 설정 점검 CLI (읽기 전용)")
    sub = parser.add_subparsers(dest="mode", required=True)

    p_fix = sub.add_parser("fixture", help="AWS 없이 fixture 파일로 판정")
    p_fix.add_argument("--fixture", required=True, help="fixture JSON 경로")
    p_fix.add_argument("--baseline", required=True, help="baseline JSON 경로")
    p_fix.add_argument("--output-dir", required=True, help="결과를 저장할 새 폴더")

    sub.add_parser("live", help="실제 AWS 읽기 전용 수집 (3회차 예정, 아직 미구현)")

    args = parser.parse_args()
    if args.mode == "live":
        print("[ERROR] live 모드는 아직 구현하지 않았습니다(3회차 예정).", file=sys.stderr)
        return EXIT_CODE["ERROR"]
    return run_fixture(args)


if __name__ == "__main__":
    sys.exit(main())