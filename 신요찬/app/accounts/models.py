"""accounts 모델: 로그인 실패 기록(로그인 실패 제한, 앱계약 8장 13번)."""
from django.db import models


class LoginFailure(models.Model):
    """최근 로그인 실패 한 건. 아이디·IP 원문 대신 HMAC 키만 저장한다(accounts/login_limit.py)."""

    class Axis(models.TextChoices):
        ACCOUNT = "account", "아이디"
        IP = "ip", "IP"

    axis = models.CharField(max_length=7, choices=Axis.choices)
    key = models.CharField(max_length=64)
    created_at = models.DateTimeField()

    class Meta:
        indexes = [models.Index(fields=["axis", "key", "created_at"], name="login_failure_lookup")]
        constraints = [
            models.CheckConstraint(condition=models.Q(axis__in=["account", "ip"]), name="login_failure_axis_valid"),
        ]

    def __str__(self):
        return f"{self.axis} {self.created_at:%Y-%m-%d %H:%M:%S}"
