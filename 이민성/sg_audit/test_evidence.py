"""증거 묶음(make_evidence.py, 명세 9장) 시험. AWS 없이 결과 파일만으로 돈다.

실행(저장소 루트):
    python -B -m unittest discover -s 이민성/sg_audit -p "test_*.py" -v
"""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import make_evidence as me  # noqa: E402

SG_WEB = "sg-0123456789abcdef0"
VPC = "vpc-0aaaabbbbccccdddd"
ENI = "eni-0fedcba9876543210"
ACCOUNT = "123456789012"
RUN_ID = "5c1e0a43-1111-4222-8333-444455556666"


def results(run_id=RUN_ID, verdict="FAIL", extra=None, errors=None, scope=None):
    findings = [
        {"check_id": "SG-05", "region": "ap-northeast-2", "vpc_id": VPC, "sg_id": SG_WEB, "asset_id": "web-1",
         "asset_role": "web", "direction": "egress", "protocol": "tcp", "from_port": 443, "to_port": 443,
         "source_type": "cidr", "source_value": "0.0.0.0/0", "expected": "", "actual": "", "verdict": "PASS",
         "reason": "baseline 허용 규칙과 일치", "evidence": f"{SG_WEB}: egress tcp 443 0.0.0.0/0"},
        {"check_id": "SG-07", "region": "ap-northeast-2", "vpc_id": VPC, "sg_id": "sg-0bbbbccccdddd0000",
         "asset_id": "(default SG)", "asset_role": "", "direction": "ingress", "protocol": "-1",
         "from_port": None, "to_port": None, "source_type": "sg", "source_value": "sg-0bbbbccccdddd0000",
         "expected": "규칙 없음", "actual": "", "verdict": verdict, "reason": "default SG에 규칙이 있음",
         "evidence": f"eni: {ENI} 10.0.1.25 2001:db8::1/128 arn:aws:iam::{ACCOUNT}:user/minsung"},
    ] + (extra or [])
    counts = {"PASS": 1, "FAIL": 1 if verdict == "FAIL" else 0, "UNKNOWN": 0, "ERROR": len(errors or [])}
    if verdict == "PASS":
        counts["PASS"] = 2
    return {"schema_version": 1, "run_id": run_id, "started_at_utc": "2026-11-13T06:45:00.123456+00:00",
            "finished_at_utc": "2026-11-13T06:45:03.000000+00:00", "tool_version": "0.3.0", "mode": "live",
            "account_id": "7771********", "region": "ap-northeast-2",
            "scope": scope or {"vpc_id": VPC, "sg_ids": [], "profile": "default"},
            "collection_status": "FAILED" if errors else "COMPLETE", "overall_verdict": verdict,
            "counts": counts, "findings": findings, "errors": errors or []}


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.baseline = self.root / "baseline.live.json"
        self.baseline.write_text('{"schema_version": 1}', encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def write_run(self, name, data):
        d = self.root / name
        d.mkdir()
        (d / "results.json").write_text(json.dumps(data), encoding="utf-8")
        return d

    def build(self, run_dir, **kw):
        return me.make_evidence(run_dir, self.baseline, self.root / "evidence", **kw)

    def all_text(self, target):
        return "".join(p.read_text(encoding="utf-8-sig") for p in target.iterdir())

    # E1 필수 파일 6개와 manifest 필드
    def test_E1_bundle_files_and_manifest(self):
        target = self.build(self.write_run("out", results()))
        self.assertEqual(target.name, RUN_ID)
        self.assertEqual(sorted(p.name for p in target.iterdir()),
                         ["comparison.md", "findings.csv", "manifest.json", "masking.json",
                          "masking_log.json", "results.json"])
        m = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
        for key in ("commit", "environment", "tool_version", "rule_version", "scope",
                    "run_started_at_utc", "known_omissions"):
            self.assertIn(key, m)
        self.assertEqual(len(m["rule_version"]["baseline_sha256"]), 64)
        self.assertTrue(any("NACL" in o for o in m["known_omissions"]))

    # E2 실제 ID·IP·ARN·계정 번호가 공개 묶음에 남지 않음, 공개 범위(0.0.0.0/0)와 시각은 그대로
    def test_E2_masks_ids_ips_arn_account(self):
        target = self.build(self.write_run("out", results()))
        text = self.all_text(target)
        for raw in (SG_WEB, VPC, ENI, "10.0.1.25", "2001:db8::1", ACCOUNT, "arn:aws:iam", "7771"):
            self.assertNotIn(raw, text, raw)
        saved = json.loads((target / "results.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["findings"][0]["source_value"], "0.0.0.0/0")
        self.assertEqual(saved["account_id"], "account-masked")
        m = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(m["account_id"], "account-masked")
        self.assertIn("2026-11-13T06:45:00.123456+00:00", text)
        self.assertIn(RUN_ID, text)

    # E2-c 비교표 '내용' 칸: 일반 규칙·범위 포트·default SG PASS 줄
    def test_E2c_rule_text(self):
        self.assertEqual(me.rule_text(("SG-05", "web-1", "sg-#1", "egress", "tcp", "443", "443", "cidr", "0.0.0.0/0")),
                         "egress tcp 443 0.0.0.0/0")
        self.assertEqual(me.rule_text(("SG-01", "db-1", "sg-#1", "ingress", "tcp", "0", "65535", "cidr", "0.0.0.0/0")),
                         "ingress tcp 0-65535 0.0.0.0/0")
        self.assertEqual(me.rule_text(("SG-07", "(default SG)", "sg-#1", "", "", "", "", "", "")),
                         "(default SG 비어 있음)")

    # E2-d 4자리만 남긴 계정 번호가 가림 없이 남으면 안전장치가 잡음
    def test_E2d_partial_account_is_leak(self):
        self.assertEqual(me.leaks('"account_id": "7771********"'), ["account"])
        self.assertEqual(me.leaks('"account_id": "account-masked"'), [])

    # E2-b 시각(17:06:30)·날짜는 IP로 보고 가리지 않음
    def test_E2b_times_are_not_masked(self):
        m = me.Masker()
        self.assertEqual(m.text("백업 20261113T080630Z 17:06:30 배포"), "백업 20261113T080630Z 17:06:30 배포")
        self.assertEqual(m.counts["ipv6"], 0)
        self.assertNotEqual(m.text("fe80::1"), "fe80::1")

    # E3 같은 값은 같은 가림 값(전후 비교가 되도록), 원래 값 대응표는 raw 위치에만
    def test_E3_stable_tokens_and_map_outside_bundle(self):
        run = self.write_run("out", results())
        target = self.build(run)
        saved = json.loads((target / "results.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["findings"][0]["sg_id"], me.token("aws_id", SG_WEB))
        self.assertTrue(saved["findings"][0]["evidence"].startswith(me.token("aws_id", SG_WEB)))
        mapping = json.loads((run / "masking_map.json").read_text(encoding="utf-8"))
        self.assertEqual(mapping[SG_WEB], me.token("aws_id", SG_WEB))
        self.assertFalse((target / "masking_map.json").exists())

    # E4 가림 로그는 개수만, 원래 값 없음
    def test_E4_masking_log_has_counts_only(self):
        target = self.build(self.write_run("out", results()))
        log = json.loads((target / "masking_log.json").read_text(encoding="utf-8"))
        self.assertGreater(log["total"], 0)
        self.assertGreaterEqual(log["replaced"]["aws_id"], 3)
        self.assertEqual(log["replaced"]["arn"], 1)

    # E5 전후 비교: FAIL → PASS 로 바뀐 항목이 나옴
    def test_E5_comparison_shows_changed_verdict(self):
        before = self.write_run("before", results(run_id="aaaaaaaa-0000-4000-8000-000000000001"))
        after = self.write_run("after", results(verdict="PASS"))
        target = self.build(after, before_dir=before)
        text = (target / "comparison.md").read_text(encoding="utf-8")
        self.assertIn("| SG-07 |", text)
        self.assertIn("| FAIL | PASS |", text)
        self.assertIn("ingress 전체 프로토콜 전체", text)        # 포트 없는 규칙은 None-None이 아니라 '전체'
        self.assertNotIn("None", text)
        self.assertNotIn("sg-0bbbbccccdddd0000", text)
        m = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(m["before_run_id"], "aaaaaaaa-0000-4000-8000-000000000001")

    # E5-b 범위가 다른 두 실행은 경고
    def test_E5b_comparison_warns_on_scope_change(self):
        before = self.write_run("before", results(run_id="aaaaaaaa-0000-4000-8000-000000000002",
                                                  scope={"vpc_id": "", "sg_ids": [SG_WEB], "profile": "default"}))
        target = self.build(self.write_run("after", results()), before_dir=before)
        self.assertIn("범위가 달라", (target / "comparison.md").read_text(encoding="utf-8"))

    # E6 이미 있는 증거 폴더는 덮어쓰지 않음
    def test_E6_existing_bundle_is_not_overwritten(self):
        run = self.write_run("out", results())
        target = self.build(run)
        (target / "manifest.json").write_text("keep", encoding="utf-8")
        with self.assertRaises(me.EvidenceError):
            self.build(run)
        self.assertEqual((target / "manifest.json").read_text(encoding="utf-8"), "keep")

    # E7 결과 파일 없음/깨짐/모양 이상 → 오류, 폴더를 만들지 않음
    def test_E7_bad_results_are_rejected(self):
        empty = self.root / "empty"
        empty.mkdir()
        broken = self.root / "broken"
        broken.mkdir()
        (broken / "results.json").write_text("{not json", encoding="utf-8")
        weird = self.write_run("weird", dict(results(), run_id="../../escape"))
        for d in (empty, broken, weird):
            with self.subTest(d=d.name), self.assertRaises(me.EvidenceError):
                self.build(d)
        self.assertFalse((self.root / "evidence").exists())

    # E8 수집 오류·UNKNOWN이 있으면 알려진 누락에 적힘, 사용자 누락도 가려서 기록
    def test_E8_known_omissions(self):
        data = results(errors=[{"stage": "DescribeNetworkInterfaces", "code": "UnauthorizedOperation",
                                "message": "x"}])
        data["counts"]["UNKNOWN"] = 3
        target = self.build(self.write_run("out", data), omissions=[f"{ENI}는 수동 대조 안 함"])
        m = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
        joined = " ".join(m["known_omissions"])
        self.assertIn("DescribeNetworkInterfaces:UnauthorizedOperation", joined)
        self.assertIn("UNKNOWN 3건", joined)
        self.assertNotIn(ENI, joined)

    # E9 git이 없으면 commit unknown + 누락에 기록 (실패를 숨기지 않음)
    def test_E9_no_git_is_recorded(self):
        target = me.make_evidence(self.write_run("out", results()), self.baseline, self.root / "evidence",
                                  repo_dir=self.root / "no-such-dir")
        m = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(m["commit"], "unknown")
        self.assertTrue(any("commit" in o for o in m["known_omissions"]))

    # E9-b git 출력을 못 읽음(Windows 한글 경로에서 stdout이 None) → 멈추지 않고 commit unknown
    def test_E9b_unreadable_git_output_is_unknown(self):
        class Done:
            stdout = None
        original = me.subprocess.run
        me.subprocess.run = lambda *a, **k: Done()
        try:
            self.assertEqual(me.git_commit(HERE), (None, None))
            target = self.build(self.write_run("out", results()))
        finally:
            me.subprocess.run = original
        m = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(m["commit"], "unknown")

    # E9-c git 출력에 한글 경로가 있어도 UTF-8로 읽음
    def test_E9c_git_called_with_utf8(self):
        seen = []

        class Done:
            def __init__(self, out):
                self.stdout = out
        original = me.subprocess.run

        def fake(cmd, **kw):
            seen.append(kw.get("encoding"))
            return Done("a" * 40 if "rev-parse" in cmd else " M 이민성/sg_audit/README.md\n")
        me.subprocess.run = fake
        try:
            self.assertEqual(me.git_commit(HERE), ("a" * 40, True))
        finally:
            me.subprocess.run = original
        self.assertEqual(seen, ["utf-8", "utf-8"])

    # E10 baseline을 못 읽으면 오류
    def test_E10_missing_baseline_is_error(self):
        with self.assertRaises(me.EvidenceError):
            me.make_evidence(self.write_run("out", results()), self.root / "nope.json", self.root / "evidence")

    # E11 CLI 종료 코드: 성공 0, 오류 2
    def test_E11_cli_exit_codes(self):
        run = self.write_run("out", results())
        args = ["--results-dir", str(run), "--baseline", str(self.baseline), "--evidence-root", str(self.root / "ev")]
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(me.main(args), 0)
            self.assertEqual(me.main(args), 2)       # 두 번째는 이미 있음

    # E12 가림이 빠진 값이 있으면(안전장치) 묶음을 만들지 않음
    def test_E12_leak_guard(self):
        original = me.Masker.text
        me.Masker.text = lambda self, value: value          # 가림을 일부러 끈다
        try:
            with self.assertRaises(me.EvidenceError):
                self.build(self.write_run("out", results()))
        finally:
            me.Masker.text = original
        self.assertFalse((self.root / "evidence").exists())


if __name__ == "__main__":
    unittest.main()
