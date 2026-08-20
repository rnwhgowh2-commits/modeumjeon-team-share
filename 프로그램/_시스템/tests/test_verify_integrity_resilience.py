# -*- coding: utf-8 -*-
"""돈 무결성 점검 하니스가 **한 점검 실패에 무너지지 않는지**.

왜 필요한가 (2026-08-01 라이브 첫 실행에서 드러난 것)
    `scripts/verify_integrity.py` 는 금전 직결 불변식 7가지를 전 데이터로 검사한다.
    그런데 매일 감시기를 붙여 라이브(PostgreSQL)에서 처음 돌려 보니 **7개가 전부**
    "판정 불가"로 나왔다. 원인은 두 겹이었다.

      ① inv1 이 `options.deleted_at` 을 보는데 그 칸이 없다(활성 표시는 `is_active`).
      ② 그 하나가 깨지자 Postgres 가 트랜잭션을 중단시켰고, 예외만 삼키고 넘어가는
         바람에 **나머지 6개가 도미노로 죽었다**(InFailedSqlTransaction).

    ②가 더 무섭다 — 앞으로 어떤 점검 하나가 깨지기만 하면 감시기가 통째로 눈이 먼다.
    그런데 SQLite 에는 그런 중단이 없어서 **로컬에서는 절대 안 드러난다.**
    그래서 「글자 비교」가 아니라 **「무엇이 참이어야 하는가」**로 못 박는다:
      · 한 점검이 터져도 뒤 점검은 계속 돈다
      · 터지면 세션을 되살린다(rollback) — 이게 ②의 실제 처방
"""
import scripts.verify_integrity as VI


class _FakeSession:
    """rollback 이 불렸는지만 본다."""
    def __init__(self):
        self.rollbacks = 0

    def rollback(self):
        self.rollbacks += 1


def test_한_점검이_터져도_나머지가_계속_돈다(monkeypatch):
    called = []

    def _boom(s):
        called.append("boom")
        raise RuntimeError("표가 없다")

    def _ok(s):
        called.append("ok")
        return VI.Check("OK-1", "멀쩡한 점검", "영향 없음")

    monkeypatch.setattr(VI, "CHECKS", [_boom, _ok, _ok])
    s = _FakeSession()
    results = VI.run_checks(s)

    assert called == ["boom", "ok", "ok"], "앞 점검이 터지자 뒤 점검이 안 돌았다"
    assert len(results) == 3
    assert results[0].count == -1        # 터진 것은 -1(판정 불가)로 표시
    assert results[1].count == 0 and results[2].count == 0


def test_점검이_터지면_세션을_되살린다(monkeypatch):
    """rollback 을 안 하면 PostgreSQL 에서 뒤 점검이 전부 InFailedSqlTransaction 로 죽는다."""
    def _boom(s):
        raise RuntimeError("표가 없다")

    monkeypatch.setattr(VI, "CHECKS", [_boom])
    s = _FakeSession()
    VI.run_checks(s)
    assert s.rollbacks == 1, "점검이 터졌는데 rollback 을 안 했다 — 라이브에서 뒤 점검이 전멸한다"


def test_모든_불변식이_지금_스키마에서_실행된다(tmp_path):
    """SQL 이 **지금 표 모양과 맞는가.** ← 이게 없어서 inv1 의 `options.deleted_at` 을 못 잡았다.

    ★위반이 몇 건이냐를 보는 게 아니다(그건 데이터 문제라 여기서 알 수 없다).
      **문장이 실행은 되느냐**만 본다. 라이브에 감시기를 붙이고 나서야 알았던 것을
      여기서 미리 잡는다 — 칸 이름이 바뀌거나 표가 사라지면 이 검사가 먼저 빨개진다.

    공용 엔진을 안 쓰고 **따로 만든 빈 DB** 에서 돈다(다른 테스트에 영향 주지 않으려고).
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from shared.db import Base

    eng = create_engine(f"sqlite:///{tmp_path / 'schema.db'}")
    Base.metadata.create_all(eng)        # conftest 가 전 모델을 등록해 둔다
    s = sessionmaker(bind=eng)()
    try:
        results = VI.run_checks(s)
    finally:
        s.close()

    broken = [(c.code, c.title, c.money_impact) for c in results if c.count == -1]
    assert not broken, f"지금 스키마와 안 맞는 점검이 있다: {broken}"
    assert len(results) == len(VI.CHECKS)


def _mk(tmp_path, name, rows):
    """(site, 재고, 뒤처짐) 목록으로 stale 상황을 하나 만든다. 상품 시각은 now 고정."""
    import datetime as dt

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from shared.db import Base
    from lemouton.sources.models import SourceOption, SourceProduct

    eng = create_engine(f"sqlite:///{tmp_path / name}")
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    now = dt.datetime(2026, 8, 1, 12, 0, 0)
    for i, (site, stock, delta) in enumerate(rows):
        sp = SourceProduct(site=site, url=f"https://example/{i}", last_fetched_at=now)
        s.add(sp)
        s.flush()
        s.add(SourceOption(source_product_id=sp.id, color_text="블랙",
                           size_text=str(260 + i), current_stock=stock,
                           last_fetched_at=now - delta))
    s.commit()
    return s


def test_inv4는_낡은_숫자만_위반으로_세고_무해한_부류는_따로_적는다(tmp_path):
    """건수만으로는 판단이 안 된다 — 세 부류가 한 숫자에 뭉쳐 있었다(라이브 373건, 이슈 #636).

    ① 1시간 미만 = 한 크롤 안의 기록 순서(옵션 먼저 쓰고 상품 나중). 무해.
    ② 재고 NULL = 화면이 「확인 불가」, 업로드가 「보류」로 안전하게 끊는다.
       게다가 이 부류는 INV-5 가 세는 바로 그 행들이라 총합이 이중으로 부풀었다.
    ③ 재고에 **숫자**가 든 것 = 아무도 낡은 줄 모르고 현재값처럼 쓴다. 이것만이 위반이다.

    ①②를 위반에서 빼되 **숨기지 않는다** — 건수로 남아야 나중에 판단이 된다.
    """
    import datetime as dt

    s = _mk(tmp_path, "inv4.db", [
        ("musinsa", 5, dt.timedelta(seconds=3)),    # ① 무해(기록 순서)
        ("lotteon", None, dt.timedelta(days=55)),   # ② 확인 불가
        ("musinsa", 7, dt.timedelta(days=2)),       # ③ 위반 — 낡은 양수
    ])
    try:
        c = VI.inv4_option_stock_stale(s)
    finally:
        s.close()

    assert c.count == 1, f"낡은 숫자 1건만 위반이어야 한다: {c.samples}"
    joined = " ".join(c.samples)
    assert "2일 뒤처짐" in joined, f"뒤처진 정도가 안 보인다: {c.samples}"
    assert "재고=7" in joined                       # 낡은 '숫자'가 무엇인지도 보여야 한다
    assert "3초" not in joined, "무해한 기록 순서가 위반 목록에 섞였다"
    assert "1일↑ 1건" in c.money_impact
    assert "낡은 양수재고 1건" in c.money_impact
    # 뺀 것들은 숨기지 않고 건수로 남는다
    assert "1시간 미만 1건" in c.money_impact
    assert "재고 NULL 1건" in c.money_impact


def test_inv4_낡았어도_재고가_NULL_이면_위반이_아니다(tmp_path):
    """NULL 은 화면이 「확인 불가」·업로드가 「보류」로 안전하게 끊는다 — 위험은 낡은 **숫자** 쪽이다.

    라이브 실측에서 가장 오래 뒤처진 행들이 전부 `재고=None` 이었다(55일). 그것까지
    위반으로 세면 고칠 곳을 잘못 짚는다. 반대로 품절(0)은 **숫자**다 — 오버셀은 아니지만
    멀쩡한 물건을 품절로 막으므로 계속 빨갛게 남긴다.
    """
    import datetime as dt

    s = _mk(tmp_path, "inv4b.db", [
        ("lotteon", None, dt.timedelta(days=55)),   # 낡았지만 NULL = 위반 아님
        ("lotteon", 0, dt.timedelta(days=55)),      # 품절(0)도 낡은 숫자 = 위반
    ])
    try:
        c = VI.inv4_option_stock_stale(s)
    finally:
        s.close()

    assert c.count == 1, "재고 NULL 이 위반으로 세졌다"
    assert "재고=0" in " ".join(c.samples)
    assert "낡은 양수재고 0건" in c.money_impact   # 오버셀 후보는 0건
    assert "재고 NULL 1건" in c.money_impact


def test_inv4_판매가능_옵션에_안_물린_고아는_그렇게_말한다(tmp_path):
    """「오버셀 후보 48건」이 전부 **아무 옵션에도 안 물린 고아 상품**이었다(2026-08-06 실측).

    낡은 숫자 자체는 데이터 문제지만 **돈**이 되는 건 판매 중인 옵션에 닿을 때뿐이다.
    연결이 0 이면 0 이라고 말해야 사장님이 우선순위를 제대로 잡는다.
    """
    import datetime as dt

    # options 표까지 만들어야 연결을 셀 수 있다(고아 = 연결 0건).
    import lemouton.sourcing.models  # noqa: F401
    s = _mk(tmp_path, "inv4c.db", [("musinsa", 9, dt.timedelta(days=6))])
    from shared.db import Base
    Base.metadata.create_all(s.bind)
    try:
        c = VI.inv4_option_stock_stale(s)
    finally:
        s.close()

    assert c.count == 1
    assert "판매가능 옵션에 물린 것 0건" in c.money_impact


def test_inv5는_대표가_복사본을_구별해_말한다(tmp_path):
    """재고를 못 주는 소싱처(정직한 「확인 불가」)와 **폴백 가격**을 헷갈리면 안 된다.

    라이브 285건은 전부 옵션가 == 상품 대표가였다 = 옵션을 읽은 값이 아니라 복사본.
    """
    import datetime as dt

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from shared.db import Base
    from lemouton.sources.models import SourceOption, SourceProduct

    eng = create_engine(f"sqlite:///{tmp_path / 'inv5.db'}")
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    now = dt.datetime(2026, 8, 1, 12, 0, 0)
    sp = SourceProduct(site="ssg", url="https://example/x",
                       last_price=119900, last_fetched_at=now)
    s.add(sp)
    s.flush()
    # 대표가와 똑같다 = 복사본
    s.add(SourceOption(source_product_id=sp.id, color_text="블랙", size_text="260",
                       current_price=119900, current_stock=None, last_fetched_at=now))
    # 옵션마다 다른 값 = 실제로 읽은 가격(재고만 못 준 정직한 경우)
    s.add(SourceOption(source_product_id=sp.id, color_text="블랙", size_text="270",
                       current_price=131000, current_stock=None, last_fetched_at=now))
    s.commit()
    try:
        c = VI.inv5_price_present_stock_missing(s)
    finally:
        s.close()

    assert c.count == 2
    assert "그중 1건은 가격이 상품 대표가와 같다" in c.money_impact


def test_되살리기까지_실패해도_남은_점검은_시도한다(monkeypatch):
    """DB 가 아주 끊긴 상황에서도 하니스 자체는 끝까지 간다(무한루프·예외전파 없음)."""
    class _DeadSession:
        def rollback(self):
            raise RuntimeError("연결이 끊겼다")

    ran = []

    def _boom(s):
        raise RuntimeError("표가 없다")

    def _ok(s):
        ran.append(1)
        return VI.Check("OK-1", "멀쩡한 점검", "영향 없음")

    monkeypatch.setattr(VI, "CHECKS", [_boom, _ok])
    results = VI.run_checks(_DeadSession())
    assert ran == [1] and len(results) == 2
