"""마켓 정산 대조 실행 이력 (노션 주문관리 c-4).

한 번 대조할 때마다 한 줄. 「지난번 대비」 수렴을 볼 수 있어야 대조가 쓸모 있다
(샵마인 대조탭 `ShopmineReconRun` 과 같은 구조·같은 이유).

Alembic 없음 — app.py 가 이 모듈을 import 하면 `Base.metadata.create_all` 이 생성.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, Column, DateTime, Integer, String

from shared.db import Base


def _utcnow():
    return datetime.now(timezone.utc)


class SettleReconRun(Base):
    """정산 대조 1회 — 어떤 항목을, 어떤 파일로, 어떻게 판정했나.

    result 에 판정 dict 를 그대로 담는다(화면·저장이 같은 모양을 쓴다).
    parsed 는 「우리가 파일을 어떻게 읽었나」 — 열 이름·기간·건수까지 남겨야
    나중에 「그때 왜 그 숫자였나」를 되짚을 수 있다.
    """

    __tablename__ = "settle_recon_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ran_at = Column(DateTime, default=_utcnow)
    item = Column(String(40), default="")        # ITEMS 의 키
    filename = Column(String(255), default="")
    market_total = Column(Integer, default=0)
    ours_total = Column(Integer, default=0)
    verdict = Column(String(16), default="")     # match|tol|def|diff|unknown
    parsed = Column(JSON)
    result = Column(JSON)
