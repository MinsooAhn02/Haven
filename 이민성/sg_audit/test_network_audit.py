import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "network_audit.py"
BASELINE = HERE / "baseline.json"
FIXTURES = HERE / "fixtures"


class NetworkAuditTests(unittest.TestCase):
    def run_cli(self, fixture, baseline=BASELINE, out=None):
        return subprocess.run(
            [sys.executable, str(SCRIPT), "fixture", "--fixture", str(fixture),
             "--baseline", str(baseline), "--output-dir", str(out)],
            capture_output=True, text=True,
        )

    def test_supplied_fixtures_and_output_formats(self):
        expected = {"pass": 0, "fail_public_db": 1, "unknown_role": 3, "error_access_denied": 2}
        with tempfile.TemporaryDirectory() as temp:
            for name, code in expected.items():
                with self.subTest(fixture=name):
                    out = Path(temp) / name
                    result = self.run_cli(FIXTURES / f"{name}.json", out=out)
                    self.assertEqual(result.returncode, code, result.stderr)
                    self.assertTrue((out / "results.json").is_file())
                    self.assertTrue((out / "findings.csv").read_bytes().startswith(b"\xef\xbb\xbf"))

    def test_missing_expected_asset_is_unknown(self):
        fixture = json.loads((FIXTURES / "pass.json").read_text(encoding="utf-8"))
        fixture["attachments"] = [a for a in fixture["attachments"] if a["asset_id"] != "db-1"]
        fixture["security_groups"] = [sg for sg in fixture["security_groups"] if sg["GroupId"] != "sg-fixture-db"]
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "fixture.json"
            source.write_text(json.dumps(fixture), encoding="utf-8")
            result = self.run_cli(source, out=Path(temp) / "out")
            self.assertEqual(result.returncode, 3, result.stderr)
            saved = json.loads((Path(temp) / "out/results.json").read_text(encoding="utf-8"))
            self.assertTrue(any(f["asset_id"] == "db-1" and f["verdict"] == "UNKNOWN" for f in saved["findings"]))

    def test_bad_schema_and_json_are_error_without_traceback(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            malformed = root / "baseline.json"
            malformed.write_text("[]", encoding="utf-8")
            schema = self.run_cli(FIXTURES / "pass.json", baseline=malformed, out=root / "schema-out")
            self.assertEqual(schema.returncode, 2)
            self.assertNotIn("Traceback", schema.stderr)
            malformed.write_text("{", encoding="utf-8")
            syntax = self.run_cli(FIXTURES / "pass.json", baseline=malformed, out=root / "json-out")
            self.assertEqual(syntax.returncode, 2)
            self.assertNotIn("Traceback", syntax.stderr)

    def test_output_path_errors_are_error_without_traceback(self):
        with tempfile.TemporaryDirectory() as temp:
            file_path = Path(temp) / "file"
            file_path.write_text("occupied", encoding="utf-8")
            result = self.run_cli(FIXTURES / "pass.json", out=file_path)
            self.assertEqual(result.returncode, 2)
            self.assertNotIn("Traceback", result.stderr)

    def test_collected_findings_survive_fixture_errors(self):
        fixture = json.loads((FIXTURES / "pass.json").read_text(encoding="utf-8"))
        fixture["errors"] = [{"stage": "test", "code": "Injected", "message": "partial"}]
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "fixture.json"
            source.write_text(json.dumps(fixture), encoding="utf-8")
            result = self.run_cli(source, out=Path(temp) / "out")
            self.assertEqual(result.returncode, 2)
            saved = json.loads((Path(temp) / "out/results.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["overall_verdict"], "ERROR")
            self.assertEqual(saved["counts"]["PASS"], 10)


    def test_outbound_80_must_match_baseline(self):
        """설계 4.2 web·db outbound TCP 80(apt): 빠지거나 다르게 열리면 FAIL(SG-05)."""
        base = json.loads((FIXTURES / "pass.json").read_text(encoding="utf-8"))

        def egress(fixture, group_id):
            return next(sg for sg in fixture["security_groups"] if sg["GroupId"] == group_id)["IpPermissionsEgress"]

        missing = json.loads(json.dumps(base))
        db_egress = egress(missing, "sg-fixture-db")
        db_egress[:] = [p for p in db_egress if p["FromPort"] != 80]

        wrong_port = json.loads(json.dumps(base))
        for perm in egress(wrong_port, "sg-fixture-web"):
            if perm["FromPort"] == 80:
                perm["FromPort"] = perm["ToPort"] = 8080

        wrong_target = json.loads(json.dumps(base))
        for perm in egress(wrong_target, "sg-fixture-web"):
            if perm["FromPort"] == 80:
                perm["IpRanges"] = [{"CidrIp": "10.0.0.0/8"}]

        cases = {
            "missing": (missing, "db-1", "규칙 없음"),
            "wrong_port": (wrong_port, "web-1", "egress tcp 8080-8080 cidr:0.0.0.0/0"),
            "wrong_target": (wrong_target, "web-1", "egress tcp 80-80 cidr:10.0.0.0/8"),
        }
        with tempfile.TemporaryDirectory() as temp:
            for name, (fixture, asset, actual) in cases.items():
                with self.subTest(case=name):
                    source = Path(temp) / f"{name}.json"
                    source.write_text(json.dumps(fixture), encoding="utf-8")
                    result = self.run_cli(source, out=Path(temp) / name)
                    self.assertEqual(result.returncode, 1, result.stderr)
                    saved = json.loads((Path(temp) / name / "results.json").read_text(encoding="utf-8"))
                    self.assertTrue(any(f["verdict"] == "FAIL" and f["check_id"] == "SG-05"
                                        and f["asset_id"] == asset and f["actual"] == actual
                                        for f in saved["findings"]), saved["findings"])

    def run_saved(self, fixture, temp, name):
        out = Path(temp) / name
        result = self.run_cli(fixture, out=out)
        saved = json.loads((out / "results.json").read_text(encoding="utf-8")) if (out / "results.json").is_file() else None
        return result, saved

    def fails(self, saved):
        return sorted((f["check_id"], f["asset_id"], f["actual"]) for f in saved["findings"] if f["verdict"] == "FAIL")

    def test_aud03_range_ports(self):
        """AUD-03: 범위 안에 숨은 SSH·DB 포트를 잡고, 민감 포트가 없는 범위는 일반 위반으로 둔다."""
        with tempfile.TemporaryDirectory() as temp:
            result, saved = self.run_saved(FIXTURES / "aud03_range_ports.json", temp, "aud03")
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertEqual(self.fails(saved), [
                ("SG-01", "db-1", "ingress tcp 5000-6000 cidr:0.0.0.0/0"),
                ("SG-01", "web-1", "ingress tcp 0-65535 cidr:0.0.0.0/0"),
                ("SG-04", "db-1", "ingress tcp 5400-5500 sg_role:web"),
                ("SG-05", "alb", "ingress tcp 8000-8100 cidr:0.0.0.0/0"),
            ])
            self.assertEqual(saved["counts"]["PASS"], 10)  # 정상 규칙은 그대로 PASS

    def test_aud05_all_protocol_and_missing_ports(self):
        """AUD-05: 전체 프로토콜(-1)·포트 없는 규칙을 죽지 않고 '전부 열림'으로 판정한다."""
        with tempfile.TemporaryDirectory() as temp:
            result, saved = self.run_saved(FIXTURES / "aud05_all_protocol.json", temp, "aud05")
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertNotIn("Traceback", result.stderr)
            self.assertEqual(self.fails(saved), [
                ("SG-01", "db-1", "ingress -1 None-None cidr:0.0.0.0/0"),
                ("SG-02", "web-1", "egress -1 None-None cidr:10.20.0.0/16"),
                ("SG-04", "db-1", "ingress tcp None-None sg_role:web"),
            ])
            self.assertEqual(saved["counts"]["PASS"], 10)

    def test_aud05_malformed_rules_are_error_not_fail(self):
        """AUD-05: 깨진 규칙 모양은 추측하지 않고 ERROR(2). 예전에는 Traceback으로 종료 코드 1(FAIL처럼 보임)이었다."""
        bad_rules = {
            "string_port": {"IpProtocol": "tcp", "FromPort": "22", "ToPort": "22", "IpRanges": [{"CidrIp": "0.0.0.0/0"}]},
            "bool_port": {"IpProtocol": "tcp", "FromPort": True, "ToPort": True, "IpRanges": [{"CidrIp": "0.0.0.0/0"}]},
            "no_protocol": {"FromPort": 22, "ToPort": 22, "IpRanges": [{"CidrIp": "0.0.0.0/0"}]},
            "blank_protocol": {"IpProtocol": " ", "FromPort": 22, "ToPort": 22, "IpRanges": [{"CidrIp": "0.0.0.0/0"}]},
            "rule_not_object": "tcp 22 0.0.0.0/0",
            "ranges_not_list": {"IpProtocol": "tcp", "FromPort": 22, "ToPort": 22, "IpRanges": "0.0.0.0/0"},
            "range_not_object": {"IpProtocol": "tcp", "FromPort": 22, "ToPort": 22, "IpRanges": ["0.0.0.0/0"]},
            "reversed_range": {"IpProtocol": "tcp", "FromPort": 6000, "ToPort": 5000, "IpRanges": [{"CidrIp": "0.0.0.0/0"}]},
            "port_over_65535": {"IpProtocol": "udp", "FromPort": 0, "ToPort": 70000, "IpRanges": [{"CidrIp": "0.0.0.0/0"}]},
        }
        base = json.loads((FIXTURES / "pass.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as temp:
            result, saved = self.run_saved(FIXTURES / "aud05_bad_ports.json", temp, "supplied")
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertNotIn("Traceback", result.stderr)
            self.assertIsNone(saved)  # 판정 전에 멈춰 PASS/FAIL 결과를 남기지 않는다
            cases = {name: rule for name, rule in bad_rules.items()}
            cases["permissions_not_list"] = None
            for name, rule in cases.items():
                with self.subTest(case=name):
                    fixture = json.loads(json.dumps(base))
                    web = next(sg for sg in fixture["security_groups"] if sg["GroupId"] == "sg-fixture-web")
                    if rule is None:
                        web["IpPermissions"] = "tcp 80"
                    else:
                        web["IpPermissions"].append(rule)
                    source = Path(temp) / f"{name}.json"
                    source.write_text(json.dumps(fixture), encoding="utf-8")
                    result, saved = self.run_saved(source, temp, f"out-{name}")
                    self.assertEqual(result.returncode, 2, result.stderr)
                    self.assertNotIn("Traceback", result.stderr)
                    self.assertIsNone(saved)

    def test_aud06_udp_icmp_are_not_tcp(self):
        """AUD-06: UDP 80은 TCP 80 허용이 아니고, UDP 5432·ICMP는 PostgreSQL·SSH가 아니다. RDP는 UDP도 민감 포트."""
        with tempfile.TemporaryDirectory() as temp:
            result, saved = self.run_saved(FIXTURES / "aud06_udp_icmp.json", temp, "aud06")
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertEqual(self.fails(saved), [
                ("SG-01", "web-1", "ingress udp 3389-3389 cidr:0.0.0.0/0"),
                ("SG-05", "alb", "ingress icmp -1--1 cidr:0.0.0.0/0"),
                ("SG-05", "db-1", "ingress udp 5432-5432 cidr:0.0.0.0/0"),
                ("SG-05", "web-1", "ingress icmp 3-22 cidr:0.0.0.0/0"),
                ("SG-05", "web-1", "ingress udp 80-80 sg_role:alb"),
            ])
            # 정상 TCP 80(ALB → Web)은 UDP 80이 있어도 PASS 그대로
            self.assertTrue(any(f["verdict"] == "PASS" and f["actual"] == "ingress tcp 80-80 sg_role:alb"
                                for f in saved["findings"]))
            self.assertEqual(saved["counts"]["PASS"], 10)

    def test_icmp_type_code_is_not_a_port_range(self):
        """ICMP echo request(type 8, code 0)는 FromPort 8 > ToPort 0이 정상이다. 깨진 범위로 보지 않는다."""
        base = json.loads((FIXTURES / "pass.json").read_text(encoding="utf-8"))
        web = next(sg for sg in base["security_groups"] if sg["GroupId"] == "sg-fixture-web")
        web["IpPermissions"].append({"IpProtocol": "icmp", "FromPort": 8, "ToPort": 0, "IpRanges": [{"CidrIp": "10.20.0.0/16"}]})
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "icmp.json"
            source.write_text(json.dumps(base), encoding="utf-8")
            result, saved = self.run_saved(source, temp, "icmp")
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertEqual(self.fails(saved), [("SG-05", "web-1", "ingress icmp 8-0 cidr:10.20.0.0/16")])

    def test_numeric_protocol_is_same_as_name(self):
        """AWS가 프로토콜을 번호(6=tcp, 17=udp)로 줘도 이름과 똑같이 판정한다."""
        base = json.loads((FIXTURES / "pass.json").read_text(encoding="utf-8"))
        for perm in next(sg for sg in base["security_groups"] if sg["GroupId"] == "sg-fixture-alb")["IpPermissions"]:
            perm["IpProtocol"] = "6"
        db = next(sg for sg in base["security_groups"] if sg["GroupId"] == "sg-fixture-db")
        db["IpPermissions"].append({"IpProtocol": 17, "FromPort": 5432, "ToPort": 5432, "IpRanges": [{"CidrIp": "0.0.0.0/0"}]})
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "numeric.json"
            source.write_text(json.dumps(base), encoding="utf-8")
            result, saved = self.run_saved(source, temp, "numeric")
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertEqual(self.fails(saved), [("SG-05", "db-1", "ingress udp 5432-5432 cidr:0.0.0.0/0")])
            self.assertEqual(saved["counts"]["PASS"], 10)  # "6"은 tcp로 읽혀 ALB 443·80이 PASS

if __name__ == "__main__":
    unittest.main()
