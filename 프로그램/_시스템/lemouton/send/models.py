# -*- coding: utf-8 -*-
"""마켓 전송 작업 — 한 번 누른 것과 그 안의 건별 결과.

설계서: docs/superpowers/specs/2026-08-02-상품-마켓전송-탭-design.md §4-4
사장님 확정 2026-08-02 ③-b:
  "발송 시 실패하면 발송 실패 부류에 맞게 설정하고 실패사유 보내기.
   ex. 정책 필수 상품 누락으로 인한 마켓 전송 실패
   (**이 내용은 api 실제 마켓으로부터 전송 실패한 이유를 적어야함**)"

━━ 🔴 실패를 두 칸으로 나눈다 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  `kind`            부류 — **우리가** 붙인다. 무엇부터 손볼지 정하는 데 쓴다.
  `market_code`     마켓이 준 **에러코드 원문**
  `market_message`  마켓이 준 **메시지 원문**

  🔴 마켓 칸은 **우리가 지어내지 않는다.** 마켓이 아무 말도 안 했으면 비워 두고
    `kind=NO_REASON_GIVEN` 으로 남긴다. 그럴듯한 추측을 적으면 사장님이 엉뚱한
    데를 고친다 (프로젝트 최상위 원칙 · 폴백 금지).

    어댑터는 이미 원문을 들고 있다 —
    `adapters/smartstore.py` 의 `error=f"{r.error_code}: {r.error_message}"`.
    지금은 그게 `MarketRegistration.sync_error` 한 칸에 뭉개져 부류와 섞인다.

━━ 왜 DB 인가 (DLQ 는 파일이다) ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  기존 실패함(`uploader/dlq.py`)은 `logs/*.jsonl` 이다. 그런데 앱 컨테이너 안
  파일은 **배포마다 사라진다**(CLAUDE.md). 「어제 왜 실패했지」를 물을 수 있어야
  하므로 전송 이력은 표로 남긴다.

Alembic 없음 — 신규 테이블이라 `shared/db.py:init_db()` 의 create_all 이 만든다.
  ★ `app.py` 가 이 모듈을 import 해야 등록된다(컬럼 추가만 migrations 리스트 필요).
"""
from datetime import datetime, timezone

from sqlalchemy import (
    Column, DateTime, ForeignKey, Index, Integer, String, Text,
)

from shared.db import Base


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ── 실패 부류 (우리가 붙인다) ────────────────────────────────────────────
#
# 전송 **전** 게이트에서 잡히는 것과, 마켓이 **거부한** 것을 구분한다.
# 앞의 것은 우리가 고칠 수 있고, 뒤의 것은 마켓 말을 들어야 안다.

KIND_OK = 'OK'                                   # 성공
KIND_SKIPPED = 'SKIPPED'                         # 보낼 게 없어 건너뜀(변동 없음 등)

#: 전송 **전** 우리 게이트가 막은 것 — 마켓을 부르지도 않았다.
KIND_NO_POLICY = 'NO_POLICY'                     # 정책이 안 붙음 = 보낼 값이 안 정해짐
KIND_REQUIRED_MISSING = 'POLICY_REQUIRED_MISSING'  # 그 마켓 필수 항목이 비었음
KIND_STOCK_UNKNOWN = 'STOCK_UNKNOWN'             # 재고 확인 불가 — 있다고 단정 못 함
KIND_NO_CATEGORY = 'NO_CATEGORY'                 # 마켓 카테고리 미확정
KIND_ACCOUNT = 'ACCOUNT'                         # 계정·인증 문제

#: 마켓을 불렀는데 실패한 것.
KIND_MARKET_REJECTED = 'MARKET_REJECTED'         # 마켓이 거부 — 사유는 마켓 원문
KIND_NO_REASON_GIVEN = 'NO_REASON_GIVEN'         # 실패했는데 마켓이 사유를 안 줌
KIND_NETWORK = 'NETWORK'                         # 아예 닿지 못함(연결·시간초과)

#: 화면에 보일 이름 + 사장님이 무엇을 해야 하는지.
#:   🔴 「어떻게 고치나」를 같이 적는다 — 부류만 있으면 이름만 알고 손을 못 쓴다.
KIND_LABEL: dict[str, tuple[str, str]] = {
    KIND_OK: ('보냄', ''),
    KIND_SKIPPED: ('건너뜀', '보낼 변동이 없었습니다.'),
    KIND_NO_POLICY: ('정책 없음',
                     '이 구성에 정책이 안 붙어 있습니다 — 「정책 매칭」에서 붙여 주세요.'),
    KIND_REQUIRED_MISSING: ('필수 항목 빔',
                            '그 마켓이 요구하는 항목이 비어 있습니다 — 「정책 생성」에서 '
                            '빨간 「필수」가 붙은 칸을 채워 주세요.'),
    KIND_STOCK_UNKNOWN: ('재고 확인 불가',
                         '소싱처에서 재고를 못 읽었습니다 — 있다고 단정하고 올리면 '
                         '오버셀입니다. 크롤을 다시 돌려 주세요.'),
    KIND_NO_CATEGORY: ('카테고리 없음',
                       '이 마켓 카테고리가 아직 확정되지 않았습니다 — 맵핑표에서 '
                       '확정해 주세요.'),
    KIND_ACCOUNT: ('계정 문제', '판매처 계정·인증을 확인해 주세요.'),
    KIND_MARKET_REJECTED: ('마켓이 거부', '아래 마켓이 보낸 사유를 그대로 보여드립니다.'),
    KIND_NO_REASON_GIVEN: ('사유 못 받음',
                           '마켓이 실패라고만 하고 이유를 주지 않았습니다 — '
                           '지어내지 않고 그대로 적습니다.'),
    KIND_NETWORK: ('마켓에 못 닿음', '연결이 안 되거나 시간이 초과됐습니다.'),
}

#: 마켓을 **부르기 전에** 막은 부류 — 우리가 고칠 수 있는 것들.
PRE_SEND_KINDS = frozenset({KIND_NO_POLICY, KIND_REQUIRED_MISSING, KIND_STOCK_UNKNOWN,
                            KIND_NO_CATEGORY, KIND_ACCOUNT})
#: 실패로 세는 부류 (성공·건너뜀 빼고 전부).
FAILURE_KINDS = frozenset(KIND_LABEL) - {KIND_OK, KIND_SKIPPED}


class SendJob(Base):
    """전송 버튼 한 번 = 작업 1건.

    화면이 「지난번에 뭘 보냈지」를 되짚을 수 있어야 한다. 작업이 없으면 결과 행만
    흩어져 「이번 것」과 「지난 것」을 못 가른다.
    """

    __tablename__ = 'send_jobs'

    id = Column(Integer, primary_key=True, autoincrement=True)
    # 'send' = 마켓으로 보내기 / 'harvest' = 소싱처 다시 긁기 / 'both' = 긁고 보내기
    #   (사장님 확정 ② — 「긁을 항목」과 「보낼 항목」을 둘 다 둔다)
    mode = Column(String(16), nullable=False, default='send')
    # 무엇을 골라 눌렀나 — 되짚기용. 필터 조건을 JSON 문자열로 그대로 담는다.
    filters_json = Column(Text)
    # 'running' | 'done' | 'stopped'
    status = Column(String(16), nullable=False, default='running')
    total = Column(Integer, nullable=False, default=0)
    ok_count = Column(Integer, nullable=False, default=0)
    fail_count = Column(Integer, nullable=False, default=0)
    started_at = Column(DateTime, default=_utcnow, nullable=False)
    finished_at = Column(DateTime)
    # 누가 눌렀나 — 팀 공유라 필요하다.
    started_by = Column(String(64))
    # 🔴 살아있음 신호 — 서버 워커가 2개라 「스레드가 이 프로세스에 없다」는
    #   죽었다는 뜻이 아니다(폴링이 다른 워커에 떨어지면 늘 없다). 돌고 있는
    #   스레드가 주기적으로 시각을 찍고, 고아 판정은 이 시각의 신선도로 한다.
    #   실측: 살아있는 작업을 「고아」로 오판해 닫아버린 라이브 사고(job 2).
    heartbeat_at = Column(DateTime)
    # 지금 뭘 하는 중인가 — 큰 상품은 사본 조립만 100초가 넘는다(라이브 524 실측).
    #   그동안 로그가 0줄이면 화면이 「죽었나」로 보인다. 단계를 적어 보여준다.
    stage = Column(String(200))

    __table_args__ = (
        Index('ix_send_jobs_started', 'started_at'),
    )


class SendJobRow(Base):
    """작업 안의 한 건 = (구성 × 마켓 × 계정) 하나.

    ★ 한 줄이 **구성(벌)** 인 이유 — 사장님 확정 ①. 마켓에 올라가는 실제 단위가
      구성이다(구성 하나 = 마켓 상품 하나). 상품 단위로 적으면 「한 상품에 여러
      정책」일 때 어느 벌이 실패했는지 못 말한다.
    """

    __tablename__ = 'send_job_rows'

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(Integer, ForeignKey('send_jobs.id', ondelete='CASCADE'),
                    nullable=False, index=True)

    set_id = Column(Integer, index=True)          # 구성(ProductSet). FK 는 걸지 않는다 —
    model_code = Column(String(64), index=True)   #   구성을 지워도 이력은 남아야 한다.
    market = Column(String(20), nullable=False)
    account_key = Column(String(64), nullable=False, default='default')

    # 보낸 뒤 받은 마켓 상품번호(신규 등록이면 여기서 처음 생긴다).
    market_product_id = Column(String(64))
    # 'create'(신규 등록) | 'update'(수정) — 화면이 둘을 갈라 보여준다.
    action = Column(String(16), nullable=False, default='update')

    # ── 결과 ────────────────────────────────────────────────────────
    kind = Column(String(32), nullable=False, default=KIND_OK)   # 부류 — 우리가 붙임
    #: 🔴 아래 두 칸은 **마켓이 준 원문 그대로**. 비어 있으면 마켓이 말을 안 한 것이다.
    market_code = Column(String(64))
    market_message = Column(Text)
    #: 우리가 덧붙인 안내(있으면). 마켓 말과 **절대 섞지 않는다.**
    our_note = Column(Text)

    http_status = Column(Integer)
    created_at = Column(DateTime, default=_utcnow, nullable=False)

    __table_args__ = (
        Index('ix_send_job_rows_kind', 'job_id', 'kind'),
        Index('ix_send_job_rows_market', 'market', 'created_at'),
    )

    @property
    def failed(self) -> bool:
        return self.kind in FAILURE_KINDS

    @property
    def reason_text(self) -> str:
        """화면에 보일 사유 한 줄 — **마켓 말이 먼저**, 없으면 없다고 말한다.

        🔴 우리 안내로 마켓 사유를 대체하지 않는다. 사장님이 「마켓이 뭐랬는데?」를
          물었을 때 답이 나와야 한다.
        """
        if self.market_code or self.market_message:
            head = f'[{self.market_code}] ' if self.market_code else ''
            return f'{head}{self.market_message or ""}'.strip()
        if self.kind in PRE_SEND_KINDS:
            return KIND_LABEL.get(self.kind, ('', ''))[1]
        if self.kind in FAILURE_KINDS:
            return '마켓이 실패 사유를 주지 않았습니다.'
        return ''
