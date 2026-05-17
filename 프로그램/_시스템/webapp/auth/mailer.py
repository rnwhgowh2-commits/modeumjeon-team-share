"""Gmail SMTP 메일 발송 헬퍼 — 비밀번호 재설정 메일 전용.

환경변수 (.env 로 주입):
  SMTP_USER             : Gmail 주소 (예: you@gmail.com)
  SMTP_APP_PASSWORD     : Google 앱 비밀번호 16자 (공백 제거)
  SMTP_FROM             : 발신자 표시 이메일 (보통 SMTP_USER 와 동일)
  APP_BASE_URL          : reset 링크 base URL (예: http://127.0.0.1:5053)

설계:
  - 표준 라이브러리만 (smtplib + email.mime). 의존성 추가 없음.
  - 환경변수 누락 시 ValueError → 라우트가 받아서 안전한 fallback 메시지 표시.
  - 발송 실패는 예외로 raise → 라우트가 잡아서 로깅 (사용자에겐 동일 응답 — enumeration 방지).
"""
from __future__ import annotations

import os
import smtplib
import ssl
from email.message import EmailMessage
from typing import Optional


SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587   # STARTTLS


class MailConfigError(RuntimeError):
    """SMTP 환경변수 누락·잘못된 형식."""


def _get_config() -> tuple[str, str, str, str]:
    user = os.environ.get("SMTP_USER", "").strip()
    pw = os.environ.get("SMTP_APP_PASSWORD", "").strip().replace(" ", "")
    sender = os.environ.get("SMTP_FROM", "").strip() or user
    base_url = os.environ.get("APP_BASE_URL", "").strip().rstrip("/")

    missing = [k for k, v in [("SMTP_USER", user), ("SMTP_APP_PASSWORD", pw), ("APP_BASE_URL", base_url)] if not v]
    if missing:
        raise MailConfigError(f"환경변수 누락: {', '.join(missing)}. .env 확인 필요.")

    if len(pw) != 16:
        raise MailConfigError(
            f"SMTP_APP_PASSWORD 는 Google 앱 비밀번호 16자여야 합니다 (현재 {len(pw)}자). "
            "https://myaccount.google.com/apppasswords 에서 재발급."
        )
    return user, pw, sender, base_url


def _send(to_email: str, subject: str, text_body: str, html_body: Optional[str] = None) -> None:
    """단일 메일 발송 — 실패 시 예외 raise."""
    user, pw, sender, _base = _get_config()

    msg = EmailMessage()
    msg["From"] = f"모음전 시스템 <{sender}>"
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(text_body)
    if html_body:
        msg.add_alternative(html_body, subtype="html")

    ctx = ssl.create_default_context()
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as s:
        s.ehlo()
        s.starttls(context=ctx)
        s.login(user, pw)
        s.send_message(msg)


def send_password_reset_email(to_email: str, user_name: str, token: str) -> None:
    """비밀번호 재설정 링크 메일.

    링크: {APP_BASE_URL}/auth/reset-password/{token}
    """
    _, _, _, base_url = _get_config()
    reset_url = f"{base_url}/auth/reset-password/{token}"

    subject = "[모음전] 비밀번호 재설정 안내"

    text_body = f"""{user_name}님,

모음전 시스템에서 비밀번호 재설정 요청이 접수되었습니다.

아래 링크를 클릭하면 새 비밀번호를 설정할 수 있습니다 (유효시간 1시간):

{reset_url}

요청하지 않으셨다면 이 메일을 무시해 주세요. 기존 비밀번호는 그대로 유지됩니다.

— 모음전 시스템
"""

    html_body = f"""<!doctype html>
<html><body style="font-family: -apple-system, 'Segoe UI', sans-serif; line-height:1.6; color:#292A2F; max-width:560px; margin:24px auto; padding:0 16px;">
  <div style="text-align:center; padding:20px 0; border-bottom:1px solid #E5E8EB;">
    <div style="font-size:24px; font-weight:700; color:#4F67FF;">모음전</div>
    <div style="font-size:12px; color:#6B7684; margin-top:4px;">팀 공유 재고 시스템</div>
  </div>
  <h2 style="font-size:18px; margin:24px 0 12px;">비밀번호 재설정 안내</h2>
  <p style="font-size:14px;">{user_name}님, 비밀번호 재설정 요청이 접수되었습니다.</p>
  <p style="font-size:14px;">아래 버튼을 눌러 새 비밀번호를 설정해 주세요.</p>
  <div style="text-align:center; margin:28px 0;">
    <a href="{reset_url}" style="display:inline-block; padding:14px 28px; background:#4F67FF; color:#fff; text-decoration:none; border-radius:10px; font-size:14px; font-weight:600;">비밀번호 재설정</a>
  </div>
  <p style="font-size:12px; color:#6B7684; word-break:break-all;">또는 이 링크를 복사: <br><span style="color:#4F67FF;">{reset_url}</span></p>
  <p style="font-size:12px; color:#6B7684; margin-top:24px; padding-top:16px; border-top:1px solid #E5E8EB;">
    이 링크는 <strong>1시간</strong> 동안 유효합니다. 한 번만 사용 가능합니다.<br>
    요청하지 않으셨다면 이 메일을 무시해 주세요. 기존 비밀번호는 그대로 유지됩니다.
  </p>
</body></html>"""

    _send(to_email, subject, text_body, html_body)


def send_test_email(to_email: str) -> None:
    """SMTP 설정 테스트용."""
    _send(
        to_email,
        "[모음전] SMTP 연동 테스트",
        "이 메일을 받으셨다면 Gmail SMTP 가 정상 작동합니다.\n— 모음전 시스템",
    )
