#!/usr/bin/env bash
# web-1에서 root로 실행: DB_HOST=<db-1 사설 IP> ALLOWED_HOSTS=<도메인 또는 ALB 이름[,..]> bash web-setup.sh
# Python venv, 비root 실행 계정 haven, Gunicorn(systemd, 127.0.0.1:8000), Nginx(:80) 준비.
# 앱 코드는 넣지 않는다(deploy.sh가 함). 여러 번 실행해도 같은 결과.
source "$(dirname "$0")/common.sh"

need DB_HOST
need ALLOWED_HOSTS
REPO_URL="${REPO_URL:-git@github.com:MinsooAhn02/Haven.git}"
APP_SUBDIR="${APP_SUBDIR:-신요찬/app}"
STATIC_SUBDIR="${STATIC_SUBDIR:-노푸른/static}"
HEALTH_HOST="${ALLOWED_HOSTS%%,*}"   # ALB 상태 검사는 Host가 서버 IP라 Django가 400을 낸다. 첫 허용 Host로 바꿔 넘긴다.
[[ $HEALTH_HOST =~ ^[A-Za-z0-9.-]+$ ]] || die "first ALLOWED_HOSTS entry is not a host name: $HEALTH_HOST"
H=/srv/haven

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

# deploy.sh가 읽는 비밀 아닌 설정. 비밀값은 deploy.sh가 배포 때 SSM에서 읽어 haven.env에 쓴다.
cat > /etc/haven/site.conf <<EOF
DB_HOST=$DB_HOST
ALLOWED_HOSTS=$ALLOWED_HOSTS
REPO_URL=$REPO_URL
APP_SUBDIR=$APP_SUBDIR
PARAM_PREFIX=$PARAM_PREFIX
CSRF_TRUSTED_ORIGINS=${CSRF_TRUSTED_ORIGINS:-}
AWS_REGION=$AWS_REGION
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
cat > /etc/nginx/sites-available/haven <<EOF
server {
    listen 80 default_server;
    server_name _;
    server_tokens off;
    client_max_body_size 16k;

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
ln -sfn /etc/nginx/sites-available/haven /etc/nginx/sites-enabled/haven
rm -f /etc/nginx/sites-enabled/default
nginx -t -q || die "nginx config test failed"
systemctl enable --now nginx >/dev/null
systemctl reload nginx

echo "OK  web-setup: next, add this public key to GitHub > Settings > Deploy keys (read-only), then run deploy.sh <commit>"
cat "$H/.ssh/id_ed25519.pub"
