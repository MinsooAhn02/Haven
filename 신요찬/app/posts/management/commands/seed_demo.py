"""시험용 가상 데이터 (앱계약.md 2장, 권혁민 fixture 사전 조건).

member_a(소유자) · member_b(2회차 공유 대상) · member_c(비대상)
P1(id=1, A 소유), P2(id=2, A 소유, 삭제 시험 전용)

- DJANGO_DEBUG=1에서만 실행된다(운영 DB 보호).
- 비밀번호는 HAVEN_SEED_PASSWORD에서 읽고 출력하지 않는다.
- 빈 DB에서만 실행된다. id가 1·2가 아니면 실패한다(fixture가 id를 고정해서 쓴다).
  다시 만들려면 로컬 개발 DB에서만: python manage.py flush --noinput
"""
import os

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from posts.models import Post

USERNAMES = ["member_a", "member_b", "member_c"]
POSTS = [
    (1, "가상 기록 1", "시험용 가상 본문입니다."),
    (2, "가상 기록 2 (삭제 시험용)", "삭제 시험에 쓰는 가상 본문입니다."),
]


class Command(BaseCommand):
    help = "로컬 개발 DB에 시험용 가상 계정 3개와 기록 2건을 만든다."

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("DJANGO_DEBUG=1인 로컬 개발 환경에서만 실행할 수 있습니다.")
        password = os.environ.get("HAVEN_SEED_PASSWORD", "")
        if not password:
            raise CommandError("환경변수 HAVEN_SEED_PASSWORD가 필요합니다.")
        User = get_user_model()
        try:
            validate_password(password, User(username=USERNAMES[0]))
        except ValidationError as exc:
            raise CommandError("HAVEN_SEED_PASSWORD가 비밀번호 정책에 맞지 않습니다: " + " ".join(exc.messages))
        if User.objects.exists() or Post.objects.exists():
            raise CommandError(
                "빈 DB에서만 실행합니다. 로컬 개발 DB라면 'python manage.py flush --noinput' 후 다시 실행하세요."
            )

        with transaction.atomic():
            users = {name: User.objects.create_user(username=name, password=password) for name in USERNAMES}
            for expected_id, title, body in POSTS:
                post = Post.objects.create(owner=users["member_a"], title=title, body=body)
                if post.pk != expected_id:
                    raise CommandError(
                        f"기록 id가 {expected_id}가 아니라 {post.pk}입니다. "
                        "로컬 개발 DB에서 'python manage.py flush --noinput' 후 다시 실행하세요."
                    )

        self.stdout.write(self.style.SUCCESS("가상 계정 member_a, member_b, member_c와 기록 id 1, 2를 만들었습니다."))
