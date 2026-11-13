"""live 모드 시험 (설계 L1~L15). 실제 AWS·boto3 없이 가짜 EC2 클라이언트로 돌린다.

실행(저장소 루트):
    python -B -m unittest discover -s 이민성/sg_audit -p "test_*.py" -v
"""
import contextlib
import copy
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import network_audit as na  # noqa: E402

BASELINE = HERE / "baseline.json"
VPC = "vpc-fake0001"
ACCOUNT = "123456789012"


class FakeClientError(Exception):
    """botocore ClientError와 같은 모양(response["Error"]["Code"])."""

    def __init__(self, code):
        super().__init__(f"An error occurred ({code}) ... arn:aws:iam::{ACCOUNT}:user/someone")
        self.response = {"Error": {"Code": code, "Message": "secret detail"}}


class NoCredentialsError(Exception):
    """botocore.exceptions.NoCredentialsError 대신(이름으로 코드가 정해짐)."""


def sg(group_id, name, ingress=(), egress=()):
    return {"GroupId": group_id, "GroupName": name, "OwnerId": ACCOUNT,
            "IpPermissions": list(ingress), "IpPermissionsEgress": list(egress)}


def cidr(port, value="0.0.0.0/0"):
    return {"IpProtocol": "tcp", "FromPort": port, "ToPort": port, "IpRanges": [{"CidrIp": value}]}


def ref(port, group_id):
    return {"IpProtocol": "tcp", "FromPort": port, "ToPort": port, "UserIdGroupPairs": [{"GroupId": group_id}]}


def good_world():
    """설계 4장대로 만든 가짜 AWS (build.sh가 만드는 규칙과 같음). default SG는 비어 있음."""
    alb, web, db, dflt = "sg-alb01", "sg-web01", "sg-db01", "sg-default01"
    return {
        "vpcs": [{"VpcId": VPC, "OwnerId": ACCOUNT}],
        "security_groups": [
            sg(alb, "haven-sg-alb", [cidr(443), cidr(80)], [ref(80, web)]),
            sg(web, "haven-sg-web", [ref(80, alb)], [ref(5432, db), cidr(443), cidr(80)]),
            sg(db, "haven-sg-db", [ref(5432, web)], [cidr(443), cidr(80)]),
            sg(dflt, "default"),
        ],
        "instances": [
            {"InstanceId": "i-web", "Tags": [{"Key": "Name", "Value": "web-1"}],
             "State": {"Name": "running"}, "SecurityGroups": [{"GroupId": web}]},
            {"InstanceId": "i-db", "Tags": [{"Key": "Name", "Value": "db-1"}],
             "State": {"Name": "stopped"}, "SecurityGroups": [{"GroupId": db}]},
        ],
        # ALB는 가용 영역마다 ENI가 하나씩(11/13 실제 확인: 2개, 둘 다 haven-sg-alb)
        "enis": [
            {"Description": "ELB app/haven-alb/abc", "Groups": [{"GroupId": alb}]},
            {"Description": "ELB app/haven-alb/abc", "Groups": [{"GroupId": alb}]},
        ],
    }


class FakeEC2:
    """Describe* 4개만 있는 가짜 클라이언트. 다른 API를 부르면 AttributeError로 드러난다."""

    def __init__(self, world, errors=None, page_size=None):
        self.world = world
        self.errors = errors or {}        # 메서드 이름 → 예외 목록(호출마다 하나씩 꺼냄)
        self.page_size = page_size
        self.calls = []

    def _maybe_fail(self, method):
        queue = self.errors.get(method)
        if queue:
            raise queue.pop(0)

    def _page(self, method, key, items, NextToken=None):
        self.calls.append(method)
        self._maybe_fail(method)
        start = int(NextToken or 0)
        size = self.page_size or len(items) or 1
        page = {key: items[start:start + size]}
        if start + size < len(items):
            page["NextToken"] = str(start + size)
        return page

    @staticmethod
    def _filter(filters, name):
        return next((f["Values"] for f in filters if f["Name"] == name), None)

    def describe_vpcs(self, Filters, NextToken=None):
        return self._page("describe_vpcs", "Vpcs", self.world["vpcs"], NextToken)

    def describe_security_groups(self, Filters, NextToken=None):
        return self._page("describe_security_groups", "SecurityGroups", self.world["security_groups"], NextToken)

    def describe_instances(self, Filters, NextToken=None):
        names = self._filter(Filters, "tag:Name") or []
        states = self._filter(Filters, "instance-state-name") or []
        found = [i for i in self.world["instances"]
                 if any(t["Key"] == "Name" and t["Value"] in names for t in i["Tags"])
                 and i["State"]["Name"] in states]
        return self._page("describe_instances", "Reservations", [{"Instances": [i]} for i in found], NextToken)

    def describe_network_interfaces(self, Filters, NextToken=None):
        pattern = (self._filter(Filters, "description") or [""])[0].rstrip("*")
        found = [e for e in self.world["enis"] if e["Description"].startswith(pattern)]
        return self._page("describe_network_interfaces", "NetworkInterfaces", found, NextToken)


class Args:
    def __init__(self, out, baseline=BASELINE):
        self.baseline = str(baseline)
        self.output_dir = str(out)
        self.region = "ap-northeast-2"
        self.project = "Haven"
        self.alb_name = "haven-alb"


class LiveTests(unittest.TestCase):
    def run_live(self, client, out=None, factory=None, baseline=BASELINE):
        """run_live를 직접 부른다. (종료 코드, results.json 내용, 화면 출력)"""
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / "out" if out is None else out
            stdout, stderr = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = na.run_live(Args(out, baseline), client_factory=factory or (lambda region: client),
                                   sleep=lambda seconds: None)
            saved = json.loads((out / "results.json").read_text(encoding="utf-8")) if (out / "results.json").exists() else None
            return code, saved, stdout.getvalue() + stderr.getvalue()

    def assert_no_secret(self, saved, text):
        blob = json.dumps(saved, ensure_ascii=False) + text
        self.assertNotIn(ACCOUNT, blob)            # 계정 번호는 가려서 저장
        self.assertNotIn("secret detail", blob)    # AWS 오류 원문은 남기지 않음
        self.assertNotIn("Traceback", blob)

    def checks(self, saved, verdict=None):
        return [(f["check_id"], f["asset_id"]) for f in saved["findings"]
                if verdict is None or f["verdict"] == verdict]

    # L1 설계대로 + default SG 비어 있음 → PASS
    def test_L1_good_world_is_pass(self):
        client = FakeEC2(good_world())
        code, saved, text = self.run_live(client)
        self.assertEqual(code, 0, text)
        self.assertEqual(saved["overall_verdict"], "PASS")
        self.assertEqual(saved["counts"], {"PASS": 11, "FAIL": 0, "UNKNOWN": 0, "ERROR": 0})  # 10 + default SG 1
        self.assertEqual(saved["account_id"], "1234********")
        self.assertEqual(saved["mode"], "live")
        self.assertTrue(set(client.calls) <= {"describe_vpcs", "describe_security_groups",
                                              "describe_instances", "describe_network_interfaces"})
        self.assert_no_secret(saved, text)

    # L2 default SG에 AWS 기본 규칙 → FAIL SG-07
    def test_L2_default_sg_with_rules_is_fail(self):
        world = good_world()
        dflt = world["security_groups"][3]
        dflt["IpPermissions"] = [{"IpProtocol": "-1", "UserIdGroupPairs": [{"GroupId": dflt["GroupId"]}]}]
        dflt["IpPermissionsEgress"] = [{"IpProtocol": "-1", "IpRanges": [{"CidrIp": "0.0.0.0/0"}]}]
        code, saved, text = self.run_live(FakeEC2(world))
        self.assertEqual(code, 1, text)
        self.assertEqual(self.checks(saved, "FAIL"), [("SG-07", "(default SG)")] * 2)
        self.assertNotIn("SG-06", [c for c, _ in self.checks(saved)])   # default SG는 '연결 안 된 SG'로 안 셈

    # L3 SG 조회 권한 거부 → ERROR, PASS 아님
    def test_L3_sg_access_denied_is_error(self):
        client = FakeEC2(good_world(), errors={"describe_security_groups": [FakeClientError("UnauthorizedOperation")]})
        code, saved, text = self.run_live(client)
        self.assertEqual(code, 2, text)
        self.assertEqual(saved["overall_verdict"], "ERROR")
        self.assertEqual(saved["errors"][0]["code"], "UnauthorizedOperation")
        self.assertEqual(saved["counts"]["PASS"], 0)
        self.assert_no_secret(saved, text)

    # L4 인스턴스 조회만 거부 → ERROR, 읽은 ALB 결과는 보존
    def test_L4_partial_collection_keeps_findings(self):
        client = FakeEC2(good_world(), errors={"describe_instances": [FakeClientError("UnauthorizedOperation")]})
        code, saved, text = self.run_live(client)
        self.assertEqual(code, 2, text)
        self.assertEqual(saved["collection_status"], "FAILED")
        self.assertTrue(any(f["asset_id"] == "alb" and f["verdict"] == "PASS" for f in saved["findings"]))
        self.assertTrue(any(f["asset_id"] == "web-1" and f["verdict"] == "UNKNOWN" for f in saved["findings"]))

    # L5 자격 증명 없음(로그인 만료) → ERROR, Traceback 없음
    def test_L5_no_credentials_is_error(self):
        client = FakeEC2(good_world(), errors={"describe_vpcs": [NoCredentialsError()]})
        code, saved, text = self.run_live(client)
        self.assertEqual(code, 2, text)
        self.assertEqual(saved["errors"][0]["code"], "NoCredentialsError")
        self.assert_no_secret(saved, text)

    # L5-b boto3가 없음 → ERROR(설치 안내), Traceback 없음
    def test_L5b_boto3_missing_is_error(self):
        def factory(region):
            raise ImportError("No module named 'boto3'")
        code, saved, text = self.run_live(None, factory=factory)
        self.assertEqual(code, 2, text)
        self.assertEqual(saved["errors"][0]["code"], "Boto3NotInstalled")
        self.assertNotIn("Traceback", text)

    # L6 Haven VPC 0개 / 2개 → ERROR
    def test_L6_vpc_not_found_or_ambiguous_is_error(self):
        for count, expected in ((0, "VpcNotFound"), (2, "VpcAmbiguous")):
            with self.subTest(vpcs=count):
                world = good_world()
                world["vpcs"] = [{"VpcId": f"vpc-{i}", "OwnerId": ACCOUNT} for i in range(count)]
                client = FakeEC2(world)
                code, saved, text = self.run_live(client)
                self.assertEqual(code, 2, text)
                self.assertEqual(saved["errors"][0]["code"], expected)
                self.assertEqual(client.calls, ["describe_vpcs"])   # VPC가 정해지지 않으면 더 읽지 않음

    # L7 web-1 인스턴스 없음 → UNKNOWN
    def test_L7_missing_server_is_unknown(self):
        world = good_world()
        world["instances"] = [i for i in world["instances"] if i["InstanceId"] != "i-web"]
        code, saved, text = self.run_live(FakeEC2(world))
        self.assertEqual(code, 3, text)
        self.assertIn(("SG-06", "web-1"), self.checks(saved, "UNKNOWN"))

    # L7-b 종료(terminated)된 web-1만 있으면 없는 것으로 본다
    def test_L7b_terminated_server_is_not_counted(self):
        world = good_world()
        world["instances"][0]["State"]["Name"] = "terminated"
        code, saved, text = self.run_live(FakeEC2(world))
        self.assertEqual(code, 3, text)
        self.assertIn(("SG-06", "web-1"), self.checks(saved, "UNKNOWN"))

    # L8 ALB ENI 없음 → UNKNOWN
    def test_L8_missing_alb_is_unknown(self):
        world = good_world()
        world["enis"] = []
        code, saved, text = self.run_live(FakeEC2(world))
        self.assertEqual(code, 3, text)
        self.assertIn(("SG-06", "alb"), self.checks(saved, "UNKNOWN"))

    # L9 여러 페이지 → 끝까지 읽고 정상 판정
    def test_L9_paginated_results_are_complete(self):
        client = FakeEC2(good_world(), page_size=1)
        code, saved, text = self.run_live(client)
        self.assertEqual(code, 0, text)
        self.assertEqual(client.calls.count("describe_security_groups"), 4)
        self.assertEqual(saved["counts"]["PASS"], 11)

    # L10 지우는 걸 잊은 SG → UNKNOWN SG-06
    def test_L10_leftover_sg_is_unknown(self):
        world = good_world()
        world["security_groups"].append(sg("sg-test01", "haven-sg-test"))
        code, saved, text = self.run_live(FakeEC2(world))
        self.assertEqual(code, 3, text)
        self.assertTrue(any(f["check_id"] == "SG-06" and f["sg_id"] == "sg-test01" for f in saved["findings"]))

    # L11 같은 이름의 SG 2개 → ERROR
    def test_L11_duplicate_sg_name_is_error(self):
        world = good_world()
        world["security_groups"].append(sg("sg-web02", "haven-sg-web"))
        code, saved, text = self.run_live(FakeEC2(world))
        self.assertEqual(code, 2, text)
        self.assertIn("DuplicateSgName", [e["code"] for e in saved["errors"]])

    # L11-b 같은 Name 태그의 인스턴스 2개 → ERROR
    def test_L11b_duplicate_instance_name_is_error(self):
        world = good_world()
        world["instances"].append(copy.deepcopy(world["instances"][0]) | {"InstanceId": "i-web2"})
        code, saved, text = self.run_live(FakeEC2(world))
        self.assertEqual(code, 2, text)
        self.assertIn("DuplicateInstanceName", [e["code"] for e in saved["errors"]])

    # L12 요청 제한: 2번 실패 후 성공 → PASS / 계속 실패 → 3번 시도 후 ERROR
    def test_L12_throttling_retries_then_error(self):
        recover = FakeEC2(good_world(), errors={"describe_security_groups": [FakeClientError("Throttling")] * 2})
        code, saved, text = self.run_live(recover)
        self.assertEqual(code, 0, text)
        self.assertEqual(recover.calls.count("describe_security_groups"), 3)

        stuck = FakeEC2(good_world(), errors={"describe_security_groups": [FakeClientError("Throttling")] * 5})
        code, saved, text = self.run_live(stuck)
        self.assertEqual(code, 2, text)
        self.assertEqual(stuck.calls.count("describe_security_groups"), na.MAX_ATTEMPTS)
        self.assertEqual(saved["errors"][0]["code"], "Throttling")

    # L13 IPv6 ::/0 22번 → SG-01, prefix list → SG-05
    def test_L13_ipv6_and_prefix_list_rules(self):
        world = good_world()
        web = world["security_groups"][1]
        web["IpPermissions"].append({"IpProtocol": "tcp", "FromPort": 22, "ToPort": 22,
                                     "Ipv6Ranges": [{"CidrIpv6": "::/0"}]})
        web["IpPermissionsEgress"].append({"IpProtocol": "tcp", "FromPort": 443, "ToPort": 443,
                                           "PrefixListIds": [{"PrefixListId": "pl-fake"}]})
        code, saved, text = self.run_live(FakeEC2(world))
        self.assertEqual(code, 1, text)
        self.assertCountEqual(self.checks(saved, "FAIL"), [("SG-01", "web-1"), ("SG-05", "web-1")])

    # L14 출력 폴더가 이미 차 있음 → AWS를 읽기 전에 ERROR
    def test_L14_existing_output_dir_stops_before_aws(self):
        client = FakeEC2(good_world())
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / "out"
            out.mkdir()
            (out / "old.txt").write_text("keep", encoding="utf-8")
            code, saved, text = self.run_live(client, out=out)
            self.assertEqual(code, 2, text)
            self.assertEqual(client.calls, [])
            self.assertEqual((out / "old.txt").read_text(encoding="utf-8"), "keep")

    # L15 ALB ENI 2개(같은 SG) → 중복 없이 1개로 판정
    def test_L15_alb_enis_are_deduplicated(self):
        code, saved, text = self.run_live(FakeEC2(good_world()))
        self.assertEqual(code, 0, text)
        alb_rules = [f for f in saved["findings"] if f["asset_id"] == "alb"]
        self.assertEqual(len(alb_rules), 3)            # alb 허용 규칙 3개가 한 번씩만

    # 이름이 바뀐(없는) SG → 기대 SG 미연결 FAIL
    def test_renamed_sg_is_fail_not_pass(self):
        world = good_world()
        world["security_groups"][2]["GroupName"] = "haven-sg-db-old"
        code, saved, text = self.run_live(FakeEC2(world))
        self.assertNotEqual(code, 0, text)
        self.assertTrue(any(f["check_id"] == "SG-05" and f["sg_id"] == "missing:haven-sg-db"
                            and f["verdict"] == "FAIL" for f in saved["findings"]))

    # baseline에 expected_sg_names가 없으면 live는 ERROR
    def test_baseline_without_names_is_error(self):
        data = json.loads(BASELINE.read_text(encoding="utf-8"))
        for asset in data["assets"]:
            asset.pop("expected_sg_names", None)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "b.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            code, saved, text = self.run_live(FakeEC2(good_world()), baseline=path)
        self.assertEqual(code, 2, text)
        self.assertIn("NoExpectedSgNames", [e["code"] for e in saved["errors"]])

    # 예상 못 한 응답 모양 → Traceback 없이 ERROR
    def test_unexpected_response_shape_is_error(self):
        world = good_world()
        world["vpcs"] = [{"NoVpcIdHere": True}]
        code, saved, text = self.run_live(FakeEC2(world))
        self.assertEqual(code, 2, text)
        self.assertNotIn("Traceback", text)


if __name__ == "__main__":
    unittest.main()
