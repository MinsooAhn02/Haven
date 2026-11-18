#!/usr/bin/env bash
# web-1에서 root로 실행: DB_HOST=<db-1 사설 IP> ALLOWED_HOSTS=<도메인 또는 ALB 이름[,..]> bash web-setup.sh
#   선택: CSRF_TRUSTED_ORIGINS=https://<도메인>  MAIL_FROM=<SES 인증 발신 주소>(시험 메일, 비우면 보내지 않음)
#   다시 실행할 때 기존 site.conf에 있던 CSRF_TRUSTED_ORIGINS·MAIL_FROM을 빠뜨리면 멈춘다(지우려면 ALLOW_CLEAR=1).
# Python venv, 비root 실행 계정 haven, Gunicorn(systemd, 127.0.0.1:8000), Nginx(:80) 준비.
# 앱 코드는 넣지 않는다(deploy.sh가 함). 여러 번 실행해도 같은 결과.
source "$(dirname "$0")/common.sh"
source "$(dirname "$0")/site-lib.sh"

need DB_HOST
need ALLOWED_HOSTS
REPO_URL="${REPO_URL:-git@github.com:MinsooAhn02/Haven.git}"
APP_SUBDIR="${APP_SUBDIR:-신요찬/app}"
STATIC_SUBDIR="${STATIC_SUBDIR:-노푸른/static}"
HEALTH_HOST="${ALLOWED_HOSTS%%,*}"   # ALB 상태 검사는 Host가 서버 IP라 Django가 400을 낸다. 첫 허용 Host로 바꿔 넘긴다.
[[ $HEALTH_HOST =~ ^[A-Za-z0-9.-]+$ ]] || die "first ALLOWED_HOSTS entry is not a host name: $HEALTH_HOST"
H=/srv/haven
MAIL_FROM="${MAIL_FROM:-}"
# 아무것도 설치·변경하기 전에 입력부터 확인한다.
mail_env_lines "$MAIL_FROM" "$AWS_REGION" >/dev/null || die "MAIL_FROM is not a valid address: $MAIL_FROM"
keep_or_die CSRF_TRUSTED_ORIGINS "${CSRF_TRUSTED_ORIGINS:-}" /etc/haven/site.conf || die "stopped before changing anything"
keep_or_die MAIL_FROM "$MAIL_FROM" /etc/haven/site.conf || die "stopped before changing anything"

apt-get update -q
DEBIAN_FRONTEND=noninteractive apt-get install -yq python3-venv nginx git curl
command -v aws >/dev/null || snap install aws-cli --classic

id haven >/dev/null 2>&1 || useradd --system --home-dir "$H" --shell /usr/sbin/nologin haven
install -d -o haven -g haven -m 755 "$H" "$H/releases"   # 755: nginx(www-data)가 static을 읽어야 함
install -d -o haven -g haven -m 700 "$H/.ssh"
# 첨부 원본(3회차, 앱계약 HAVEN_UPLOAD_DIR). Nginx는 직접 제공하지 않는다: 다운로드는 앱이 권한 확인 후.
install -d -o haven -g haven -m 750 "$H/uploads"
install -d -o root -g haven -m 750 /etc/haven
[[ -x $H/venv/bin/python ]] || runuser -u haven -- python3 -m venv "$H/venv"

# 읽기 전용 deploy key. 개인키는 이 서버 밖으로 나가지 않는다. 공개키만 GitHub에 등록.
[[ -f $H/.ssh/id_ed25519 ]] || runuser -u haven -- ssh-keygen -q -t ed25519 -N '' \
  -C "haven web-1 deploy key (read-only)" -f "$H/.ssh/id_ed25519"
# GitHub 공식 호스트 키를 고정한다(처음 접속 때 가짜 서버를 믿지 않게). 틀리면 git이 접속을 거부한다.
echo 'github.com ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl' \
  | install -o haven -g haven -m 644 /dev/stdin "$H/.ssh/known_hosts"
# sg-web outbound는 80·443만 연다(민성 설계 4.2). GitHub SSH를 443(ssh.github.com)으로 돌린다.
# 22로 가면 연결 시간 초과. 호스트 키는 같아서 HostKeyAlias로 위 known_hosts 줄을 그대로 쓴다.
printf 'Host github.com\n  HostName ssh.github.com\n  Port 443\n  HostKeyAlias github.com\n' \
  | install -o haven -g haven -m 600 /dev/stdin "$H/.ssh/config"

# deploy.sh가 읽는 비밀 아닌 설정. 비밀값은 deploy.sh가 배포 때 SSM에서 읽어 haven.env에 쓴다.
cat > /etc/haven/site.conf <<EOF
DB_HOST=$DB_HOST
ALLOWED_HOSTS=$ALLOWED_HOSTS
REPO_URL=$REPO_URL
APP_SUBDIR=$APP_SUBDIR
PARAM_PREFIX=$PARAM_PREFIX
CSRF_TRUSTED_ORIGINS=${CSRF_TRUSTED_ORIGINS:-}
AWS_REGION=$AWS_REGION
MAIL_FROM=$MAIL_FROM
EOF
chmod 640 /etc/haven/site.conf; chgrp haven /etc/haven/site.conf

cat > /etc/systemd/system/haven.service <<EOF
[Unit]
Description=Haven Django (Gunicorn)
After=network-online.target
Wants=network-online.target

[Service]
User=haven
Group=haven
WorkingDirectory=$H/current/$APP_SUBDIR
EnvironmentFile=/etc/haven/haven.env
ExecStart=$H/venv/bin/gunicorn config.wsgi:application --bind 127.0.0.1:8000 --workers 3 --access-logfile -
Restart=on-failure
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=yes
ReadWritePaths=$H/uploads

[Install]
WantedBy=multi-user.target
EOF
# 첨부 정리(앱계약 E4): 끊긴 업로드 예약·삭제 대기·남은 임시 파일을 하루 한 번 정리. 실패가 남으면 명령이 1을 내서 journal에 남는다.
cat > /etc/systemd/system/haven-cleanup.service <<EOF
[Unit]
Description=Haven attachment cleanup
ConditionPathExists=$H/current

[Service]
Type=oneshot
User=haven
Group=haven
WorkingDirectory=$H/current/$APP_SUBDIR
EnvironmentFile=/etc/haven/haven.env
ExecStart=$H/venv/bin/python manage.py cleanup_attachments
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=yes
ReadWritePaths=$H/uploads
EOF
cat > /etc/systemd/system/haven-cleanup.timer <<EOF
[Unit]
Description=Run Haven attachment cleanup daily

[Timer]
OnCalendar=*-*-* 04:00:00
Persistent=true

[Install]
WantedBy=timers.target
EOF
systemctl daemon-reload
systemctl enable haven >/dev/null   # 시작은 첫 deploy 때
systemctl enable --now haven-cleanup.timer >/dev/null

# 본문 한도(앱계약 E3): 정확한 한도는 앱이 건다(글 8,192 / 첨부 업로드 2,162,688바이트 → 413 + 요청 로그).
# Nginx는 그보다 조금 크게 잡아 경계값 요청은 앱까지 보내고(혁민 APP-11 시험·로그 대조), 훨씬 큰 요청만 앱 앞에서 끊는다.
#
# 접근 로그 요청 식별자(조장 결정 11/13, 혁민 방안): WAF·ALB ↔ Nginx ↔ 앱 로그를 같은 요청으로 잇는다.
#   trace=  X-Amzn-Trace-Id의 Root(ALB가 붙임, WAF 로그의 같은 값과 대조)
#   rid=    앱이 돌려주는 X-Request-ID(앱 로그 request_id와 같음). Nginx가 직접 끊은 요청(큰 413·static)은 -
#   cid=/run= X-Haven-Request-ID / X-Haven-Run-ID(혁민 CLI). 클라이언트가 마음대로 넣는 값이라 앱과 같은 형식만 남기고 나머지는 -
#   client= X-Forwarded-For의 마지막 값 = ALB가 본 실제 접속 IP(앞 값들은 클라이언트가 위조할 수 있어 남기지 않음)
# 앞부분은 기본 combined 형식 그대로라 기존 조회(CloudWatch /haven/web nginx-access)는 그대로 읽힌다.
# 헤더 값의 따옴표·제어 문자는 Nginx가 \xHH로 바꿔 쓰므로 줄 바꿈 등으로 로그를 위조할 수 없다.
NGX=/etc/nginx/sites-available/haven
NGX_NEW=$(mktemp)
cat > "$NGX_NEW" <<'EOF'
map $http_x_amzn_trace_id $haven_trace {
    "~*(?:^|;)\s*Root=(?<haven_root>1-[0-9a-f]{8}-[0-9a-f]{24})\s*(?:;|$)" $haven_root;
    default "-";
}
map $http_x_haven_request_id $haven_cid {
    "~^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$" $http_x_haven_request_id;
    default "-";
}
map $http_x_haven_run_id $haven_run {
    "~^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$" $http_x_haven_run_id;
    default "-";
}
map $http_x_forwarded_for $haven_client {
    "~(?:^|,)\s*(?<haven_xff_last>[0-9A-Fa-f.:]{2,45})\s*$" $haven_xff_last;
    default "-";
}
log_format haven '$remote_addr - $remote_user [$time_local] "$request" $status $body_bytes_sent '
                 '"$http_referer" "$http_user_agent" '
                 'trace=$haven_trace rid=$upstream_http_x_request_id cid=$haven_cid run=$haven_run '
                 'client=$haven_client rt=$request_time';
EOF
cat >> "$NGX_NEW" <<EOF
server {
    listen 80 default_server;
    server_name _;
    server_tokens off;
    client_max_body_size 16k;
    access_log /var/log/nginx/access.log haven;

    location /static/ { alias $H/current/$STATIC_SUBDIR/; }

    location ~ ^/posts/[0-9]+/attachments/\$ {
        client_max_body_size 3m;
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$http_x_forwarded_proto;
    }

    location = /healthz {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $HEALTH_HOST;
    }

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$http_x_forwarded_proto;
    }
}
EOF
# test-wsl.sh 전용: 일부러 깨진 설정을 넣어 아래 되돌리기를 시험한다(운영에서는 쓰지 않음).
[[ ${NGINX_BREAK_FOR_TEST:-} == 1 ]] && echo 'haven_broken_directive_for_test on;' >> "$NGX_NEW"
# 새 설정이 nginx -t를 통과할 때만 바꾼다. 실패하면 이전 파일로 되돌려, 다음 reload·재부팅 때 Nginx가 못 뜨는 일을 막는다.
[[ -f $NGX ]] && cp -p "$NGX" "$NGX.prev"
install -m 644 "$NGX_NEW" "$NGX"; rm -f "$NGX_NEW"
ln -sfn "$NGX" /etc/nginx/sites-enabled/haven
rm -f /etc/nginx/sites-enabled/default
if ! nginx -t -q; then
  if [[ -f $NGX.prev ]]; then mv -f "$NGX.prev" "$NGX"; die "nginx config test failed (previous config restored, nginx not reloaded)"; fi
  rm -f "$NGX" /etc/nginx/sites-enabled/haven   # 처음 설치였으면 깨진 새 파일을 남기지 않는다
  die "nginx config test failed"
fi
rm -f "$NGX.prev"
systemctl enable --now nginx >/dev/null
systemctl reload nginx

echo "OK  web-setup: next, add this public key to GitHub > Settings > Deploy keys (read-only), then run deploy.sh <commit>"
cat "$H/.ssh/id_ed25519.pub"
