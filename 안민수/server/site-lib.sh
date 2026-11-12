# web-setup.sh·deploy.sh가 source 하는 작은 함수들. root·AWS 없이 시험할 수 있게 따로 둔다(test-site-lib.sh).
# 이 파일은 실행하지 않고 source만 한다. 실패하면 이유를 stderr에 쓰고 0이 아닌 값을 돌려준다(종료는 부르는 쪽이 정함).

# mail_env_lines <발신 주소 또는 빈 값> <SES 리전>
#   빈 값  → HAVEN_MAIL_BACKEND=console (보내지 않음, 앱 기본값과 같음. 무엇으로 떴는지 파일에서 보이게 항상 쓴다)
#   주소   → HAVEN_MAIL_BACKEND=ses + HAVEN_MAIL_FROM + HAVEN_SES_REGION 세 줄을 "같이" 출력
#            (앱계약 1.2.2: ses인데 발신 주소가 없으면 앱이 시작하지 않아 배포가 되돌아간다)
#   형식이 이상한 주소·리전은 아무것도 출력하지 않고 실패. 공백·줄바꿈·따옴표가 들어가면
#   haven.env에 다른 설정 줄을 끼워 넣을 수 있으므로 거부한다.
mail_env_lines() {
  local from=${1-} region=${2-}
  if [[ -z $from ]]; then
    printf 'HAVEN_MAIL_BACKEND=console\n'
    return 0
  fi
  if [[ ! $from =~ ^[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}$ ]]; then
    echo "FAIL: MAIL_FROM is not a plain e-mail address" >&2
    return 1
  fi
  if [[ ! $region =~ ^[a-z]{2}(-[a-z]+)+-[0-9]$ ]]; then
    echo "FAIL: SES region is not a region name: '$region'" >&2
    return 1
  fi
  printf 'HAVEN_MAIL_BACKEND=ses\nHAVEN_MAIL_FROM=%s\nHAVEN_SES_REGION=%s\n' "$from" "$region"
}

# keep_or_die <이름> <새 값> <site.conf 경로>
#   web-setup.sh를 다시 돌릴 때 예전 site.conf에 값이 있던 항목을 빠뜨려 빈 값으로 덮는 실수를 막는다.
#   (예: CSRF_TRUSTED_ORIGINS를 빼먹으면 다음 배포에서 DJANGO_HTTPS=0이 되어 쿠키 Secure가 빠진다)
#   값을 바꾸는 것은 허용. 일부러 비우려면 ALLOW_CLEAR=1.
keep_or_die() {
  local name=$1 new=${2-} conf=$3 old=""
  [[ -f $conf ]] && old=$(sed -n "s/^${name}=//p" "$conf" | tail -n 1 | tr -d '\r')
  if [[ -n $old && -z $new && ${ALLOW_CLEAR:-} != 1 ]]; then
    echo "FAIL: $name was '$old' in $conf but is empty now. Pass it again (or ALLOW_CLEAR=1 to clear on purpose)" >&2
    return 1
  fi
  return 0
}
