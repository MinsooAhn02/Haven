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
            self.assertEqual(saved["counts"]["PASS"], 8)


if __name__ == "__main__":
    unittest.main()
