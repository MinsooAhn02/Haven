"""SG 설정 점검 CLI (읽기 전용) - 이민성

network/설계.md 4장의 SG 연결표(baseline.json)와 실제(또는 fixture) SG 규칙을 비교해
PASS / FAIL / UNKNOWN / ERROR 로 판정한다.

사용법:
    python network_audit.py fixture --fixture <json> --baseline <json> --output-dir <새 폴더>
    python network_audit.py live --region <리전> --profile <프로필> --vpc-id <vpc> --baseline <json> --output-dir <새 폴더>
    python network_audit.py live --region <리전> --profile <프로필> --sg-id <sg> [--sg-id <sg> ...] --baseline <json> --output-dir <새 폴더>

live 모드(3회차)는 실제 AWS를 읽기만 한다(Describe* API). boto3가 필요하다.

종료 코드: 0=PASS, 1=FAIL, 2=ERROR, 3=UNKNOWN (여러 개면 ERROR > UNKNOWN > FAIL > PASS)
"""

import argparse
import csv
import json
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

TOOL_VERSION = "0.3.0"

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
    except OSError as e:
        raise ValueError(f"파일 읽기 실패: {path} ({e})")


def validate_inputs(baseline, fixture):
    """Reject malformed input shapes before indexing nested fields."""
    def require_list(obj, key, label):
        if not isinstance(obj, dict) or not isinstance(obj.get(key), list):
            raise ValueError(f"{label}.{key}는 목록이어야 합니다")
        return obj[key]

    assets = require_list(baseline, "assets", "baseline")
    rules = require_list(baseline, "allowed_rules", "baseline")
    groups = require_list(fixture, "security_groups", "fixture")
    attachments = require_list(fixture, "attachments", "fixture")
    errors = require_list(fixture, "errors", "fixture")
    for item in assets:
        if not isinstance(item, dict) or not isinstance(item.get("asset_id"), str) or not isinstance(item.get("asset_role"), str) or not isinstance(item.get("expected_sg_ids", []), list):
            raise ValueError("baseline.assets 항목 형식이 잘못되었습니다")
    required_rule = ("asset_role", "direction", "protocol", "from_port", "to_port", "source_type", "source_value")
    if any(not isinstance(item, dict) or any(key not in item for key in required_rule) for item in rules):
        raise ValueError("baseline.allowed_rules 항목 형식이 잘못되었습니다")
    if any(not isinstance(item, dict) or not isinstance(item.get("GroupId"), str) for item in groups):
        raise ValueError("fixture.security_groups 항목 형식이 잘못되었습니다")
    if any(not isinstance(item, dict) or not isinstance(item.get("asset_id"), str) or not isinstance(item.get("sg_ids", []), list) for item in attachments):
        raise ValueError("fixture.attachments 항목 형식이 잘못되었습니다")
    if any(not isinstance(item, dict) for item in errors):
        raise ValueError("fixture.errors 항목 형식이 잘못되었습니다")


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


def audit(baseline, fixture, ignore_unattached=(), scope_assets=None):
    """baseline과 fixture를 비교해 findings 목록을 만든다.
    ignore_unattached: '연결 안 된 SG(SG-06)' 판정에서 뺄 SG ID(live의 default SG, SG-07에서 따로 판정).
    scope_assets: 점검 범위에 든 자산 ID(live --sg-id). None이면 baseline 자산 전부가 범위다."""
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

    attached_assets = {att["asset_id"] for att in fixture.get("attachments", [])}
    for asset_id, role in asset_role.items():
        if scope_assets is not None and asset_id not in scope_assets:
            continue
        if asset_id not in attached_assets:
            findings.append(make_finding(
                ctx, check_id="SG-06", asset_id=asset_id, asset_role=role,
                expected="자산 attachment 수집", actual="attachment 결과 없음",
                verdict="UNKNOWN", reason="baseline 자산의 attachment 수집 결과가 없어 상태를 알 수 없음",
                evidence=f"baseline asset: {asset_id}"))

    # (6) 어느 자산에도 연결되지 않은 SG → UNKNOWN (SG-06)
    for sg_id in sgs:
        if sg_id not in attached_sg_ids and sg_id not in ignore_unattached:
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
# 5. live 수집 (실제 AWS, 읽기 전용)
# ---------------------------------------------------------------------------
# 이 코드는 Describe* API만 부른다. AWS 설정을 바꾸는 API는 쓰지 않는다.
RETRY_CODES = {"Throttling", "ThrottlingException", "RequestLimitExceeded", "RequestThrottled",
               "ServiceUnavailable", "InternalError"}
MAX_ATTEMPTS = 3
DEFAULT_SG_NAME = "default"


class CollectError(Exception):
    """수집 단계 하나가 실패함. stage·code만 남기고 AWS 오류 원문은 남기지 않는다(ARN·계정 번호가 들어 있음)."""

    def __init__(self, stage, code, message):
        super().__init__(message)
        self.stage, self.code, self.message = stage, code, message

    def as_dict(self):
        return {"stage": self.stage, "code": self.code, "message": self.message}


def error_code(exc):
    """botocore ClientError면 AWS 오류 코드, 아니면 예외 이름(예: NoCredentialsError)."""
    response = getattr(exc, "response", None)
    if isinstance(response, dict):
        code = response.get("Error", {}).get("Code")
        if code:
            return str(code)[:64]
    return type(exc).__name__


def call_paged(client, stage, method, result_key, sleep=time.sleep, **kwargs):
    """Describe* API를 마지막 페이지까지 부른다. 요청 제한이면 MAX_ATTEMPTS번까지 다시 시도한다."""
    items, token = [], None
    while True:
        params = dict(kwargs)
        if token:
            params["NextToken"] = token
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                page = getattr(client, method)(**params)
                break
            except Exception as exc:  # 어떤 오류든 PASS로 넘기지 않고 ERROR로 남긴다
                code = error_code(exc)
                if code in RETRY_CODES and attempt < MAX_ATTEMPTS:
                    sleep(2 ** attempt)
                    continue
                tried = f" ({attempt}번 시도)" if code in RETRY_CODES else ""
                raise CollectError(stage, code, f"{stage} 호출 실패{tried}")
        items.extend(page.get(result_key, []))
        token = page.get("NextToken")
        if not token:
            return items


def mask_account(account_id):
    """계정 번호는 앞 4자리만 남긴다."""
    account_id = str(account_id or "")
    return account_id[:4] + "*" * (len(account_id) - 4) if len(account_id) > 4 else account_id


def collect_live(ec2, baseline, account_id, vpc_id=None, sg_ids=None, sleep=time.sleep):
    """실제 AWS를 읽어 fixture와 같은 모양(dict)으로 돌려준다(명세 5.1).
    - 범위: --vpc-id(그 VPC의 SG·ENI 전부) 또는 --sg-id(그 SG들과, 같은 ENI에 붙은 추가 SG).
    - 자산 매핑: baseline의 expected_sg_ids가 붙은 ENI를 그 자산의 연결로 본다. 이름·태그로 추정하지 않는다.
    돌려주는 값: (data, default_sg_ids, scope_assets, extra_findings, skip_unattached).
    skip_unattached는 extra_findings에서 이미 UNKNOWN으로 남긴 SG(중복 판정 방지). 실패한 단계는 data["errors"]에 남긴다."""
    data = {"account_id": account_id, "region": "", "vpc_id": vpc_id or "", "fixture_id": "live",
            "security_groups": [], "attachments": [], "errors": []}
    extra = []
    skip_unattached = set()
    assets = baseline.get("assets", [])
    sg_owner = {}                      # 기대 SG ID → 자산 ID
    for a in assets:
        for sg_id in a.get("expected_sg_ids", []):
            sg_owner.setdefault(sg_id, set()).add(a["asset_id"])

    def fail(e):
        data["errors"].append(e.as_dict())

    # 1) 범위 확인
    if vpc_id:
        try:
            vpcs = call_paged(ec2, "DescribeVpcs", "describe_vpcs", "Vpcs", sleep=sleep, VpcIds=[vpc_id])
        except CollectError as e:
            fail(e)
            return data, [], None, extra, skip_unattached
        if len(vpcs) != 1:
            fail(CollectError("DescribeVpcs", "VpcNotFound", "지정한 VPC를 찾지 못함"))
            return data, [], None, extra, skip_unattached
        if account_id and vpcs[0].get("OwnerId") not in (None, account_id):
            fail(CollectError("DescribeVpcs", "VpcOwnerMismatch", "지정한 VPC가 로그인한 계정의 것이 아님"))
            return data, [], None, extra, skip_unattached
        scope_filter = [{"Name": "vpc-id", "Values": [vpc_id]}]
    else:
        scope_filter = None

    # 2) ENI(연결 정보): VPC 전부, 또는 지정 SG가 붙은 ENI
    try:
        if vpc_id:
            enis = call_paged(ec2, "DescribeNetworkInterfaces", "describe_network_interfaces",
                              "NetworkInterfaces", sleep=sleep, Filters=scope_filter)
        else:
            enis = call_paged(ec2, "DescribeNetworkInterfaces", "describe_network_interfaces",
                              "NetworkInterfaces", sleep=sleep,
                              Filters=[{"Name": "group-id", "Values": list(sg_ids)}])
        eni_ok = True
    except CollectError as e:
        fail(e)
        enis, eni_ok = [], False

    # 3) SG 규칙: VPC 전부, 또는 지정 SG + 같은 ENI에 붙은 추가 SG
    try:
        if vpc_id:
            groups = call_paged(ec2, "DescribeSecurityGroups", "describe_security_groups",
                                "SecurityGroups", sleep=sleep, Filters=scope_filter)
        else:
            wanted = set(sg_ids) | {g["GroupId"] for e in enis for g in e.get("Groups", [])}
            groups = call_paged(ec2, "DescribeSecurityGroups", "describe_security_groups",
                                "SecurityGroups", sleep=sleep, GroupIds=sorted(wanted))
    except CollectError as e:
        fail(e)
        groups = []
    data["security_groups"] = groups
    if not data["vpc_id"]:
        data["vpc_id"] = ";".join(sorted({g.get("VpcId", "") for g in groups if g.get("VpcId")}))
    collected = {g["GroupId"] for g in groups}
    # default SG는 AWS가 정한 이름(역할 추정이 아님). SG-07은 VPC 범위에서만 판정한다.
    default_sg_ids = [g["GroupId"] for g in groups if g.get("GroupName") == DEFAULT_SG_NAME] if vpc_id else []

    # 점검 범위에 드는 자산: VPC 범위면 전부, SG 범위면 지정 SG를 기대 SG로 가진 자산
    if vpc_id:
        scope_assets = None
    else:
        scope_assets = set().union(*[sg_owner.get(s, set()) for s in sg_ids]) if sg_ids else set()

    # 4) 자산 ↔ ENI: 기대 SG가 붙은 ENI의 SG를 모두 합쳐 그 자산의 연결로 본다(합집합 검사)
    attached = {}
    unmapped = []
    for eni in enis:
        eni_sgs = [g["GroupId"] for g in eni.get("Groups", [])]
        owners = set().union(*[sg_owner.get(s, set()) for s in eni_sgs]) if eni_sgs else set()
        if len(owners) > 1:
            extra.append(make_finding(
                {"region": "", "vpc_id": data["vpc_id"]}, check_id="SG-06", sg_id=";".join(eni_sgs),
                asset_id=";".join(sorted(owners)), expected="자산 하나의 기대 SG만 붙은 ENI",
                actual="서로 다른 자산의 기대 SG가 한 ENI에 붙음", verdict="UNKNOWN",
                reason="역할 미확정: 한 ENI가 여러 자산의 SG를 가짐",
                evidence=f"eni: {eni.get('NetworkInterfaceId', '')}"))
            skip_unattached.update(eni_sgs)
            continue
        if not owners:
            # baseline 어느 자산의 기대 SG도 없는 ENI(VPC 엔드포인트 등): 역할을 추정하지 않고 UNKNOWN
            if eni_sgs and (vpc_id or set(eni_sgs) & set(sg_ids or [])):
                unmapped.append({"asset_id": f"eni:{eni.get('NetworkInterfaceId', '')}",
                                 "sg_ids": sorted(eni_sgs)})
            continue
        for owner in owners:
            attached.setdefault(owner, set()).update(eni_sgs)

    if eni_ok:
        for asset_id, sgs in sorted(attached.items()):
            data["attachments"].append({"asset_id": asset_id, "sg_ids": sorted(sgs)})
        data["attachments"].extend(unmapped)   # audit()이 'baseline에 없는 자산' UNKNOWN으로 판정
    else:
        # 연결 정보가 없으면 SG 규칙만 판정하고, 자산 접근 결과는 UNKNOWN으로 둔다(명세 5.1)
        for a in assets:
            if scope_assets is not None and a["asset_id"] not in scope_assets:
                continue
            exp = [s for s in a.get("expected_sg_ids", []) if s in collected]
            if exp:
                data["attachments"].append({"asset_id": a["asset_id"], "sg_ids": exp})
            extra.append(make_finding(
                {"region": "", "vpc_id": data["vpc_id"]}, check_id="SG-06", asset_id=a["asset_id"],
                asset_role=a["asset_role"], expected="ENI 연결 정보 수집", actual="수집 실패",
                verdict="UNKNOWN", reason="연결 정보가 없어 SG 규칙만 판정함(자산 접근 결과는 알 수 없음)",
                evidence=f"baseline asset: {a['asset_id']}"))

    return data, default_sg_ids, scope_assets, extra, skip_unattached


def check_default_sg(data, default_sg_ids):
    """SG-07: VPC의 default SG는 규칙이 하나도 없어야 한다(실수로 붙어도 통신이 안 되게)."""
    findings = []
    ctx = {"region": data.get("region", ""), "vpc_id": data.get("vpc_id", "")}
    groups = {sg["GroupId"]: sg for sg in data.get("security_groups", [])}
    for sg_id in default_sg_ids:
        rules = flatten_rules(groups[sg_id])
        if rules:
            for rule in rules:
                findings.append(make_finding(
                    ctx, check_id="SG-07", sg_id=sg_id, asset_id="(default SG)",
                    **{k: rule[k] for k in ("direction", "protocol", "from_port", "to_port",
                                            "source_type", "source_value")},
                    expected="default SG에 규칙 없음", actual=describe(rule), verdict="FAIL",
                    reason="default SG에 규칙이 있음(실수로 붙으면 통신이 열림)",
                    evidence=f"{sg_id}: {describe(rule)}"))
        else:
            findings.append(make_finding(
                ctx, check_id="SG-07", sg_id=sg_id, asset_id="(default SG)",
                expected="default SG에 규칙 없음", actual="규칙 없음", verdict="PASS",
                reason="default SG가 비어 있음", evidence=f"sg_id: {sg_id}"))
    return findings


# ---------------------------------------------------------------------------
# 6. 명령 실행
# ---------------------------------------------------------------------------
def finish(mode, data, findings, out, started, scope):
    """판정 개수·전체 판정을 정리해 저장하고 화면에 요약을 찍는다. 종료 코드를 돌려준다."""
    errors = data.get("errors", [])
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
        "mode": mode,
        "account_id": data.get("account_id", ""),
        "region": data.get("region", ""),
        "scope": scope,
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

    print(f"모드: {mode} ({scope.get('fixture_id') or scope.get('vpc_id', '')})  계정: {envelope['account_id']}  리전: {envelope['region']}")
    print(f"수집 상태: {envelope['collection_status']}  결과: {counts}")
    for f in findings:
        if f["verdict"] != "PASS":
            print(f"  [{f['verdict']}] {f['check_id']} {f['asset_id']} {f['sg_id']}: {f['reason']}")
    for e in errors:
        print(f"  [ERROR] {e.get('stage')}: {e.get('code')} - {e.get('message')}")
    print(f"전체 판정: {verdict} (종료 코드 {EXIT_CODE[verdict]})")
    print(f"저장 위치: {out / 'results.json'}, {out / 'findings.csv'}")
    return EXIT_CODE[verdict]


def run_fixture(args):
    started = datetime.now(timezone.utc)
    try:
        baseline = load_json(args.baseline)
        fixture = load_json(args.fixture)
        validate_inputs(baseline, fixture)
        out = prepare_output_dir(args.output_dir)
    except (ValueError, OSError) as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        return EXIT_CODE["ERROR"]

    findings = audit(baseline, fixture)
    scope = {"vpc_id": fixture.get("vpc_id", ""), "fixture_id": fixture.get("fixture_id", "")}
    return finish("fixture", fixture, findings, out, started, scope)


def make_clients(profile, region):
    """boto3 클라이언트(EC2·STS). 재시도는 call_paged가 직접 하므로 boto3 자동 재시도는 끈다."""
    import boto3
    from botocore.config import Config
    config = Config(retries={"total_max_attempts": 1}, connect_timeout=5, read_timeout=15)
    session = boto3.Session(profile_name=profile, region_name=region)
    return session.client("ec2", config=config), session.client("sts", config=config)


def run_live(args, client_factory=make_clients, sleep=time.sleep):
    started = datetime.now(timezone.utc)
    # AWS를 읽기 전에 입력·출력 폴더부터 확인한다
    try:
        baseline = load_json(args.baseline)
        validate_inputs(baseline, {"security_groups": [], "attachments": [], "errors": []})
        if any(not a.get("expected_sg_ids") or any(not str(s).startswith("sg-") or "fixture" in str(s)
                                                    for s in a.get("expected_sg_ids", []))
               for a in baseline["assets"]):
            raise ValueError("live에는 실제 SG ID가 든 baseline이 필요합니다(예: baseline.live.json). "
                             "자산마다 expected_sg_ids를 실제 sg-... 로 채우세요")
        out = prepare_output_dir(args.output_dir)
    except (ValueError, OSError) as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        return EXIT_CODE["ERROR"]

    scope = {"vpc_id": args.vpc_id or "", "sg_ids": list(args.sg_id or []), "profile": args.profile}
    data = {"errors": []}
    default_sg_ids, scope_assets, extra, skip = [], None, [], set()
    try:
        ec2, sts = client_factory(args.profile, args.region)
    except ImportError:
        data["errors"].append({"stage": "setup", "code": "Boto3NotInstalled",
                               "message": "live 모드는 boto3가 필요함(pip install --user \"boto3[crt]\")"})
        ec2 = sts = None
    except Exception as e:
        data["errors"].append({"stage": "setup", "code": error_code(e), "message": "AWS 클라이언트 생성 실패"})
        ec2 = sts = None

    if ec2 is not None:
        account_id = ""
        try:
            account_id = str(sts.get_caller_identity()["Account"])
        except Exception as e:
            data["errors"].append({"stage": "GetCallerIdentity", "code": error_code(e),
                                   "message": "로그인한 계정을 확인하지 못함"})
        if account_id:
            target = f"VPC {args.vpc_id}" if args.vpc_id else f"SG {', '.join(args.sg_id)}"
            print(f"대상 계정: {mask_account(account_id)}  리전: {args.region}  범위: {target}")
            try:
                data, default_sg_ids, scope_assets, extra, skip = collect_live(
                    ec2, baseline, account_id, vpc_id=args.vpc_id, sg_ids=args.sg_id, sleep=sleep)
            except Exception as e:  # 예상 못 한 응답 모양도 Traceback 대신 ERROR로
                data = {"errors": [{"stage": "collect", "code": error_code(e),
                                    "message": "수집 중 예상하지 못한 오류"}]}

    data.setdefault("security_groups", [])
    data.setdefault("attachments", [])
    data["region"] = args.region
    data["account_id"] = mask_account(data.get("account_id", ""))
    for f in extra:
        f["region"] = args.region

    findings = extra + audit(baseline, data, ignore_unattached=set(default_sg_ids) | skip, scope_assets=scope_assets)
    findings += check_default_sg(data, default_sg_ids)
    return finish("live", data, findings, out, started, scope)


def main(argv=None):
    parser = argparse.ArgumentParser(description="SG 설정 점검 CLI (읽기 전용)")
    sub = parser.add_subparsers(dest="mode", required=True)

    p_fix = sub.add_parser("fixture", help="AWS 없이 fixture 파일로 판정")
    p_fix.add_argument("--fixture", required=True, help="fixture JSON 경로")
    p_fix.add_argument("--baseline", required=True, help="baseline JSON 경로")
    p_fix.add_argument("--output-dir", required=True, help="결과를 저장할 새 폴더")

    p_live = sub.add_parser("live", help="실제 AWS를 읽기만 해서 판정(boto3 필요, 명세 5.1)")
    p_live.add_argument("--region", required=True, help="AWS 리전 (예: ap-northeast-2)")
    p_live.add_argument("--profile", required=True, help="AWS CLI 프로필 이름 (기본 프로필이면 default)")
    p_live.add_argument("--baseline", required=True, help="실제 SG ID가 든 baseline JSON (예: baseline.live.json)")
    p_live.add_argument("--output-dir", required=True, help="결과를 저장할 새 폴더")
    target = p_live.add_mutually_exclusive_group(required=True)
    target.add_argument("--vpc-id", help="점검할 VPC (그 VPC의 SG·ENI 전부)")
    target.add_argument("--sg-id", action="append", help="점검할 SG (여러 번 줄 수 있음)")

    args = parser.parse_args(argv)
    if args.mode == "live":
        return run_live(args)
    return run_fixture(args)


if __name__ == "__main__":
    sys.exit(main())
