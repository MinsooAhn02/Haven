"""SG 점검 결과(output-dir)로 공개용 증거 묶음 evidence/<run-id>/ 을 만든다 (구현명세 9장).

    python make_evidence.py --results-dir <network_audit.py의 output-dir> --baseline <json>
                            [--evidence-root evidence] [--before <이전 output-dir>] [--omission "알려진 누락"]

만드는 파일 (evidence/<run-id>/):
    manifest.json      commit, 환경, 도구/규칙 버전, 대상 범위, 실행 시각, 알려진 누락
    masking.json       가림 설정(무엇을 어떻게 가렸는지)
    results.json       가린 시험 결과
    findings.csv       가린 시험 결과(CSV)
    masking_log.json   가림 로그(종류별 개수, 원래 값은 남기지 않음)
    comparison.md      전후 비교(--before가 없으면 '비교 대상 없음')
원래 값 ↔ 가림 값 대응표(masking_map.json)는 공개 묶음이 아니라 results-dir(raw 위치, 깃에 안 올림)에 둔다.
종료 코드: 0 성공, 2 입력/파일 오류. 읽기 전용 — AWS를 호출하지 않는다.
"""
import argparse
import csv
import hashlib
import json
import platform
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import network_audit as na  # noqa: E402

MASK_VERSION = 1
OPEN_CIDRS = {"0.0.0.0/0", "::/0"}       # 공개 범위 자체는 판정 근거라 가리지 않는다

# (종류, 정규식). 순서대로 적용한다. ARN을 먼저 가려야 안의 계정 번호가 따로 남지 않는다.
# 경계는 \b 대신 영숫자로 직접 정한다(\b는 한글을 글자로 봐서 'eni-...는'을 놓침).
PATTERNS = [
    ("arn", re.compile(r"arn:aws[a-z-]*:[^\s\"',;]+")),
    ("aws_id", re.compile(r"(?<![0-9A-Za-z_-])(?:sg|vpc|eni|i|pl|subnet|igw|nat|rtb|acl|vpce)-[0-9a-f]{8,17}(?![0-9A-Za-z])")),
    ("ipv4", re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?:/\d{1,2})?(?![\d.])")),
    ("ipv6", re.compile(r"(?<![0-9A-Za-z:])(?:[0-9a-fA-F]{1,4}:){1,7}:?(?:[0-9a-fA-F]{1,4})?(?:/\d{1,3})?(?![0-9A-Za-z:])")),
    ("account", re.compile(r"(?<![0-9A-Za-z-])\d{12}(?![0-9A-Za-z-])")),
]


class EvidenceError(Exception):
    pass


def skip(kind, value):
    """가리지 않을 값: 공개 범위, 이미 가린 값, IP처럼 보이는 시각(17:06:30)."""
    if value in OPEN_CIDRS or "#" in value:
        return True
    if kind == "ipv6":
        return "/" not in value and "::" not in value and value.count(":") < 7
    return False


def token(kind, value):
    """같은 값은 언제나 같은 가림 값이 된다(전후 비교용). 원래 값은 되돌릴 수 없다."""
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]
    if kind == "aws_id":
        return value.split("-", 1)[0] + "-#" + digest
    return f"{kind}-#{digest}"


class Masker:
    def __init__(self):
        self.counts = {kind: 0 for kind, _ in PATTERNS}
        self.mapping = {}

    def text(self, value):
        for kind, pattern in PATTERNS:
            def repl(m, kind=kind):
                original = m.group(0)
                if skip(kind, original):
                    return original
                masked = token(kind, original)
                self.counts[kind] += 1
                self.mapping[original] = masked
                return masked
            value = pattern.sub(repl, value)
        return value

    def walk(self, obj):
        if isinstance(obj, dict):
            return {k: self.walk(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self.walk(v) for v in obj]
        if isinstance(obj, str):
            return self.text(obj)
        return obj


def leaks(blob):
    """가린 뒤에도 남은 원래 값 후보. 하나라도 있으면 묶음을 만들지 않는다."""
    found = []
    for kind, pattern in PATTERNS:
        for m in pattern.finditer(blob):
            if not skip(kind, m.group(0)):
                found.append(kind)
    return found


def git_commit(cwd):
    """(commit, dirty). git이 없거나 저장소가 아니면 (None, None)."""
    # Windows 기본 인코딩(cp949)으로 풀면 한글 경로에서 깨져 stdout이 None이 된다 → UTF-8로 고정
    opts = dict(cwd=cwd, capture_output=True, encoding="utf-8", errors="replace", timeout=10, check=True)
    try:
        commit = (subprocess.run(["git", "rev-parse", "HEAD"], **opts).stdout or "").strip()
        status = subprocess.run(["git", "status", "--porcelain", "--", "."], **opts).stdout
    except (OSError, subprocess.SubprocessError, ValueError):
        return None, None
    if not re.fullmatch(r"[0-9a-f]{40}", commit) or status is None:
        return None, None
    return commit, bool(status.strip())


def boto3_version():
    try:
        import boto3
        return boto3.__version__
    except ImportError:
        return "미설치"


def finding_key(f):
    return tuple(str(f.get(k, "")) for k in ("check_id", "asset_id", "sg_id", "direction", "protocol",
                                              "from_port", "to_port", "source_type", "source_value"))


def compare(before, after):
    """가린 결과 두 개를 비교한 마크다운."""
    lines = ["# 전후 비교", "",
             f"- 전: run_id `{before.get('run_id', '')}` · {before.get('started_at_utc', '')} · "
             f"전체 {before.get('overall_verdict', '')} · {before.get('counts', {})}",
             f"- 후: run_id `{after.get('run_id', '')}` · {after.get('started_at_utc', '')} · "
             f"전체 {after.get('overall_verdict', '')} · {after.get('counts', {})}", ""]
    if before.get("scope") != after.get("scope") or before.get("mode") != after.get("mode"):
        lines += ["> 주의: 두 실행의 모드나 범위가 달라 결과를 그대로 비교할 수 없음", ""]
    b = {finding_key(f): f["verdict"] for f in before.get("findings", [])}
    a = {finding_key(f): f["verdict"] for f in after.get("findings", [])}
    rows = []
    for key in sorted(set(b) | set(a)):
        if b.get(key) != a.get(key):
            rows.append(f"| {key[0]} | {key[1]} | {key[2]} | {key[3]} {key[4]} {key[5]}-{key[6]} {key[8]} "
                        f"| {b.get(key, '(없음)')} | {a.get(key, '(없음)')} |")
    be = sorted({e.get("code", "") for e in before.get("errors", [])})
    ae = sorted({e.get("code", "") for e in after.get("errors", [])})
    if rows:
        lines += ["| 규칙 | 자산 | SG | 내용 | 전 | 후 |", "|---|---|---|---|---|---|"] + rows
    else:
        lines.append("판정이 바뀐 항목 없음")
    if be != ae:
        lines += ["", f"- 수집 오류: 전 {be or '없음'} → 후 {ae or '없음'}"]
    return "\n".join(lines) + "\n"


def default_omissions(results):
    out = ["SG 허용 설정만 본 결과이며 실제 인터넷 도달(공인 IP/route/NACL/listener)은 별도 시험으로 확인함(명세 5.2)"]
    scope = results.get("scope", {})
    if results.get("mode") == "live" and scope.get("sg_ids"):
        out.append("--sg-id 범위: VPC 전체가 아니며 default SG(SG-07) 판정을 하지 않음")
    if results.get("mode") == "fixture":
        out.append("fixture 결과: 실제 AWS를 읽지 않음")
    if results.get("errors"):
        out.append("수집 오류 있음: " + ", ".join(sorted({f"{e.get('stage')}:{e.get('code')}" for e in results['errors']})))
    unknown = results.get("counts", {}).get("UNKNOWN", 0)
    if unknown:
        out.append(f"UNKNOWN {unknown}건: 판정 근거 부족(findings 참고)")
    return out


def load_results(results_dir):
    path = Path(results_dir) / "results.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise EvidenceError(f"결과를 읽지 못함: {path} ({type(e).__name__})")
    for key in ("run_id", "mode", "findings", "counts", "tool_version"):
        if key not in data:
            raise EvidenceError(f"{path}에 {key}가 없음(network_audit.py 결과가 아님)")
    if not re.fullmatch(r"[0-9a-f-]{8,64}", str(data["run_id"])):
        raise EvidenceError("run_id 모양이 이상함(폴더 이름으로 쓸 수 없음)")
    return data


def make_evidence(results_dir, baseline, evidence_root, before_dir=None, omissions=(), repo_dir=HERE):
    results = load_results(results_dir)
    before = load_results(before_dir) if before_dir else None
    try:
        rule_hash = hashlib.sha256(Path(baseline).read_bytes()).hexdigest()
    except OSError as e:
        raise EvidenceError(f"baseline을 읽지 못함 ({type(e).__name__})")

    target = Path(evidence_root) / results["run_id"]
    if target.exists():
        raise EvidenceError(f"이미 있는 증거 폴더는 덮어쓰지 않음: {target}")

    masker = Masker()
    masked = masker.walk(results)
    masked_before = Masker().walk(before) if before else None

    commit, dirty = git_commit(repo_dir)
    known = default_omissions(results) + [masker.text(o) for o in omissions]
    if commit is None:
        known.append("commit을 확인하지 못함(git 없음)")
    elif dirty:
        known.append("실행 시 sg_audit 폴더에 커밋 안 된 변경이 있었음")

    manifest = {
        "evidence_version": 1,
        "run_id": results["run_id"],
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "commit": commit or "unknown",
        "commit_dirty": dirty,
        "environment": {"python": platform.python_version(), "os": f"{platform.system()} {platform.release()}",
                        "boto3": boto3_version()},
        "tool_version": results["tool_version"],
        "rule_version": {"baseline_sha256": rule_hash, "baseline_file": Path(baseline).name},
        "mode": results["mode"],
        "account_id": masked.get("account_id", ""),
        "region": masked.get("region", ""),
        "scope": masked.get("scope", {}),
        "run_started_at_utc": results.get("started_at_utc", ""),
        "run_finished_at_utc": results.get("finished_at_utc", ""),
        "overall_verdict": results.get("overall_verdict", ""),
        "counts": results.get("counts", {}),
        "known_omissions": known,
        "before_run_id": before["run_id"] if before else None,
    }
    masking = {
        "mask_version": MASK_VERSION,
        "rules": {
            "account": "12자리 계정 번호 → account-#<sha256 앞 8자> (network_audit.py는 앞 4자리만 남겨 이미 가림)",
            "arn": "ARN 전체 → arn-#<해시>",
            "aws_id": "sg-/vpc-/eni-/i-/pl-/subnet- 등 실제 ID → <접두어>-#<해시>",
            "ipv4": "IPv4 주소·CIDR → ipv4-#<해시> (0.0.0.0/0은 판정 근거라 그대로)",
            "ipv6": "IPv6 주소·CIDR → ipv6-#<해시> (::/0은 그대로)",
        },
        "same_value_same_token": True,
        "map_location": "results-dir/masking_map.json (raw 위치, 공개 묶음에 넣지 않음)",
    }
    log = {"run_id": results["run_id"], "replaced": masker.counts, "total": sum(masker.counts.values())}
    comparison = compare(masked_before, masked) if before else "# 전후 비교\n\n비교 대상 없음(--before 미지정)\n"

    files = {
        "manifest.json": json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        "masking.json": json.dumps(masking, ensure_ascii=False, indent=2) + "\n",
        "results.json": json.dumps(masked, ensure_ascii=False, indent=2) + "\n",
        "masking_log.json": json.dumps(log, ensure_ascii=False, indent=2) + "\n",
        "comparison.md": comparison,
    }
    found = leaks("".join(v for k, v in files.items() if k != "masking.json"))
    if found:
        raise EvidenceError(f"가림 뒤에도 원래 값 후보가 남음({sorted(set(found))}) — 묶음을 만들지 않음")

    target.mkdir(parents=True)
    for name, content in files.items():
        (target / name).write_text(content, encoding="utf-8")
    with (target / "findings.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=na.FINDING_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(masked["findings"])
    map_path = Path(results_dir) / "masking_map.json"
    if not map_path.exists():
        map_path.write_text(json.dumps(masker.mapping, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


def main(argv=None):
    p = argparse.ArgumentParser(description="SG 점검 결과로 공개용 증거 묶음을 만든다(명세 9장)")
    p.add_argument("--results-dir", required=True, help="network_audit.py의 output-dir")
    p.add_argument("--baseline", required=True, help="그 실행에 쓴 baseline JSON(규칙 버전 해시용)")
    p.add_argument("--evidence-root", default=str(HERE / "evidence"), help="증거 묶음 상위 폴더")
    p.add_argument("--before", help="비교할 이전 실행의 output-dir")
    p.add_argument("--omission", action="append", default=[], help="알려진 누락(여러 번 가능)")
    args = p.parse_args(argv)
    try:
        target = make_evidence(args.results_dir, args.baseline, args.evidence_root, args.before, args.omission)
    except EvidenceError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        return 2
    except OSError as e:
        print(f"[ERROR] 증거 묶음 저장 실패: {type(e).__name__}", file=sys.stderr)
        return 2
    print(f"증거 묶음: {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
