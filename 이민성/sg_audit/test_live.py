"""live 모드 시험 (명세 5.1). 실제 AWS·boto3 없이 가짜 EC2·STS 클라이언트로 돌린다.

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

VPC = "vpc-fake0001"
ACCOUNT = "123456789012"
ALB, WEB, DB, DFLT = "sg-alb01", "sg-web01", "sg-db01", "sg-default01"

_TMP = tempfile.TemporaryDirectory()
LIVE_BASELINE = Path(_TMP.name) / "baseline.live.json"


def setUpModule():
    """baseline.json을 복사해 실제처럼 sg-... ID를 넣은 baseline.live.json을 만든다(실제 파일은 깃에 안 올림)."""
    data = json.loads((HERE / "baseline.json").read_text(encoding="utf-8"))
    ids = {"alb": [ALB], "web-1": [WEB], "db-1": [DB]}
    for asset in data["assets"]:
        asset["expected_sg_ids"] = ids[asset["asset_id"]]
    LIVE_BASELINE.write_text(json.dumps(data), encoding="utf-8")


def tearDownModule():
    _TMP.cleanup()


class FakeClientError(Exception):
    """botocore ClientError와 같은 모양(response["Error"]["Code"])."""

    def __init__(self, code):
        super().__init__(f"An error occurred ({code}) ... arn:aws:iam::{ACCOUNT}:user/someone")
        self.response = {"Error": {"Code": code, "Message": "secret detail"}}


class NoCredentialsError(Exception):
    """botocore.exceptions.NoCredentialsError 대신(이름으로 코드가 정해짐)."""


def sg(group_id, name, ingress=(), egress=(), vpc=VPC):
    return {"GroupId": group_id, "GroupName": name, "OwnerId": ACCOUNT, "VpcId": vpc,
            "IpPermissions": list(ingress), "IpPermissionsEgress": list(egress)}


def cidr(port, value="0.0.0.0/0"):
    return {"IpProtocol": "tcp", "FromPort": port, "ToPort": port, "IpRanges": [{"CidrIp": value}]}


def ref(port, group_id):
    return {"IpProtocol": "tcp", "FromPort": port, "ToPort": port, "UserIdGroupPairs": [{"GroupId": group_id}]}


def eni(eni_id, *groups, desc="", status="in-use"):
    e = {"NetworkInterfaceId": eni_id, "VpcId": VPC, "Description": desc,
         "Groups": [{"GroupId": g} for g in groups]}
    if status is not None:
        e["Status"] = status
    return e


def good_world():
    """설계 4장대로 만든 가짜 AWS (build.sh가 만드는 규칙과 같음). default SG는 비어 있음."""
    return {
        "vpcs": [{"VpcId": VPC, "OwnerId": ACCOUNT}],
        "security_groups": [
            sg(ALB, "haven-sg-alb", [cidr(443), cidr(80)], [ref(80, WEB)]),
            sg(WEB, "haven-sg-web", [ref(80, ALB)], [ref(5432, DB), cidr(443), cidr(80)]),
            sg(DB, "haven-sg-db", [ref(5432, WEB)], [cidr(443), cidr(80)]),
            sg(DFLT, "default"),
        ],
        # ALB는 가용 영역마다 ENI가 하나씩(11/13 실제 확인: 2개, 둘 다 ALB SG)
        "enis": [
            eni("eni-alb-a", ALB, desc="ELB app/haven-alb/abc"),
            eni("eni-alb-c", ALB, desc="ELB app/haven-alb/abc"),
            eni("eni-web", WEB),
            eni("eni-db", DB),
        ],
    }


class FakeEC2:
    """Describe* 3개만 있는 가짜 클라이언트. 다른 API(DescribeInstances 등)를 부르면 AttributeError로 드러난다."""

    def __init__(self, world, errors=None, page_size=None):
        self.world = world
        self.errors = errors or {}        # 메서드 이름 → 예외 목록(호출마다 하나씩 꺼냄)
        self.page_size = page_size
        self.calls = []
        self.kwargs = []

    def _page(self, method, key, items, NextToken=None, **kwargs):
        self.calls.append(method)
        self.kwargs.append((method, kwargs))
        queue = self.errors.get(method)
        if queue:
            raise queue.pop(0)
        start = int(NextToken or 0)
        size = self.page_size or len(items) or 1
        page = {key: items[start:start + size]}
        if start + size < len(items):
            page["NextToken"] = str(start + size)
        return page

    @staticmethod
    def _filter(filters, name):
        return next((f["Values"] for f in (filters or []) if f["Name"] == name), None)

    def describe_vpcs(self, VpcIds, NextToken=None):
        found = [v for v in self.world["vpcs"] if v.get("VpcId") in VpcIds or "VpcId" not in v]
        return self._page("describe_vpcs", "Vpcs", found, NextToken, VpcIds=VpcIds)

    def describe_security_groups(self, Filters=None, GroupIds=None, NextToken=None):
        groups = self.world["security_groups"]
        if GroupIds is not None:
            known = {g["GroupId"] for g in groups}
            if any(g not in known for g in GroupIds) and not self.errors.get("describe_security_groups"):
                self.errors["describe_security_groups"] = [FakeClientError("InvalidGroup.NotFound")]
            found = [g for g in groups if g["GroupId"] in GroupIds]
        else:
            vpcs = self._filter(Filters, "vpc-id")
            found = [g for g in groups if g["VpcId"] in vpcs]
        return self._page("describe_security_groups", "SecurityGroups", found, NextToken,
                          Filters=Filters, GroupIds=GroupIds)

    def describe_network_interfaces(self, Filters, NextToken=None):
        vpcs = self._filter(Filters, "vpc-id")
        groups = self._filter(Filters, "group-id")
        found = [e for e in self.world["enis"]
                 if (vpcs is None or e["VpcId"] in vpcs)
                 and (groups is None or any(g["GroupId"] in groups for g in e["Groups"]))]
        return self._page("describe_network_interfaces", "NetworkInterfaces", found, NextToken, Filters=Filters)


class FakeSTS:
    def __init__(self, account=ACCOUNT, error=None):
        self.account, self.error, self.calls = account, error, 0

    def get_caller_identity(self):
        self.calls += 1
        if self.error:
            raise self.error
        return {"Account": self.account, "Arn": f"arn:aws:iam::{self.account}:user/minsung"}


class Args:
    def __init__(self, out, baseline=None, vpc_id=VPC, sg_id=None):
        self.baseline = str(baseline or LIVE_BASELINE)
        self.output_dir = str(out)
        self.region = "ap-northeast-2"
        self.profile = "default"
        self.vpc_id = None if sg_id else vpc_id
        self.sg_id = sg_id


class LiveTests(unittest.TestCase):
    def run_live(self, client, out=None, factory=None, baseline=None, sts=None, sg_id=None):
        """run_live를 직접 부른다. (종료 코드, results.json 내용, 화면 출력)"""
        sts = sts or FakeSTS()
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / "out" if out is None else out
            stdout, stderr = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = na.run_live(Args(out, baseline, sg_id=sg_id),
                                   client_factory=factory or (lambda profile, region: (client, sts)),
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

    # L1 설계대로 + default SG 비어 있음 → PASS. 시작할 때 계정(가림)·리전·범위를 찍는다
    def test_L1_good_world_is_pass(self):
        client = FakeEC2(good_world())
        code, saved, text = self.run_live(client)
        self.assertEqual(code, 0, text)
        self.assertEqual(saved["overall_verdict"], "PASS")
        self.assertEqual(saved["counts"], {"PASS": 11, "FAIL": 0, "UNKNOWN": 0, "ERROR": 0})  # 10 + default SG 1
        self.assertEqual(saved["account_id"], "1234********")
        self.assertEqual(saved["scope"]["vpc_id"], VPC)
        self.assertIn(f"대상 계정: 1234********  리전: ap-northeast-2  범위: VPC {VPC}", text.splitlines()[0])
        self.assertTrue(set(client.calls) <= {"describe_vpcs", "describe_security_groups",
                                              "describe_network_interfaces"})
        self.assert_no_secret(saved, text)

    # L2 default SG에 AWS 기본 규칙 → FAIL SG-07
    def test_L2_default_sg_with_rules_is_fail(self):
        world = good_world()
        dflt = world["security_groups"][3]
        dflt["IpPermissions"] = [{"IpProtocol": "-1", "UserIdGroupPairs": [{"GroupId": DFLT}]}]
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

    # L4 ENI(연결 정보)만 거부 → ERROR. SG 규칙 결과는 남기고, 자산 접근 결과는 UNKNOWN으로 나눈다
    def test_L4_eni_failure_keeps_sg_rules_and_marks_assets_unknown(self):
        client = FakeEC2(good_world(), errors={"describe_network_interfaces": [FakeClientError("UnauthorizedOperation")]})
        code, saved, text = self.run_live(client)
        self.assertEqual(code, 2, text)
        self.assertEqual(saved["collection_status"], "FAILED")
        self.assertTrue(any(f["asset_id"] == "alb" and f["verdict"] == "PASS" for f in saved["findings"]))
        unknown = [f for f in saved["findings"] if f["verdict"] == "UNKNOWN" and "연결 정보" in f["reason"]]
        self.assertCountEqual([f["asset_id"] for f in unknown], ["alb", "web-1", "db-1"])

    # L5 자격 증명 없음(로그인 만료) → ERROR, EC2는 읽지 않음, Traceback 없음
    def test_L5_no_credentials_is_error(self):
        client = FakeEC2(good_world())
        code, saved, text = self.run_live(client, sts=FakeSTS(error=NoCredentialsError()))
        self.assertEqual(code, 2, text)
        self.assertEqual(saved["errors"][0]["code"], "NoCredentialsError")
        self.assertEqual(client.calls, [])
        self.assert_no_secret(saved, text)

    # L5-b boto3가 없음 → ERROR(설치 안내), Traceback 없음
    def test_L5b_boto3_missing_is_error(self):
        def factory(profile, region):
            raise ImportError("No module named 'boto3'")
        code, saved, text = self.run_live(None, factory=factory)
        self.assertEqual(code, 2, text)
        self.assertEqual(saved["errors"][0]["code"], "Boto3NotInstalled")
        self.assertNotIn("Traceback", text)

    # L5-c 없는 프로필(ProfileNotFound) → ERROR
    def test_L5c_unknown_profile_is_error(self):
        class ProfileNotFound(Exception):
            pass

        def factory(profile, region):
            raise ProfileNotFound("The config profile (nope) could not be found")
        code, saved, text = self.run_live(None, factory=factory)
        self.assertEqual(code, 2, text)
        self.assertEqual(saved["errors"][0]["code"], "ProfileNotFound")

    # L6 지정한 VPC가 없음 / 다른 계정 것 → ERROR, 더 읽지 않음
    def test_L6_vpc_not_found_or_other_account_is_error(self):
        for vpcs, expected in (([], "VpcNotFound"),
                               ([{"VpcId": VPC, "OwnerId": "999999999999"}], "VpcOwnerMismatch")):
            with self.subTest(expected=expected):
                world = good_world()
                world["vpcs"] = vpcs
                client = FakeEC2(world)
                code, saved, text = self.run_live(client)
                self.assertEqual(code, 2, text)
                self.assertEqual(saved["errors"][0]["code"], expected)
                self.assertEqual(client.calls, ["describe_vpcs"])
                self.assertNotIn("999999999999", text + json.dumps(saved))

    # L7 web-1이 없음(ENI 없음) → web-1 UNKNOWN, web SG는 '연결된 자산 없음' UNKNOWN
    def test_L7_missing_server_is_unknown(self):
        world = good_world()
        world["enis"] = [e for e in world["enis"] if e["NetworkInterfaceId"] != "eni-web"]
        code, saved, text = self.run_live(FakeEC2(world))
        self.assertEqual(code, 3, text)
        self.assertIn(("SG-06", "web-1"), self.checks(saved, "UNKNOWN"))
        self.assertTrue(any(f["sg_id"] == WEB and f["verdict"] == "UNKNOWN" for f in saved["findings"]))

    # L8 ALB ENI 없음 → UNKNOWN
    def test_L8_missing_alb_is_unknown(self):
        world = good_world()
        world["enis"] = [e for e in world["enis"] if not e["NetworkInterfaceId"].startswith("eni-alb")]
        code, saved, text = self.run_live(FakeEC2(world))
        self.assertEqual(code, 3, text)
        self.assertIn(("SG-06", "alb"), self.checks(saved, "UNKNOWN"))

    # L9 여러 페이지 → 마지막 페이지까지 읽고 정상 판정
    def test_L9_paginated_results_are_complete(self):
        client = FakeEC2(good_world(), page_size=1)
        code, saved, text = self.run_live(client)
        self.assertEqual(code, 0, text)
        self.assertEqual(client.calls.count("describe_security_groups"), 4)
        self.assertEqual(client.calls.count("describe_network_interfaces"), 4)
        self.assertEqual(saved["counts"]["PASS"], 11)

    # L10 지우는 걸 잊은 SG → UNKNOWN SG-06
    def test_L10_leftover_sg_is_unknown(self):
        world = good_world()
        world["security_groups"].append(sg("sg-test01", "haven-sg-test"))
        code, saved, text = self.run_live(FakeEC2(world))
        self.assertEqual(code, 3, text)
        self.assertTrue(any(f["check_id"] == "SG-06" and f["sg_id"] == "sg-test01" for f in saved["findings"]))

    # L11 한 ENI에 두 자산의 기대 SG가 같이 붙음 → 역할 미확정 UNKNOWN
    def test_L11_eni_with_two_assets_sgs_is_unknown(self):
        world = good_world()
        world["enis"].append(eni("eni-mixed", WEB, DB))
        code, saved, text = self.run_live(FakeEC2(world))
        self.assertEqual(code, 3, text)
        mixed = [f for f in saved["findings"] if "역할 미확정" in f["reason"]]
        self.assertEqual(len(mixed), 1)
        self.assertIn("eni-mixed", mixed[0]["evidence"])

    # L11-b 이름·태그만 바뀌어도 판정은 그대로(이름으로 역할을 추정하지 않음)
    def test_L11b_names_do_not_decide_roles(self):
        world = good_world()
        for g in world["security_groups"][:3]:
            g["GroupName"] = "renamed-" + g["GroupName"]
        world["security_groups"].append(sg("sg-fake-web", "haven-sg-web"))   # 이름만 같은 다른 SG
        code, saved, text = self.run_live(FakeEC2(world))
        self.assertEqual(code, 3, text)                                     # 가짜 SG는 연결 없음 UNKNOWN
        self.assertEqual(saved["counts"]["PASS"], 11)
        self.assertEqual(saved["counts"]["FAIL"], 0)

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

    # L14 출력 폴더가 이미 차 있음 → AWS(STS 포함)를 읽기 전에 ERROR
    def test_L14_existing_output_dir_stops_before_aws(self):
        client, sts = FakeEC2(good_world()), FakeSTS()
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / "out"
            out.mkdir()
            (out / "old.txt").write_text("keep", encoding="utf-8")
            code, saved, text = self.run_live(client, out=out, sts=sts)
            self.assertEqual(code, 2, text)
            self.assertEqual((client.calls, sts.calls), ([], 0))
            self.assertEqual((out / "old.txt").read_text(encoding="utf-8"), "keep")

    # L15 ALB ENI 2개(같은 SG) → 중복 없이 1개로 판정
    def test_L15_alb_enis_are_deduplicated(self):
        code, saved, text = self.run_live(FakeEC2(good_world()))
        self.assertEqual(code, 0, text)
        alb_rules = [f for f in saved["findings"] if f["asset_id"] == "alb"]
        self.assertEqual(len(alb_rules), 3)            # alb 허용 규칙 3개가 한 번씩만

    # L16 --sg-id 범위: 같은 자산에 붙은 추가 SG까지 합쳐서 본다. 범위 밖 자산은 UNKNOWN으로 세지 않음
    def test_L16_sg_scope_includes_other_sgs_on_same_asset(self):
        world = good_world()
        world["security_groups"].append(sg("sg-extra01", "anything", [cidr(22)]))
        world["enis"][2]["Groups"].append({"GroupId": "sg-extra01"})       # web ENI에 추가 SG
        client = FakeEC2(world)
        code, saved, text = self.run_live(client, sg_id=[WEB])
        self.assertEqual(code, 1, text)
        self.assertNotIn("describe_vpcs", client.calls)
        self.assertIn(("SG-01", "web-1"), self.checks(saved, "FAIL"))
        self.assertEqual({f["asset_id"] for f in saved["findings"] if f["asset_id"]}, {"web-1"})
        self.assertEqual(saved["scope"]["sg_ids"], [WEB])
        self.assertNotIn("SG-07", [c for c, _ in self.checks(saved)])     # default SG 판정은 VPC 범위에서만
        self.assertIn(f"범위: SG {WEB}", text)

    # L16-b --sg-id 범위, 정상이면 web-1 규칙만 PASS
    def test_L16b_sg_scope_pass(self):
        code, saved, text = self.run_live(FakeEC2(good_world()), sg_id=[WEB])
        self.assertEqual(code, 0, text)
        self.assertEqual(saved["counts"], {"PASS": 4, "FAIL": 0, "UNKNOWN": 0, "ERROR": 0})

    # L16-c --sg-id 범위에서는 자산에 default SG가 같이 붙어 있어도 SG-07을 판정하지 않음(VPC 범위 전용)
    def test_L16c_sg_scope_skips_default_sg_check(self):
        world = good_world()
        world["enis"][2]["Groups"].append({"GroupId": DFLT})
        code, saved, text = self.run_live(FakeEC2(world), sg_id=[WEB])
        self.assertNotIn("SG-07", [c for c, _ in self.checks(saved)], text)

    # L17 --sg-id에 없는 SG → ERROR
    def test_L17_unknown_sg_id_is_error(self):
        code, saved, text = self.run_live(FakeEC2(good_world()), sg_id=["sg-nope"])
        self.assertEqual(code, 2, text)
        self.assertEqual(saved["errors"][0]["code"], "InvalidGroup.NotFound")

    # L18 baseline에 실제 SG ID가 없음(fixture용 그대로) → AWS를 읽기 전에 ERROR
    def test_L18_fixture_baseline_is_rejected(self):
        client, sts = FakeEC2(good_world()), FakeSTS()
        code, saved, text = self.run_live(client, baseline=HERE / "baseline.json", sts=sts)
        self.assertEqual(code, 2, text)
        self.assertIsNone(saved)
        self.assertEqual((client.calls, sts.calls), ([], 0))
        self.assertIn("baseline.live.json", text)

    # L19 기대 SG가 지워지고 새 SG로 바뀜 → PASS가 아님(db-1 UNKNOWN, 모르는 ENI UNKNOWN)
    def test_L19_replaced_sg_is_not_pass(self):
        world = good_world()
        world["security_groups"][2]["GroupId"] = "sg-db-new"
        world["enis"][3]["Groups"] = [{"GroupId": "sg-db-new"}]
        code, saved, text = self.run_live(FakeEC2(world))
        self.assertNotEqual(code, 0, text)
        self.assertIn(("SG-06", "db-1"), self.checks(saved, "UNKNOWN"))
        self.assertIn(("SG-06", "eni:eni-db"), self.checks(saved, "UNKNOWN"))

    # L20 baseline에 없는 ENI(VPC 엔드포인트 등) → 역할 추정 없이 UNKNOWN
    def test_L20_unmapped_eni_is_unknown(self):
        world = good_world()
        world["security_groups"].append(sg("sg-vpce01", "vpce"))
        world["enis"].append(eni("eni-vpce", "sg-vpce01", desc="VPC Endpoint Interface"))
        code, saved, text = self.run_live(FakeEC2(world))
        self.assertEqual(code, 3, text)
        self.assertIn(("SG-06", "eni:eni-vpce"), self.checks(saved, "UNKNOWN"))

    # L20-b NAT Gateway ENI(SG 없음, 11/16 실제 VPC에 있음) → 판정에 영향 없음(PASS 11 그대로)
    def test_L20b_nat_gateway_eni_without_sg_is_ignored(self):
        world = good_world()
        world["enis"].append(eni("eni-nat", desc="Interface for NAT Gateway nat-fake"))
        code, saved, text = self.run_live(FakeEC2(world))
        self.assertEqual(code, 0, text)
        self.assertEqual(saved["counts"]["PASS"], 11)

    # L21 서버에 붙지 않은(분리된) ENI만 web SG를 가짐 → PASS 아님. web-1은 '분리된 ENI' 이유로 UNKNOWN (구민철 리뷰 질문 1)
    def test_L21_detached_eni_is_not_a_server(self):
        world = good_world()
        world["enis"][2]["Status"] = "available"
        code, saved, text = self.run_live(FakeEC2(world))
        self.assertEqual(code, 3, text)
        detached = [f for f in saved["findings"] if "분리된 ENI" in f["reason"]]
        self.assertEqual(len(detached), 1)
        self.assertEqual(detached[0]["asset_id"], "web-1")
        self.assertIn("eni-web", detached[0]["evidence"])
        self.assertFalse(any(f["asset_id"] == "web-1" and "수집 결과가 없어" in f["reason"] for f in saved["findings"]))
        self.assertFalse(any(f["asset_id"] == "web-1" and f["verdict"] == "PASS" for f in saved["findings"]))
        self.assertFalse(any(f["sg_id"] == WEB and "연결된 자산 없음" == f["actual"] for f in saved["findings"]))

    # L21-b 연결된 web ENI + 분리된 web ENI → web-1 규칙은 그대로 판정, 분리된 것만 UNKNOWN
    def test_L21b_detached_extra_eni_with_live_server(self):
        world = good_world()
        world["enis"].append(eni("eni-web-old", WEB, status="available"))
        code, saved, text = self.run_live(FakeEC2(world))
        self.assertEqual(code, 3, text)
        self.assertEqual(saved["counts"]["PASS"], 11)
        self.assertEqual([f["evidence"] for f in saved["findings"] if f["verdict"] == "UNKNOWN"], ["eni: eni-web-old"])

    # L21-c ENI 상태 값이 없음 → 연결됐다고 가정하지 않음(UNKNOWN)
    def test_L21c_missing_status_is_not_in_use(self):
        world = good_world()
        del world["enis"][3]["Status"]
        code, saved, text = self.run_live(FakeEC2(world))
        self.assertEqual(code, 3, text)
        self.assertTrue(any("분리된 ENI(상태 없음)" in f["actual"] for f in saved["findings"]))

    # L22 web 서버 2대 중 1대에만 22번 공개 SG → FAIL 근거에 그 ENI만 (구민철 리뷰 제안 2)
    def test_L22_eni_id_in_evidence(self):
        world = good_world()
        world["security_groups"].append(sg("sg-extra01", "anything", [cidr(22)]))
        world["enis"].append(eni("eni-web2", WEB, "sg-extra01"))
        code, saved, text = self.run_live(FakeEC2(world))
        self.assertEqual(code, 1, text)
        fail = [f for f in saved["findings"] if f["verdict"] == "FAIL"]
        self.assertEqual(len(fail), 1)
        self.assertTrue(fail[0]["evidence"].endswith("| eni: eni-web2"), fail[0]["evidence"])
        web_pass = [f for f in saved["findings"] if f["sg_id"] == WEB and f["verdict"] == "PASS"]
        self.assertTrue(web_pass and all(f["evidence"].endswith("| eni: eni-web, eni-web2") for f in web_pass))
        alb = [f for f in saved["findings"] if f["asset_id"] == "alb"]
        self.assertTrue(all(f["evidence"].endswith("| eni: eni-alb-a, eni-alb-c") for f in alb))

    # L11-c web의 유일한 ENI에 db SG도 붙음 → UNKNOWN 2건, 이유가 각각 맞음 (구민철 리뷰 제안 3)
    def test_L11c_ambiguous_only_eni_reason(self):
        world = good_world()
        world["enis"][2]["Groups"].append({"GroupId": DB})
        code, saved, text = self.run_live(FakeEC2(world))
        self.assertEqual(code, 3, text)
        unknown = [f for f in saved["findings"] if f["verdict"] == "UNKNOWN"]
        self.assertEqual(len(unknown), 2, unknown)
        self.assertTrue(any("역할 미확정" in f["reason"] for f in unknown))
        web = [f for f in unknown if f["asset_id"] == "web-1"]
        self.assertEqual(len(web), 1)
        self.assertIn("매핑에서 제외", web[0]["reason"])
        self.assertFalse(any("수집 결과가 없어" in f["reason"] for f in unknown))

    # 예상 못 한 응답 모양 → Traceback 없이 ERROR
    def test_unexpected_response_shape_is_error(self):
        world = good_world()
        world["enis"] = [{"NoGroupsHere": True, "Groups": [{"NoId": 1}]}]
        code, saved, text = self.run_live(FakeEC2(world))
        self.assertEqual(code, 2, text)
        self.assertNotIn("Traceback", text)


class CliTests(unittest.TestCase):
    """명세 5.1: --region·--profile·--baseline·--output-dir 필수, --vpc-id와 --sg-id 중 하나만."""

    base = ["live", "--region", "ap-northeast-2", "--profile", "default",
            "--baseline", "b.json", "--output-dir", "out"]

    def parse_exit(self, argv):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as cm:
            na.main(argv)
        return cm.exception.code

    def test_missing_profile(self):
        argv = [a for a in self.base if a not in ("--profile", "default")] + ["--vpc-id", VPC]
        self.assertEqual(self.parse_exit(argv), 2)

    def test_missing_region(self):
        argv = [a for a in self.base if a not in ("--region", "ap-northeast-2")] + ["--vpc-id", VPC]
        self.assertEqual(self.parse_exit(argv), 2)

    def test_scope_required(self):
        self.assertEqual(self.parse_exit(self.base), 2)

    def test_vpc_and_sg_together_rejected(self):
        self.assertEqual(self.parse_exit(self.base + ["--vpc-id", VPC, "--sg-id", WEB]), 2)


if __name__ == "__main__":
    unittest.main()
