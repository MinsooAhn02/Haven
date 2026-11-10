"""운영 관리자 전용 권한 (명세 3.2).

테이블은 만들지 않는다(managed=False). 권한 두 개를 등록하기 위한 자리다.
권한 행은 migrate 뒤 Django가 자동으로 만든다(post_migrate). 부여는 관리자가 직접 하거나 seed_demo가 한다.
"""
from django.db import models


class AccountStatusAdministration(models.Model):
    class Meta:
        managed = False
        default_permissions = ()
        permissions = [
            ("manage_account_status", "일반 회원 계정 활성/비활성 변경"),
            ("view_account_status_events", "계정 상태 변경 이력 조회"),
        ]
