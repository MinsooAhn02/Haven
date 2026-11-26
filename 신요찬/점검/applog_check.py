"""Haven 앱 요청 로그 점검 (앱계약 7장). web-1에서 root로 실행, 결과는 숫자 요약만 출력한다.

사용: python3 applog_check.py 2026-11-23 2026-11-27 [로그 폴더] [--dump 파일]
  날짜는 KST, 둘 다 포함. 로그 폴더 기본값 /var/log/haven (app.log, app.log.1, app.log.N.gz)
  --dump 파일: 범위 안 요청 로그 JSON만 한 줄씩 저장한다(rsyslog 머리글·서버 이름은 빼고).
원본 줄 내용은 화면에 출력하지 않는다(위반은 파일 이름·줄 번호·규칙만).

app.log에는 앱 JSON 요청 로그 말고도 gunicorn 접근 로그(--access-logfile -, 요청 줄·쿼리·Referer·User-Agent,
/healthz 포함)와 gunicorn 자체 메시지가 같이 들어온다. 접근 로그 줄은 따로 세고 쿼리·Referer에 비밀값 단어가
있는지 본다. Nginx 접근 로그(/var/log/nginx)는 이 스크립트 범위 밖이다.
"""
import glob
import gzip
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))
FIELDS = ["ts", "request_id", "trace_id", "client_request_id", "run_id", "method", "path", "view",
          "action", "actor_id", "resource_id", "status", "result", "elapsed_ms"]
SPECIAL_ACTIONS = {"login_success", "login_failure", "login_limited", "logout", "csrf_failure",
                   "body_too_large", "bad_content_length"}
RE_TS = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z")
RE_REQ = re.compile(r"[0-9a-f]{32}")
RE_TRACE = re.compile(r"1-[0-9a-f]{8}-[0-9a-f]{24}")
RE_CLIENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
RE_VIEW = re.compile(r"(?:[a-z_]+:)?[a-z_]+")  # 최상위 이름(home)은 앱 이름 없이 온다
RE_RES = re.compile(r"(post|user):\d+(/(attachment|share):\d+)?")
RE_LONG_TOKEN = re.compile(r"[A-Za-z0-9]{32,}")
SECRET_WORDS = re.compile(r"password|passwd|csrfmiddlewaretoken|csrftoken|sessionid|cookie|secret", re.I)
RE_IPV4 = re.compile(r"(?<![\d.])(\d{1,3}\.){3}\d{1,3}(?![\d.])")
# 쿼리에 비밀값을 '파라미터 이름'으로 보낸 경우(예: GET 폼으로 password= 전송). 값 속 단어(공격·시험 입력)는 참고로만 센다
RE_SECRET_PARAM = re.compile(r"(?:^|&)[^=&]*(?:password|passwd|csrfmiddlewaretoken|csrftoken|sessionid|secret)[^=&]*=", re.I)
# gunicorn 기본 접근 로그: h l u [t] "r" s b "f" "a"
RE_GACCESS = re.compile(r'\[(\d\d/[A-Za-z]{3}/\d{4}:\d\d:\d\d:\d\d [+-]\d{4})\] "([A-Z]+) ([^ "]*)[^"]*" (\d{3}) \S+ "([^"]*)"')


def expected_result(status):
    if status >= 500:
        return "error"
    if status == 400:
        return "invalid"
    if status in (401, 403, 404, 405, 413, 429):
        return "denied"
    if 200 <= status < 400:
        return "ok"
    return None  # 계약 표에 없는 코드


def open_any(path):
    return gzip.open(path, "rt", encoding="utf-8", errors="replace") if path.endswith(".gz") else open(path, encoding="utf-8", errors="replace")


def field_problems(e):
    p = []
    keys = list(e.keys())
    if set(keys) != set(FIELDS):
        miss = [k for k in FIELDS if k not in e]
        extra = [k for k in keys if k not in FIELDS]
        if miss:
            p.append("필드 빠짐:" + ",".join(miss))
        if extra:
            p.append("계약 밖 필드:" + ",".join(extra))
    g = e.get
    if not (isinstance(g("ts"), str) and RE_TS.fullmatch(g("ts"))):
        p.append("ts 형식")
    if not (isinstance(g("request_id"), str) and RE_REQ.fullmatch(g("request_id"))):
        p.append("request_id 형식")
    if g("trace_id") is not None and not (isinstance(g("trace_id"), str) and RE_TRACE.fullmatch(g("trace_id"))):
        p.append("trace_id 형식")
    for k in ("client_request_id", "run_id"):
        v = g(k)
        if v is not None and not (isinstance(v, str) and RE_CLIENT.fullmatch(v)):
            p.append(k + " 형식")
    if not (isinstance(g("method"), str) and g("method").isupper() and g("method").isalpha()):
        p.append("method 형식")
    path = g("path")
    if not (isinstance(path, str) and path.startswith("/") and len(path) <= 200):
        p.append("path 형식")
    elif "?" in path:
        p.append("path에 쿼리 문자열")
    elif any(RE_LONG_TOKEN.fullmatch(seg) for seg in path.split("/") if seg):
        p.append("path에 토큰 모양 조각")
    if g("view") is not None and not (isinstance(g("view"), str) and RE_VIEW.fullmatch(g("view"))):
        p.append("view 형식")
    a = g("action")
    if not (a is None or a in SPECIAL_ACTIONS or a == g("view")):
        p.append("action 값")
    if g("actor_id") is not None and not (isinstance(g("actor_id"), int) and not isinstance(g("actor_id"), bool)):
        p.append("actor_id 형식")
    if g("resource_id") is not None and not (isinstance(g("resource_id"), str) and RE_RES.fullmatch(g("resource_id"))):
        p.append("resource_id 형식")
    st = g("status")
    if not (isinstance(st, int) and 100 <= st <= 599):
        p.append("status 형식")
    else:
        exp = expected_result(st)
        if exp is None:
            p.append(f"표에 없는 status {st}")
        elif g("result") != exp:
            p.append("result 규칙 불일치")
    if not isinstance(g("elapsed_ms"), (int, float)) or isinstance(g("elapsed_ms"), bool):
        p.append("elapsed_ms 형식")
    for k, v in e.items():
        if k == "path" or not isinstance(v, str):
            continue
        if SECRET_WORDS.search(v):
            p.append(f"{k}에 비밀값 단어")
        if RE_IPV4.search(v):
            p.append(f"{k}에 IP 모양")
    if isinstance(path, str) and RE_IPV4.search(path):
        p.append("path에 IP 모양")
    return p


def main():
    args = sys.argv[1:]
    dump_path = None
    if "--dump" in args:
        i = args.index("--dump")
        if i + 1 >= len(args):
            sys.exit("--dump 뒤에 파일 이름이 필요하다")
        dump_path = args[i + 1]
        del args[i:i + 2]
    if len(args) < 2:
        sys.exit(__doc__)
    try:
        d0 = datetime.strptime(args[0], "%Y-%m-%d").replace(tzinfo=KST)
        d1 = datetime.strptime(args[1], "%Y-%m-%d").replace(tzinfo=KST) + timedelta(days=1)
    except ValueError:
        sys.exit("날짜는 2026-11-23 모양으로 넣는다\n" + __doc__)
    folder = args[2] if len(args) > 2 else "/var/log/haven"
    dump = open(dump_path, "w", encoding="utf-8") if dump_path else None
    files = sorted(glob.glob(os.path.join(folder, "app.log*")))
    if not files:
        sys.exit(f"로그 파일 없음: {folder}/app.log*")

    total = other = bad_json = in_range = 0
    per_day, by_result, by_action, by_status = Counter(), Counter(), Counter(), Counter()
    probs, prob_where = Counter(), {}
    healthz = 0
    first = last = None
    acc = Counter()  # gunicorn 접근 로그 줄
    acc_where = {}
    for f in files:
        with open_any(f) as fh:
            for n, line in enumerate(fh, 1):
                total += 1
                i = line.find('{"ts":')
                if i > 0 and not line[:i].rstrip().endswith(":"):
                    i = -1  # 접근 로그 요청 줄 안에 들어 있는 경우 등: JSON 로그가 아님
                if i < 0:
                    m = RE_GACCESS.search(line)
                    if not m:
                        other += 1
                        continue
                    try:
                        at = datetime.strptime(m.group(1), "%d/%b/%Y:%H:%M:%S %z")
                    except ValueError:
                        other += 1
                        continue
                    if not (d0 <= at < d1):
                        continue
                    acc["줄"] += 1
                    target, referer = m.group(3), m.group(5)
                    if target.split("?", 1)[0] == "/healthz":
                        acc["healthz"] += 1
                    if "?" in target:
                        acc["쿼리 있음"] += 1
                    q = target.split("?", 1)[1] if "?" in target else ""
                    rq = referer.split("?", 1)[1] if "?" in referer else ""
                    if RE_SECRET_PARAM.search(q) or RE_SECRET_PARAM.search(rq):
                        acc["비밀값 파라미터"] += 1
                        acc_where.setdefault("비밀값 파라미터", f"{os.path.basename(f)}:{n}")
                    elif SECRET_WORDS.search(q) or SECRET_WORDS.search(rq):
                        acc["값 속 비밀값 단어"] += 1
                        acc_where.setdefault("값 속 비밀값 단어", f"{os.path.basename(f)}:{n}")
                    if RE_LONG_TOKEN.search(q) or RE_LONG_TOKEN.search(rq):
                        acc["긴 토큰 모양"] += 1
                        acc_where.setdefault("긴 토큰 모양", f"{os.path.basename(f)}:{n}")
                    continue
                try:
                    e = json.loads(line[i:])
                except ValueError:
                    bad_json += 1
                    prob_where.setdefault("JSON 깨짐", f"{os.path.basename(f)}:{n}")
                    continue
                if not isinstance(e, dict):
                    bad_json += 1
                    continue
                try:
                    t = datetime.strptime(e.get("ts", ""), "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
                except (TypeError, ValueError):
                    probs["ts 형식"] += 1
                    prob_where.setdefault("ts 형식", f"{os.path.basename(f)}:{n}")
                    continue
                if not (d0 <= t < d1):
                    continue
                in_range += 1
                if dump:
                    dump.write(line[i:].rstrip("\n") + "\n")
                k = t.astimezone(KST)
                per_day[k.strftime("%m-%d")] += 1
                first = k if first is None or k < first else first
                last = k if last is None or k > last else last
                by_result[e.get("result")] += 1
                by_action[e.get("action")] += 1
                by_status[e.get("status")] += 1
                if e.get("path") == "/healthz":
                    healthz += 1
                for p in field_problems(e):
                    probs[p] += 1
                    prob_where.setdefault(p, f"{os.path.basename(f)}:{n}")

    if dump:
        dump.close()
    print(f"점검 범위(KST): {args[0]} 00:00 ~ {args[1]} 24:00")
    print(f"읽은 파일: {len(files)}개 ({', '.join(os.path.basename(f) for f in files)})")
    print(f"전체 줄 {total} / 앱 요청 로그(범위 안) {in_range} / gunicorn 접근 로그(범위 안) {acc['줄']} / 그 밖의 줄 {other} / JSON 깨짐 {bad_json}")
    if first:
        print(f"범위 안 첫 기록 {first:%m-%d %H:%M} · 마지막 기록 {last:%m-%d %H:%M} (KST)")
    print("날짜별(KST):", ", ".join(f"{d} {c}" for d, c in sorted(per_day.items())) or "없음")
    print("result별:", ", ".join(f"{k} {v}" for k, v in by_result.most_common()))
    print("status별:", ", ".join(f"{k} {v}" for k, v in sorted(by_status.items(), key=lambda x: str(x[0]))))
    print("action 상위 15:", ", ".join(f"{k} {v}" for k, v in by_action.most_common(15)))
    print(f"/healthz 줄: 앱 요청 로그 {healthz} (0이어야 함) · gunicorn 접근 로그 {acc['healthz']} (ALB 상태 검사, 있는 게 정상)")
    print(f"gunicorn 접근 로그: 쿼리 문자열 있는 줄 {acc['쿼리 있음']}")
    print("── 규칙 점검 ──")
    checks = [
        ("필드 14개가 계약과 정확히 같음", lambda p: p.startswith("필드 빠짐") or p.startswith("계약 밖 필드")),
        ("값 형식(ts·request_id·trace_id·run_id·method·path·view·action·actor_id·resource_id·status·elapsed_ms)",
         lambda p: p.endswith("형식") or p == "action 값"),
        ("result 규칙(2xx·3xx ok / 400 invalid / 401·403·404·405·413·429 denied / 5xx error)",
         lambda p: p == "result 규칙 불일치" or p.startswith("표에 없는 status")),
        ("쿼리 문자열·토큰 모양 조각 없음", lambda p: p.startswith("path에 쿼리") or p.startswith("path에 토큰")),
        ("비밀번호·토큰·쿠키 단어 없음", lambda p: "비밀값 단어" in p),
        ("IP 모양 없음", lambda p: "IP 모양" in p),
    ]
    all_ok = healthz == 0 and bad_json == 0 and in_range > 0
    for name, sel in checks:
        hit = {p: c for p, c in probs.items() if sel(p)}
        if hit:
            all_ok = False
            print(f"[확인 필요] {name}")
            for p, c in hit.items():
                print(f"    {p}: {c}건 (처음 위치 {prob_where.get(p)})")
        else:
            print(f"[통과] {name}")
    if bad_json:
        print(f"[확인 필요] JSON 깨진 줄 {bad_json}건 (처음 위치 {prob_where.get('JSON 깨짐')})")
    if in_range == 0:
        print("[확인 필요] 범위 안 요청 로그가 0건이다(날짜·파일 확인)")
    print("── gunicorn 접근 로그 (앱 JSON 아님) ──")
    if acc["비밀값 파라미터"]:
        all_ok = False
        print(f"[확인 필요] 쿼리·Referer에 비밀값 이름의 파라미터(password= 등): {acc['비밀값 파라미터']}건 (처음 위치 {acc_where['비밀값 파라미터']})")
    else:
        print("[통과] 쿼리·Referer에 비밀값 이름의 파라미터(password=·csrfmiddlewaretoken=·sessionid= 등) 없음")
    if acc["값 속 비밀값 단어"]:
        print(f"[참고] 쿼리·Referer 값 안에 비밀값 단어: {acc['값 속 비밀값 단어']}건 (처음 위치 {acc_where['값 속 비밀값 단어']}) - 공격·시험 입력인지 확인")
    if acc["긴 토큰 모양"]:
        print(f"[참고] 쿼리·Referer에 32자 이상 영문·숫자 조각: {acc['긴 토큰 모양']}건 (처음 위치 {acc_where['긴 토큰 모양']}) - 시험 입력인지 확인")
    print("[참고] 접근 로그의 첫 칸은 Nginx 주소(127.0.0.1)라 사용자 IP가 아니다. Nginx 접근 로그는 이 점검 범위 밖")
    print("판정:", "통과" if all_ok else "확인 필요")


if __name__ == "__main__":
    main()
