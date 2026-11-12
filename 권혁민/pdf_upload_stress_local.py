"""Haven 로컬(127.0.0.1:8000) PDF 파서 업로드 부하 시험.

요청을 일정 속도로 제한하지 않고 동시 전송한다. 사전 로그인 및
응답코드/지연/기본 건강검진 요청을 기록한다. 테스트 전용 DB에서만 실행.
"""
from __future__ import annotations

import argparse
import csv
import getpass
import json
import statistics
import threading
import time
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import requests

ORIGIN = "http://127.0.0.1:8000"  # 외부 사이트로 보내지 않도록 고정


def pct(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    i = (len(ordered) - 1) * p / 100.0
    lo = int(i)
    hi = min(lo + 1, len(ordered) - 1)
    return round(ordered[lo] + (ordered[hi] - ordered[lo]) * (i - lo), 2)


def login(username: str, password: str) -> requests.Session:
    session = requests.Session()
    session.trust_env = False  # 환경 프록시를 거치지 않는 로컬 전용 시험
    r = session.get(ORIGIN + "/accounts/login/", timeout=10, allow_redirects=False)
    if r.status_code != 200:
        raise RuntimeError(f"로그인 화면 접근 오류: HTTP {r.status_code}")
    csrf = session.cookies.get("csrftoken")
    if not csrf:
        raise RuntimeError("로그인 CSRF 쿠키가 없습니다")
    r = session.post(
        ORIGIN + "/accounts/login/",
        data={"username": username, "password": password, "csrfmiddlewaretoken": csrf},
        headers={"Origin": ORIGIN, "X-CSRFToken": csrf},
        allow_redirects=False,
        timeout=10,
    )
    if r.status_code != 302 or not session.cookies.get("sessionid"):
        raise RuntimeError(f"로그인 실패: HTTP {r.status_code}, 세션 없음 여부={not bool(session.cookies.get('sessionid'))}")
    return session


def upload_batch(worker_id: int, amount: int, barrier: threading.Barrier,
                 session: requests.Session, data: bytes, post_id: int,
                 request_timeout: float, run_id: str) -> list[dict]:
    rows = []
    barrier.wait(timeout=20)
    for index in range(amount):
        request_id = str(uuid.uuid4())
        csrf = session.cookies.get("csrftoken", "")
        begin = time.perf_counter()
        try:
            response = session.post(
                f"{ORIGIN}/posts/{post_id}/attachments/",
                files={"attachment": ("pdf_load_test.pdf", data, "application/pdf")},
                headers={
                    "Origin": ORIGIN,
                    "X-CSRFToken": csrf,
                    "X-Haven-Request-ID": request_id,
                    "X-Haven-Run-ID": run_id,
                },
                allow_redirects=False,
                timeout=(3, request_timeout),
            )
            status = response.status_code
            error = ""
            response.close()
        except requests.RequestException as ex:
            status = "ERROR"
            error = type(ex).__name__
        rows.append({
            "worker": worker_id, "index": index + 1, "request_id": request_id,
            "status": status, "elapsed_ms": round((time.perf_counter() - begin) * 1000, 2),
            "error_type": error,
        })
    return rows


def health_probe(stop: threading.Event, session: requests.Session, samples: list[dict]):
    while not stop.is_set():
        begin = time.perf_counter()
        try:
            r = session.get(ORIGIN + "/posts/", allow_redirects=False, timeout=(2, 5))
            status = r.status_code
            r.close()
            error = ""
        except requests.RequestException as ex:
            status = "ERROR"
            error = type(ex).__name__
        samples.append({
            "status": status,
            "elapsed_ms": round((time.perf_counter() - begin) * 1000, 2),
            "error_type": error,
        })
        stop.wait(0.5)


def main():
    p = argparse.ArgumentParser(description="Haven 로컬 PDF 업로드 동시 부하 시험")
    p.add_argument("--file", default="fixtures/pdf_perf_complex.pdf", help="로컬 PDF 파일 경로")
    p.add_argument("--post-id", type=int, default=1)
    p.add_argument("--username", default="member_a")
    p.add_argument("--count", type=int, default=200, help="업로드 시도 총 횟수 (기본 200)")
    p.add_argument("--concurrency", type=int, default=8, help="동시 작업자 수 (기본 8)")
    p.add_argument("--request-timeout", type=float, default=15)
    p.add_argument("--output", default="output_pdf_stress_01")
    a = p.parse_args()
    if not 1 <= a.count <= 5000 or not 1 <= a.concurrency <= 32 or a.concurrency > a.count:
        p.error("--count 1~5000, --concurrency 1~32 및 count 이하로 입력하세요")
    if a.post_id < 1 or not 1 <= a.request_timeout <= 60:
        p.error("post-id는 양수, request-timeout은 1~60초여야 합니다")
    path = Path(a.file).resolve(strict=True)
    data = path.read_bytes()
    if not data.startswith(b"%PDF-") or len(data) > 2 * 1024 * 1024:
        p.error("2 MiB 이하의 PDF fixture를 사용하세요")
    out = Path(a.output)
    if out.exists():
        p.error("결과 폴더가 이미 있습니다. 다른 --output 경로를 지정하세요")
    password = getpass.getpass(f"{a.username} 시험 계정 비밀번호: ")
    if not password:
        p.error("빈 비밀번호는 허용하지 않습니다")
    print(f"로컬 대상 {ORIGIN} / PDF {path.name} ({len(data)} bytes)")
    print(f"사전 로그인: {a.concurrency}개 작업 세션 + 1개 상태 확인 세션")
    sessions = [login(a.username, password) for _ in range(a.concurrency)]
    monitor_session = login(a.username, password)
    password = None
    baseline_start = time.perf_counter()
    baseline_resp = monitor_session.get(ORIGIN + "/posts/", timeout=10, allow_redirects=False)
    baseline = {"status": baseline_resp.status_code, "elapsed_ms": round((time.perf_counter() - baseline_start) * 1000, 2)}
    baseline_resp.close()
    print(f"기준 GET /posts/: HTTP {baseline['status']}, {baseline['elapsed_ms']}ms")
    print(f"부하 시작: {a.count}건, 동시 {a.concurrency}, 요청 간 대기 없음")
    barrier = threading.Barrier(a.concurrency + 1)
    stop = threading.Event()
    probes: list[dict] = []
    amounts = [a.count // a.concurrency + (1 if i < a.count % a.concurrency else 0)
               for i in range(a.concurrency)]
    run_id = str(uuid.uuid4())
    monitor = threading.Thread(target=health_probe, args=(stop, monitor_session, probes), daemon=True)
    monitor.start()
    results: list[dict] = []
    started = time.perf_counter()
    try:
        with ThreadPoolExecutor(max_workers=a.concurrency) as pool:
            futures = [pool.submit(upload_batch, i + 1, amounts[i], barrier, sessions[i],
                                   data, a.post_id, a.request_timeout, run_id)
                       for i in range(a.concurrency)]
            barrier.wait(timeout=20)
            for fut in futures:
                results.extend(fut.result())
    finally:
        elapsed = time.perf_counter() - started
        stop.set()
        monitor.join(timeout=7)
        for s in sessions:
            s.close()
        monitor_session.close()
    out.mkdir(parents=True, exist_ok=False)
    with (out / "requests.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["worker", "index", "request_id", "status", "elapsed_ms", "error_type"])
        writer.writeheader()
        writer.writerows(results)
    with (out / "health.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["status", "elapsed_ms", "error_type"])
        writer.writeheader()
        writer.writerows(probes)
    times = [r["elapsed_ms"] for r in results]
    health_times = [r["elapsed_ms"] for r in probes]
    summary = {
        "run_id": run_id,
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "target": ORIGIN,
        "count": len(results),
        "concurrency": a.concurrency,
        "pdf_file": path.name,
        "pdf_bytes": len(data),
        "wall_seconds": round(elapsed, 2),
        "requests_per_second": round(len(results) / elapsed, 2) if elapsed else None,
        "status_counts": dict(Counter(str(row["status"]) for row in results)),
        "request_latency_ms": {"p50": pct(times, 50), "p95": pct(times, 95), "p99": pct(times, 99), "max": max(times, default=None)},
        "health_baseline": baseline,
        "health_status_counts": dict(Counter(str(row["status"]) for row in probes)),
        "health_latency_ms": {"p50": pct(health_times, 50), "p95": pct(health_times, 95), "max": max(health_times, default=None)},
        "note": "403/400/413 등은 PDF 파싱 여부와 구분해 평가. 정상 업로드는 글당 3개/계정당 10 MiB로 제한됨."
    }
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"결과: {out / 'summary.json'}, requests.csv, health.csv")


if __name__ == "__main__":
    main()
