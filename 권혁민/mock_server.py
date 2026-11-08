#!/usr/bin/env python3
"""LOCAL-ONLY synthetic fixture app and artificial WAF/app event logs.

This is not Django and not AWS WAF. Use only to validate request_verify CLI.
"""
import argparse
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
import json
from pathlib import Path
from urllib.parse import urlsplit


def now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class FixtureHandler(BaseHTTPRequestHandler):
    waf_log: Path
    app_log: Path

    def log_message(self, _format, *_args):
        pass

    def log_line(self, path: Path, item: dict):
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(item, ensure_ascii=False) + "\n")

    def handle(self):
        # Keep the built-in HTTPHandler's socket lifecycle unchanged.
        super().handle()

    def process(self):
        req_id = self.headers.get("X-Haven-Request-ID")
        route = urlsplit(self.path).path
        is_blocked = route == "/mock-waf-block"
        content_length = int(self.headers.get("Content-Length", "0"))
        csrf_token = self.headers.get("X-CSRFToken")
        cookies = self.headers.get("Cookie", "")
        valid_csrf = csrf_token == "fixture-token" and "csrftoken=fixture-token" in cookies
        status = 403 if is_blocked else (
            200 if route == "/healthz"
            else (302 if valid_csrf else 403) if route == "/accounts/login/" and self.command == "POST"
            else 200 if route == "/accounts/login/"
            else (200 if "sessionid=fixture-session" in cookies else 302) if route.startswith("/posts/") and self.command == "GET"
            else (413 if content_length > 8192 else (302 if valid_csrf else 403))
                 if route == "/posts/new/" and self.command == "POST"
            else 404
        )
        self.log_line(self.waf_log, {
            "request_id": req_id, "run_id": self.headers.get("X-Haven-Run-ID"), "timestamp_utc": now(),
            "action": "BLOCK" if is_blocked else "ALLOW",
            "rule_id": "MOCK_BLOCK" if is_blocked else "MOCK_ALLOW",
            "synthetic_fixture": True,
        })
        if not is_blocked:
            self.log_line(self.app_log, {
                "request_id": req_id, "run_id": self.headers.get("X-Haven-Run-ID"), "timestamp_utc": now(),
                "http_status": status, "observed": True, "synthetic_fixture": True,
            })
        body = b"fixture-only response"
        if route == "/accounts/login/":
            body = b'<html><form><input type="hidden" name="csrfmiddlewaretoken" value="fixture-token"></form></html>'
        self.send_response(status)
        if status == 302:
            self.send_header("Location", "/posts/" if route == "/accounts/login/" or route == "/posts/new/" else "/accounts/login/?next=/posts/")
        if route == "/accounts/login/" and self.command == "GET":
            self.send_header("Set-Cookie", "csrftoken=fixture-token; Path=/; SameSite=Lax")
        if route == "/accounts/login/" and self.command == "POST" and status == 302:
            self.send_header("Set-Cookie", "sessionid=fixture-session; Path=/; HttpOnly; SameSite=Lax")
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_GET(self):
        self.process()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length > 2_162_688:
            self.send_error(413)
            return
        if length:
            self.rfile.read(length)
        self.process()


def main():
    parser = argparse.ArgumentParser(description="Haven CLI 전용 로컬 가상 응답 서버 (실제 Django/WAF 아님)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--waf-log", type=Path, default=Path("mock_waf.jsonl"))
    parser.add_argument("--app-log", type=Path, default=Path("mock_app.jsonl"))
    args = parser.parse_args()
    if args.host != "127.0.0.1":
        parser.error("mock server는 127.0.0.1에만 바인딩합니다")
    FixtureHandler.waf_log = args.waf_log
    FixtureHandler.app_log = args.app_log
    server = ThreadingHTTPServer((args.host, args.port), FixtureHandler)
    print(f"가상 서버 http://127.0.0.1:{args.port} 실행 (Ctrl+C 종료). 로그는 가상 WAF/앱 이벤트입니다.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
