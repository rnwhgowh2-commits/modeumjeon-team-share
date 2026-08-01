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


def test_inv4가_얼마나_낡았는지_함께_보고한다(tmp_path):
    """건수만으로는 판단이 안 된다 — **몇 초**(무해)와 **며칠**(위험)을 갈라야 한다.

    한 크롤 안에서 옵션을 먼저 쓰고 상품 행을 나중에 만지면 몇 초 차이로도 stale 로
    잡힌다(기록 순서일 뿐 무해). 반대로 며칠 벌어졌으면 옵션 재고가 진짜로 안 따라온
    것이고, 화면은 그 낡은 숫자를 **현재값처럼** 보여 준다(품절품이 winner = 오버셀).
    그래서 위반 건수만 세지 말고 **뒤처진 정도**를 같이 내놓는다.
    """
    import datetime as dt

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from shared.db import Base
    from lemouton.sources.models import SourceOption, SourceProduct

    eng = create_engine(f"sqlite:///{tmp_path / 'inv4.db'}")
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    now = dt.datetime(2026, 8, 1, 12, 0, 0)
    sp = SourceProduct(site="musinsa", url="https://example/1", last_fetched_at=now)
    s.add(sp)
    s.flush()
    s.add(SourceOption(source_product_id=sp.id, color_text="블랙", size_text="260",
                       current_stock=5, last_fetched_at=now - dt.timedelta(seconds=3)))
    s.add(SourceOption(source_product_id=sp.id, color_text="블랙", size_text="270",
                       current_stock=7, last_fetched_at=now - dt.timedelta(days=2)))
    s.commit()
    try:
        c = VI.inv4_option_stock_stale(s)
    finally:
        s.close()

    assert c.count == 2
    joined = " ".join(c.samples)
    assert "2일 뒤처짐" in joined, f"뒤처진 정도가 안 보인다: {c.samples}"
    assert "3초 뒤처짐" in joined
    assert "재고=7" in joined                       # 낡은 '숫자'가 무엇인지도 보여야 한다
    assert "1시간↑ 1건" in c.money_impact           # 무해(초)와 위험(일)이 갈려 세진다
    assert "1일↑ 1건" in c.money_impact
    assert "2일" in c.samples[0], "뒤처진 순으로 안 나온다 — 위험한 것부터 보여야 한다"


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
