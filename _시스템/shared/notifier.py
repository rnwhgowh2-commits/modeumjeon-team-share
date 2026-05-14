# -*- coding: utf-8 -*-
"""
notifier.py — 알림 발송 (채널 레지스트리 구조)

역할: 플러그 가능한 채널(카카오·슬랙·텔레그램 등)을 레지스트리에 등록하고,
notify() 호출 시 활성화된 모든 채널로 fan-out.

신규 채널 추가 절차:
    1. NotifierChannel 상속한 클래스 작성
    2. register_channel(MyChannel()) 호출
    3. config.NOTIFIER 에 enabled 플래그 포함 섹션 추가
"""
from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from enum import Enum
from typing import List

import requests

from shared.platforms import NOTIFIER

logger = logging.getLogger(__name__)


class AlertType(Enum):
    """알림 이벤트 유형."""
    이상가         = "이상가"
    품절           = "품절"
    전체품절        = "전체품절"
    크롤링실패      = "크롤링실패"
    업로드실패      = "업로드실패"
    반영가불일치    = "반영가불일치"
    차단감지        = "차단감지"
    마진부족        = "마진부족"
    시스템오류      = "시스템오류"
    토큰발급실패    = "토큰발급실패"
    속도한도도달    = "속도한도도달"
    데드레터       = "데드레터"
    워커크래시     = "워커크래시"
    인증기한임박    = "인증기한임박"


_ALERT_TEMPLATES = {
    AlertType.이상가:       "[이상가 감지] {source} — {detail}",
    AlertType.품절:         "[품절] {source} — {detail}",
    AlertType.전체품절:     "[전체 품절] {option} — 전 소싱처 품절. 판매처 품절 처리 필요.",
    AlertType.크롤링실패:   "[크롤링 실패] {source} — {detail}",
    AlertType.업로드실패:   "[업로드 실패] {platform} — {detail}",
    AlertType.반영가불일치: "[반영가 불일치] {platform} — 기대: {expected}원, 실제: {actual}원",
    AlertType.차단감지:     "[차단 감지] {source} — {detail}",
    AlertType.마진부족:     "[마진 부족] {platform} — {detail}",
    AlertType.시스템오류:   "[시스템 오류] {detail}",
    AlertType.토큰발급실패: "[토큰 발급 실패] {platform} — {detail}",
    AlertType.속도한도도달: "[속도 한도 도달] {platform} — 연속 {count}회 429 수신",
    AlertType.데드레터:     "[데드레터] {platform}/{job_type} — {detail}",
    AlertType.워커크래시:   "[워커 크래시] {worker_id} — {detail}",
    AlertType.인증기한임박: "[인증 기한 임박] {platform} — {days}일 후 만료",
}


def format_alert(alert_type: AlertType, **kwargs) -> str:
    template = _ALERT_TEMPLATES.get(alert_type, "[알림] {detail}")
    try:
        return template.format(**kwargs)
    except KeyError as e:
        logger.warning("템플릿 키 누락 — 유형: %s, 누락키: %s", alert_type.value, e)
        return f"[{alert_type.value}] {kwargs}"


# ──────────────────────────────────────────────────────────────
# 채널 추상
# ──────────────────────────────────────────────────────────────
class NotifierChannel(ABC):
    """알림 채널 추상 기반. 하위 클래스는 name 을 고유하게 지정해야 함."""
    name: str = ""

    @abstractmethod
    def is_enabled(self) -> bool: ...

    @abstractmethod
    def send(self, message: str) -> bool: ...


# ──────────────────────────────────────────────────────────────
# 기본 채널 구현
# ──────────────────────────────────────────────────────────────
class KakaoChannel(NotifierChannel):
    name = "kakao"

    def is_enabled(self) -> bool:
        c = NOTIFIER["카카오톡"]
        return bool(c.get("enabled") and c.get("access_token"))

    def send(self, message: str) -> bool:
        c = NOTIFIER["카카오톡"]
        headers = {
            "Authorization": f"Bearer {c['access_token']}",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        data = {
            "template_object": json.dumps({
                "object_type": "text",
                "text": message,
                "link": {"web_url": "", "mobile_web_url": ""},
            })
        }
        retries = int(NOTIFIER.get("retry_count", 3))
        timeout = float(NOTIFIER.get("retry_timeout_sec", 10))
        for attempt in range(1, retries + 1):
            try:
                resp = requests.post(c["api_url"], headers=headers, data=data, timeout=timeout)
                if resp.status_code == 200:
                    return True
                logger.warning("kakao 실패 attempt=%d status=%d", attempt, resp.status_code)
            except requests.RequestException as e:
                logger.warning("kakao 예외 attempt=%d err=%s", attempt, e)
        return False


class SlackChannel(NotifierChannel):
    name = "slack"

    def is_enabled(self) -> bool:
        c = NOTIFIER["슬랙"]
        return bool(c.get("enabled") and c.get("webhook_url"))

    def send(self, message: str) -> bool:
        c = NOTIFIER["슬랙"]
        retries = int(NOTIFIER.get("retry_count", 3))
        timeout = float(NOTIFIER.get("retry_timeout_sec", 10))
        for attempt in range(1, retries + 1):
            try:
                resp = requests.post(c["webhook_url"], json={"text": message}, timeout=timeout)
                if resp.status_code == 200:
                    return True
                logger.warning("slack 실패 attempt=%d status=%d", attempt, resp.status_code)
            except requests.RequestException as e:
                logger.warning("slack 예외 attempt=%d err=%s", attempt, e)
        return False


# ──────────────────────────────────────────────────────────────
# 레지스트리
# ──────────────────────────────────────────────────────────────
_CHANNELS: List[NotifierChannel] = []


def register_channel(channel: NotifierChannel) -> None:
    """채널을 레지스트리에 추가. 동일 name 중복은 교체."""
    for i, existing in enumerate(_CHANNELS):
        if existing.name == channel.name:
            _CHANNELS[i] = channel
            return
    _CHANNELS.append(channel)


def reset_channels() -> None:
    """레지스트리 초기화 후 기본 채널(카카오·슬랙) 재등록.

    모듈 import 시 1회 자동 호출되며, 테스트 픽스처에서도 상태 초기화 용으로 사용된다.
    신규 채널을 register_channel() 로 추가한 후에는 이 함수를 호출하면 추가 채널이 사라진다.
    """
    _CHANNELS.clear()
    _CHANNELS.append(KakaoChannel())
    _CHANNELS.append(SlackChannel())


def notify(alert_type: AlertType, **kwargs) -> None:
    """포맷팅 후 활성화된 모든 채널로 발송. 채널별 예외/실패는 로깅만 (전파 금지)."""
    message = format_alert(alert_type, **kwargs)
    logger.info("알림 — 유형: %s, 메시지: %s", alert_type.value, message)
    for ch in _CHANNELS:
        try:
            if not ch.is_enabled():
                continue
            ok = ch.send(message)
            if not ok:
                logger.error("[%s] 알림 발송 실패 (전 시도 실패)", ch.name)
        except Exception as e:
            logger.error("[%s] 알림 예외: %s", ch.name, e)


# ──────────────────────────────────────────────────────────────
# 텔레그램 채널
# ──────────────────────────────────────────────────────────────

class TelegramNotifier:
    """텔레그램 Bot API 알림 채널.

    환경변수 TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 또는
    생성자 인자로 자격증명을 주입한다.
    """

    def __init__(self, bot_token: str | None = None, chat_id: str | None = None):
        import os
        self.bot_token = bot_token or os.getenv("TELEGRAM_BOT_TOKEN")
        self.chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID")

    def send(self, subject: str, body: str) -> dict:
        """텔레그램 sendMessage 호출.

        Returns:
            {"ok": True/False, ...} — 실패 이유는 "reason" 키에 기록됨
        """
        if not (self.bot_token and self.chat_id):
            return {"ok": False, "reason": "missing_credentials"}
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        try:
            r = requests.post(
                url,
                json={
                    "chat_id": self.chat_id,
                    "text": f"*{subject}*\n{body}",
                    "parse_mode": "Markdown",
                },
                timeout=5,
            )
            return {"ok": r.ok, "status": r.status_code}
        except Exception as e:
            return {"ok": False, "reason": str(e)}


# ──────────────────────────────────────────────────────────────
# 이벤트 라우팅 디스패처
# ──────────────────────────────────────────────────────────────

# 기본 라우팅 테이블 (DB NotifierRouting 이 없을 때 fallback)
DEFAULT_ROUTING: dict[str, list[str]] = {
    "low_stock": ["telegram"],
    "stock_count_completed": ["telegram"],
    "sourcing_failure": ["slack"],
    "marketplace_upload_failure": ["slack"],
}


def dispatch(
    event_key: str,
    *,
    subject: str,
    body: str,
    override_channels: list[str] | None = None,
) -> dict:
    """이벤트를 적절한 채널로 라우팅하여 발송.

    우선순위:
        1. override_channels (직접 지정)
        2. DB NotifierRouting 테이블
        3. DEFAULT_ROUTING fallback

    Args:
        event_key         : 이벤트 식별자 (예: "low_stock")
        subject           : 알림 제목
        body              : 알림 본문
        override_channels : 채널 목록 직접 지정 (None 이면 DB/기본값 사용)

    Returns:
        채널별 발송 결과 dict {"telegram": {"ok": True}, ...}
    """
    channels = override_channels or _get_channels(event_key)
    results: dict = {}
    notifiers: dict = {
        "telegram": TelegramNotifier(),
        # slack / kakao 는 기존 채널 함수 사용 (있으면)
    }
    for ch in channels:
        notifier_inst = notifiers.get(ch)
        if notifier_inst:
            results[ch] = notifier_inst.send(subject, body)
        else:
            results[ch] = {"ok": False, "reason": "unknown_channel"}
    return results


def _get_channels(event_key: str) -> list[str]:
    """DB NotifierRouting 조회 → 없으면 DEFAULT_ROUTING 반환.

    [E] 르무통 프로젝트에는 NotifierRouting 테이블이 아직 없어 DB 경로는 비활성.
    필요 시 lemouton 측에서 모델을 추가하고 lazy import 부활시키면 됨.
    """
    return DEFAULT_ROUTING.get(event_key, [])


# ──────────────────────────────────────────────────────────────
# 하위 호환 함수 (기존 호출자 보존)
# ──────────────────────────────────────────────────────────────
def send_kakao(message: str) -> bool:
    ch = KakaoChannel()
    return ch.send(message) if ch.is_enabled() else False


def send_slack(message: str) -> bool:
    ch = SlackChannel()
    return ch.send(message) if ch.is_enabled() else False


# 모듈 import 시 기본 채널 자동 등록
reset_channels()
