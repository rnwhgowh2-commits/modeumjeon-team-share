"""[B] 글로벌 설정 — 단일 row 테이블."""
from sqlalchemy import Column, Integer, Float, String, Boolean, DateTime, ForeignKey
from datetime import datetime, timezone

from shared.db import Base


# DEFAULT 값 — 사용자 결정 기반 (spec §2)
_DEFAULTS = {
    "boxhero_purchase_price_default": 95000,
    "boxhero_ss_price_default": 115900,
    "boxhero_coupang_price_default": 128900,
    "external_ss_price_default": 128900,
    "external_coupang_price_default": 128900,
    "coupang_winner_premium_price": 149000,
    "guardrail_lower": 99000,
    "guardrail_upper": 120000,
    "delivery_fee": 3000,
    "ss_fee_rate": 0.06,
    "coupang_fee_rate": 0.1155,
    "external_ss_margin_mode": "rate",
    "external_ss_margin_value": 0.0945,
    "external_coupang_margin_mode": "rate",
    "external_coupang_margin_value": 0.1242,
    "rounding_unit": 100,
    "crawl_interval_hours": 6,
    "dryrun_warnings_threshold": 5,
    "dryrun_avg_price_change_pct": 30.0,
    # [자동화 설정] 크롤 자동 주기 + 판매처 자동 전송
    "crawl_auto_enabled": False,
    "crawl_interval_minutes": 0,
    "autosend_mode": "preview",          # preview | real
    "autosend_on_purchase": True,
    "autosend_on_stock": True,
    "autosend_stock_threshold": 4,
    "autosend_on_price": True,
    # [2026-07-19 Phase 1B M3-1] 역마진 가드 최소 마진 — **율(%)이 아니라 금액(원)**.
    # 기본 0 = "1원이라도 남으면 올린다" → 오늘 동작과 완전히 동일(도입 영향 0).
    "min_margin_amount": 0,
}


class GlobalSettings(Base):
    """단일 row 테이블. id=1 고정."""
    __tablename__ = "global_settings"

    id = Column(Integer, primary_key=True, default=1)

    boxhero_purchase_price_default = Column(Integer, default=95000, nullable=False)
    boxhero_ss_price_default = Column(Integer, default=115900, nullable=False)
    boxhero_coupang_price_default = Column(Integer, default=128900, nullable=False)
    external_ss_price_default = Column(Integer, default=128900, nullable=False)
    external_coupang_price_default = Column(Integer, default=128900, nullable=False)
    coupang_winner_premium_price = Column(Integer, default=149000, nullable=False)
    guardrail_lower = Column(Integer, default=99000, nullable=False)
    guardrail_upper = Column(Integer, default=120000, nullable=False)
    delivery_fee = Column(Integer, default=3000, nullable=False)
    ss_fee_rate = Column(Float, default=0.06, nullable=False)
    coupang_fee_rate = Column(Float, default=0.1155, nullable=False)
    external_ss_margin_mode = Column(String(16), default="rate", nullable=False)
    external_ss_margin_value = Column(Float, default=0.0945, nullable=False)
    external_coupang_margin_mode = Column(String(16), default="rate", nullable=False)
    external_coupang_margin_value = Column(Float, default=0.1242, nullable=False)
    rounding_unit = Column(Integer, default=100, nullable=False)
    crawl_interval_hours = Column(Integer, default=6, nullable=False)
    dryrun_warnings_threshold = Column(Integer, default=5, nullable=False)
    dryrun_avg_price_change_pct = Column(Float, default=30.0, nullable=False)
    # [자동화 설정]
    crawl_auto_enabled = Column(Boolean, default=False, nullable=False)
    crawl_interval_minutes = Column(Integer, default=0, nullable=False)
    autosend_mode = Column(String(8), default="preview", nullable=False)
    autosend_on_purchase = Column(Boolean, default=True, nullable=False)
    autosend_on_stock = Column(Boolean, default=True, nullable=False)
    autosend_stock_threshold = Column(Integer, default=4, nullable=False)
    autosend_on_price = Column(Boolean, default=True, nullable=False)
    # [역마진 가드 — Phase 1B M3-1]
    # 마진율(%)이 아니라 마진금액(원)이 기준이다(사용자 확정). 이 값 미만이면
    # 업로드하지 않고 '판매중지 후보'로 표시한다. 전역 1개로 시작 —
    # 마켓별/상품별 예외가 필요해지면 그때 분리한다(지금 나누면 같은 숫자가
    # 여러 곳에 복제돼 한 곳만 고치는 사고가 난다).
    # ※ 기존 테이블에는 create_all 이 컬럼을 못 붙인다 →
    #   shared/db.py::_apply_lightweight_migrations() 에 ADD COLUMN 등록 필수.
    min_margin_amount = Column(Integer, default=0, nullable=False)

    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        return {col.name: getattr(self, col.name)
                for col in self.__table__.columns
                if col.name not in ("id", "updated_at")}


def get_or_init(session) -> GlobalSettings:
    """싱글톤 row 가져오기. 없으면 default로 생성."""
    s = session.get(GlobalSettings, 1)
    if s is None:
        s = GlobalSettings(id=1, **_DEFAULTS)
        session.add(s)
    return s


def get_settings(session) -> GlobalSettings | None:
    return session.get(GlobalSettings, 1)


def save_settings(session) -> None:
    """이미 변경된 객체를 flush. session.commit은 호출자가."""
    session.flush()


# ── 계정(API)별 업로드 속도 (P4b) = 업로드 속도 정본 ─────────────────────────
# (구 P4 마켓 per_minute 정책 MarketUploadPolicy 는 폐기 — 이 계정 단위로 흡수.
#  마켓 처리량은 lemouton/uploader/throttle.py 의 market_hourly_total 파생값.)
_ACCOUNT_DEFAULT_SECONDS = 6   # 1개당 6초 = 시간당 600개


class AccountUploadPolicy(Base):
    """판매 계정(API)별 업로드 속도. account_id = **upload_accounts.id**.

    ■ 2026-07-20 계정 배선 통일 (사장님 「가」)
      옛날엔 ``market_accounts`` 를 봤다. 그런데 판매처 관리 화면이 쓰는 표는
      ``upload_accounts`` 라, **계정을 아무리 추가해도 속도 정책은 0개**였다
      (라이브 확인: 판매처 관리 30개 vs 속도 정책 0개).
      ``market_accounts`` 에 행을 넣는 코드는 일회성 마이그레이션 스크립트뿐이라
      영원히 안 채워진다. → 실제로 쓰는 표 하나로 모은다.

      ★ 계정이 0개면 속도 제한기가 **무제한**으로 동작한다
        (:func:`lemouton.uploader.throttle.market_min_interval_seconds` 가 0 반환).
        즉 이 배선이 끊긴 동안은 브레이크가 없었다.

    ■ 「X초에 Y개」 (2026-07-19 사장님 확정)
      옛 칸 ``seconds_per_item`` 은 **1개당 몇 초**라 한 계정이 초당 1개가 최대였다.
      「1초에 10개」도, 「10초에 30개」(순간 몰림 허용)도 담지 못한다.
      → ``window_seconds`` + ``max_count`` 두 칸을 더했다.

      ★ 옛 칸은 **지우지 않는다.** 기존 행이 그대로 돌아야 하고,
        새 칸이 NULL 이면 옛 칸에서 「N초에 1개」로 읽는다
        (:func:`lemouton.uploader.rate_window.from_seconds_per_item`).
    """
    __tablename__ = "account_upload_policies"

    account_id = Column(Integer, ForeignKey("upload_accounts.id"), primary_key=True)
    seconds_per_item = Column(Integer, default=_ACCOUNT_DEFAULT_SECONDS, nullable=False)
    # 2026-07-19: 「X초에 Y개」. NULL = 아직 안 정함 → seconds_per_item 에서 읽는다.
    window_seconds = Column(Integer)
    max_count = Column(Integer)
    enabled = Column(Boolean, default=True, nullable=False)


class MarketUploadPolicy(Base):
    """**마켓별** 업로드 속도 한도 — 그 마켓 API 자체의 제한.

    계정이 몇 개든 마켓 전체로 묶인다. 계정 수로 뚫으면 차단당한다.
    실제 확인분(2026-07-19 조사) — 쿠팡 60초에 50개 · 옥션/G마켓 5초에 1개.
    나머지 마켓은 **모른다** → 행이 없으면 '한도 미설정'이고, 계정 합산만 쓴다.
    """
    __tablename__ = "market_upload_policies"

    market = Column(String(32), primary_key=True)
    window_seconds = Column(Integer, nullable=False, default=1)
    max_count = Column(Integer, nullable=False, default=1)
    enabled = Column(Boolean, default=True, nullable=False)
    note = Column(String(200))          # 출처 메모 ("공식문서 확인 2026-07" 등)


def _active_accounts(session):
    """속도 정책의 대상 계정 = **판매처 관리에 등록된 업로드 계정**.

    ★ 2026-07-20: 여기가 배선 통일의 유일한 갈아끼움 지점이다.
      옛 ``market_accounts`` 는 웹앱 어디에서도 안 채워서 항상 0개였다.
      ``upload_accounts`` 는 판매처 관리 화면(`/accounts/upload`)이 직접 쓴다.
    """
    from lemouton.sourcing.models_v2 import UploadAccount
    return (session.query(UploadAccount)
            .filter(UploadAccount.is_active.is_(True))
            .order_by(UploadAccount.market, UploadAccount.id)
            .all())


def _account_name(acc) -> str:
    """화면에 보일 계정 이름. UploadAccount 는 ``display_name`` 을 쓴다."""
    return (getattr(acc, "display_name", None)
            or getattr(acc, "account_name", None)
            or getattr(acc, "account_key", None) or "")


# ── 「X초에 Y개」 (2026-07-19) ──────────────────────────────────────────────

def account_rate_window(policy):
    """계정 정책 → RateWindow. 새 칸이 비었으면 옛 칸에서 읽는다."""
    from lemouton.uploader.rate_window import RateWindow, from_seconds_per_item
    w, n = getattr(policy, "window_seconds", None), getattr(policy, "max_count", None)
    if w and n:
        return RateWindow(w, n)
    return from_seconds_per_item(getattr(policy, "seconds_per_item", None))


def set_account_rate(session, account_id: int, *, window_seconds: int, max_count: int):
    """계정 속도를 「X초에 Y개」로 저장. 호출자가 commit.

    옛 칸(seconds_per_item)도 **같이 맞춰 둔다** — 아직 옛 칸을 읽는 코드가 있고,
    둘이 어긋나면 어느 게 진짜인지 알 수 없게 된다.
    """
    from lemouton.uploader.rate_window import RateWindow, per_second
    rw = RateWindow(window_seconds, max_count)        # ← 여기서 검증
    p = session.get(AccountUploadPolicy, account_id)
    if p is None:
        p = AccountUploadPolicy(account_id=account_id, enabled=True)
        session.add(p)
    p.window_seconds = int(rw.window_seconds)
    p.max_count = int(rw.max_count)
    p.seconds_per_item = max(1, round(1.0 / per_second(rw)))
    session.flush()
    return p


def get_market_rate(session, market: str):
    """마켓 API 한도 RateWindow. 행이 없거나 꺼져 있으면 None(= 한도 미설정)."""
    from lemouton.uploader.rate_window import RateWindow
    row = session.get(MarketUploadPolicy, (market or "").strip())
    if not row or not row.enabled:
        return None
    try:
        return RateWindow(row.window_seconds, row.max_count)
    except ValueError:
        return None       # 깨진 값은 '한도 미설정'으로 — 화면이 죽는 것보다 낫다


def set_market_rate(session, market: str, *, window_seconds: int, max_count: int,
                    enabled: bool = True, note: str = ""):
    """마켓 API 한도를 저장(수기 설정). 호출자가 commit."""
    from lemouton.uploader.rate_window import RateWindow
    mk = (market or "").strip()
    if not mk:
        raise ValueError("마켓 키가 비었습니다.")
    RateWindow(window_seconds, max_count)             # ← 검증만
    row = session.get(MarketUploadPolicy, mk)
    if row is None:
        row = MarketUploadPolicy(market=mk)
        session.add(row)
    row.window_seconds = int(window_seconds)
    row.max_count = int(max_count)
    row.enabled = bool(enabled)
    row.note = (note or "")[:200]
    session.flush()
    return row


def clear_market_rate(session, market: str) -> bool:
    """마켓 한도를 지워 **「미확인」으로 되돌린다**. 호출자가 commit.

    ★ 왜 필요한가: 한 번 넣은 숫자를 못 지우면, 나중에 그게 공식 문서에서
      확인된 값인 줄 알고 쓰게 된다. '모르는 건 행을 안 만든다'가 원칙이므로
      '모른다'로 되돌리는 길도 있어야 한다.

    ⚠️ 시드 대상 마켓(쿠팡·옥션·G마켓)은 **다음 재부팅에 공식 확인값으로 되돌아온다**
      (:mod:`lemouton.uploader.market_rate_seed` 가 insert-if-missing).
      영구히 비우려면 그 시드에서 빼야 한다.

    Returns:
        실제로 지웠으면 True, 원래 없었으면 False.
    """
    row = session.get(MarketUploadPolicy, (market or "").strip())
    if row is None:
        return False
    session.delete(row)
    session.flush()
    return True


def market_effective_rate(session, market: str) -> dict:
    """그 마켓에 실제로 나갈 속도 — 계정 합산과 마켓 한도 중 느린 쪽.

    ★ 마켓 한도는 **API 호출 수** 기준이고, 여기서 돌려주는 건 **업로드 건수**다.
      1건 업로드에 2콜이 드는 마켓(스마트스토어·옥션·G마켓 — 현재값을 GET 한 뒤
      전체를 PUT)은 한도를 호출배수로 나눠 건수로 환산한다. 안 나누면 한도가
      1초에 4콜인데 4건/s 로 보내 실제 호출은 8콜/s = 한도의 2배가 된다.
      근거: shared/platforms/smartstore/edit_product.py:49 · esm/inventory.py:57
    """
    from lemouton.uploader.rate_window import RateWindow, effective_rate
    accs = []
    for a in _active_accounts(session):
        if a.market != market:
            continue
        p = session.get(AccountUploadPolicy, a.id)
        if p is None:
            # ★ 정책 행이 아직 없다 = '아직 안 정함'이지 '계정 없음'이 아니다.
            #   빼버리면 계정이 있는데도 "보낼 수 없음"으로 보인다 (조용한 실패).
            #   값은 **시드될 기본값과 같은 것**을 쓴다 — 시드 전후로 숫자가
            #   달라지면(그것도 시드 전이 더 빠르면) 화면을 믿을 수 없다.
            accs.append(RateWindow(_ACCOUNT_DEFAULT_SECONDS, 1))
        elif p.enabled:
            accs.append(account_rate_window(p))
    return effective_rate(account_rates=accs,
                          market_rate=market_rate_as_uploads(session, market))


def market_rate_as_uploads(session, market: str):
    """마켓 한도(API 호출 수) → **업로드 건수** 기준 RateWindow. 없으면 None.

    1건에 2콜이 드는 마켓은 창을 2배로 늘려 건수를 반으로 만든다
    (「1초에 4콜」 → 「2초에 4건」 = 2건/s).
    """
    from lemouton.uploader.rate_window import RateWindow
    from lemouton.uploader.throttle import calls_per_upload

    mk = get_market_rate(session, market)
    if mk is None:
        return None
    calls = calls_per_upload(market)
    if calls <= 1:
        return mk
    return RateWindow(mk.window_seconds * calls, mk.max_count)


def get_account_policies(session) -> list:
    """활성 계정별 속도 정책. 없으면 기본 시드. per_hour 파생 포함."""
    for acc in _active_accounts(session):
        if session.get(AccountUploadPolicy, acc.id) is None:
            session.add(AccountUploadPolicy(account_id=acc.id,
                        seconds_per_item=_ACCOUNT_DEFAULT_SECONDS, enabled=True))
    session.flush()
    out = []
    for acc in _active_accounts(session):
        p = session.get(AccountUploadPolicy, acc.id)
        sec = max(1, int(p.seconds_per_item))
        out.append({"account_id": acc.id, "market": acc.market,
                    "account_name": _account_name(acc),
                    "seconds_per_item": sec, "enabled": p.enabled,
                    "per_hour": 3600 // sec})
    return out


def set_account_policy(session, account_id: int, *, seconds_per_item=None,
                       enabled=None) -> dict:
    """전달된 항목만 갱신. seconds ≥ 1 클램프. 호출자가 commit."""
    p = session.get(AccountUploadPolicy, account_id)
    if p is None:
        p = AccountUploadPolicy(account_id=account_id,
                                seconds_per_item=_ACCOUNT_DEFAULT_SECONDS, enabled=True)
        session.add(p)
    if seconds_per_item is not None:
        p.seconds_per_item = max(1, int(seconds_per_item))
    if enabled is not None:
        p.enabled = bool(enabled)
    session.flush()
    sec = max(1, int(p.seconds_per_item))
    return {"seconds_per_item": sec, "enabled": p.enabled, "per_hour": 3600 // sec}


# ── 자동화 설정 (크롤 자동 주기 + 판매처 자동 전송) ──────────────────────────
_AUTOMATION_KEYS = (
    "crawl_auto_enabled", "crawl_interval_hours", "crawl_interval_minutes",
    "autosend_mode", "autosend_on_purchase", "autosend_on_stock",
    "autosend_stock_threshold", "autosend_on_price",
)


def get_automation(session) -> dict:
    """자동화 설정 값 dict (팀 공유 단일 설정)."""
    s = get_or_init(session)
    return {k: getattr(s, k) for k in _AUTOMATION_KEYS}


def save_automation(session, data: dict) -> dict:
    """전달된 항목만 갱신·검증(분 0~59·음수 방지·mode 화이트리스트). 호출자가 commit."""
    s = get_or_init(session)
    if "crawl_auto_enabled" in data:
        s.crawl_auto_enabled = bool(data["crawl_auto_enabled"])
    if "crawl_interval_hours" in data:
        s.crawl_interval_hours = max(0, int(data["crawl_interval_hours"]))
    if "crawl_interval_minutes" in data:
        s.crawl_interval_minutes = max(0, min(59, int(data["crawl_interval_minutes"])))
    if "autosend_mode" in data:
        s.autosend_mode = "real" if data["autosend_mode"] == "real" else "preview"
    if "autosend_on_purchase" in data:
        s.autosend_on_purchase = bool(data["autosend_on_purchase"])
    if "autosend_on_stock" in data:
        s.autosend_on_stock = bool(data["autosend_on_stock"])
    if "autosend_stock_threshold" in data:
        s.autosend_stock_threshold = max(0, int(data["autosend_stock_threshold"]))
    if "autosend_on_price" in data:
        s.autosend_on_price = bool(data["autosend_on_price"])
    session.flush()
    return get_automation(session)


# ── 역마진 가드 (Phase 1B M3-1) ─────────────────────────────────────────────

def get_min_margin_amount(session) -> int:
    """업로드 최소 마진금액(원). 팀 공유 단일 설정.

    컬럼이 아직 없는 DB(경량 마이그레이션 전)에서도 0 으로 안전하게 떨어진다.
    """
    s = get_or_init(session)
    try:
        return int(getattr(s, "min_margin_amount", 0) or 0)
    except (TypeError, ValueError):
        return 0


def save_min_margin_amount(session, value) -> int:
    """최소 마진금액 저장. 호출자가 commit.

    잘못된 입력을 0 으로 조용히 뭉개지 않는다 — 그러면 가드가 꺼진 줄 모르고
    역마진 상품이 그대로 나간다. 숫자로 못 읽으면 ValueError 로 표면화한다.
    음수는 허용한다("최대 N원까지는 손해 봐도 올린다" 는 사용자의 유효한 선택).
    """
    try:
        v = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"최소 마진금액은 정수(원)여야 합니다: {value!r}")
    s = get_or_init(session)
    s.min_margin_amount = v
    session.flush()
    return v
